"""
orchestrator/learnings_manager.py

Converts completed/archived projects into reusable intelligence.
Stores structured learnings in Notion System Config (chunked JSON) and
exposes a brief string for injection into idea-generation & viability prompts.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

EMPTY_LEARNINGS: dict = {
    "successful_patterns": [],     # max 20, rolling
    "failure_patterns": [],        # max 20, rolling
    "category_performance": {},    # {cat: {avg_revenue, success_rate, count}}
    "viability_insights": {
        "avg_score_of_successes": None,
        "avg_score_of_failures": None,
    },
    "market_insights": [],         # promising niches, max 10
    "avoid_list": [],              # patterns with >=2 failures, max 15
    "meta": {
        "total_projects_analyzed": 0,
        "last_updated": None,
        "analyzed_project_ids": [],  # idempotency
    },
}

_FAILURE_PROMPT = """Analyze this FAILED project and return ONLY a JSON object.

Project data:
- Name: {name}
- Description: {description}
- Category: {category}
- Cost incurred: ${cost:.2f}
- Revenue generated: ${revenue:.2f}
- Days active: {days}
- Archived reason: {reason}

Return JSON:
{{
  "category": "...",
  "failure_reason": "one sentence",
  "cost_wasted": <number>,
  "warning_signs": ["sign1", "sign2"],
  "lesson": "key lesson in one sentence",
  "avoid_pattern": "short label for pattern to avoid (e.g. 'crypto signals without data')"
}}"""

_SUCCESS_PROMPT = """Analyze this SUCCESSFUL project and return ONLY a JSON object.

Project data:
- Name: {name}
- Description: {description}
- Category: {category}
- Revenue (30d): ${revenue_30d:.2f}
- Viability score when started: {viability_score}

Return JSON:
{{
  "category": "...",
  "why_it_worked": "one sentence",
  "success_factors": ["factor1", "factor2"],
  "replicable_pattern": "short label for pattern (e.g. 'landing + stripe quick win')",
  "recommended_niches": ["niche1", "niche2"]
}}"""

_STRATEGY_PROMPT = """You are the strategic director of an autonomous AI agent farm whose goal is
to maximise revenue. Review the historical data below and output a strategic brief.

PROJECTS SUMMARY:
{projects_summary}

LEARNINGS:
{learnings_summary}

Output a plain-text brief (no JSON) covering:
1. Top 3 categories to prioritise NOW (with 1-line rationale each)
2. Top 3 approaches to abandon
3. Recommended viability score threshold (0-100)
4. Idea focus for the next 7 days
5. One contrarian bet worth exploring

Keep it under 600 words."""


class LearningsManager:
    """Manages the continuous learning cycle for Agent Farm."""

    LEARNINGS_KEY = "learnings_json"
    BRIEF_KEY = "learnings_brief_cache"

    def __init__(self, notion_client, llm_client):
        self.notion = notion_client
        self.llm = llm_client

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_from_project(self, project: dict, outcome: str) -> bool:
        """
        Extract learnings from a project (outcome='success'|'failure').
        Idempotent: projects already analyzed are skipped.
        Returns True if new learning was extracted.
        """
        project_id = project.get("id", "")
        data = self._load_learnings()

        if project_id and project_id in data["meta"]["analyzed_project_ids"]:
            logger.debug(f"Project {project.get('name')} already analyzed, skipping")
            return False

        try:
            if outcome == "failure":
                learning = self._extract_failure_learning(project)
            else:
                learning = self._extract_success_learning(project)

            if learning:
                self._merge_learning_into_data(data, learning, outcome, project)
                self._save_learnings(data)
                logger.info(
                    f"Extracted {outcome} learning from '{project.get('name')}'"
                )
                return True
        except Exception as e:
            logger.error(f"Failed to extract learning from '{project.get('name')}': {e}")

        return False

    def get_intelligence_brief(self) -> str:
        """
        Return a pre-computed brief string (≤6000 chars) cached in Notion.
        Returns empty string if no data yet (silent on first loops).
        """
        try:
            brief = self.notion.get_config_value(self.BRIEF_KEY, "")
            return brief
        except Exception as e:
            logger.debug(f"Could not load intelligence brief: {e}")
            return ""

    def generate_strategy_review(self) -> str:
        """
        Generate a weekly strategic review via LLM and store in Notion.
        Returns the strategy text.
        """
        data = self._load_learnings()
        if data["meta"]["total_projects_analyzed"] == 0:
            logger.debug("No projects analyzed yet, skipping strategy review")
            return ""

        try:
            projects = (
                self.notion.get_projects(status="archived") +
                self.notion.get_projects(status="scaling") +
                self.notion.get_projects(status="active")
            )
            projects_summary = self._summarize_projects(projects)
            learnings_summary = self._build_brief_text(data)

            prompt = _STRATEGY_PROMPT.format(
                projects_summary=projects_summary[:3000],
                learnings_summary=learnings_summary[:2000],
            )
            response = self.llm.complete(prompt, level="complex", max_tokens=1000)
            strategy = (response.content if hasattr(response, "content") else response.get("result", "")).strip()

            if strategy:
                self.notion.set_config_value("strategy_brief", strategy[:2000])
                logger.info("Strategy review generated and saved")

            return strategy
        except Exception as e:
            logger.error(f"Strategy review failed: {e}")
            return ""

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_learnings(self) -> dict:
        try:
            raw = self.notion.get_config_value_large(self.LEARNINGS_KEY, "")
            if raw:
                data = json.loads(raw)
                # Ensure all keys exist (forward-compatible)
                for k, v in EMPTY_LEARNINGS.items():
                    if k not in data:
                        data[k] = json.loads(json.dumps(v))
                return data
        except Exception as e:
            logger.debug(f"Could not load learnings, starting fresh: {e}")
        return json.loads(json.dumps(EMPTY_LEARNINGS))

    def _save_learnings(self, data: dict) -> None:
        data["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(data, default=str)
        self.notion.set_config_value_large(self.LEARNINGS_KEY, serialized)
        # Rebuild and cache the brief
        brief = self._build_brief_text(data)
        self.notion.set_config_value(self.BRIEF_KEY, brief[:6000])

    def _extract_failure_learning(self, project: dict) -> Optional[dict]:
        created = project.get("created_at")
        last = project.get("last_activity")
        days = 0
        if created and last:
            try:
                days = max(0, (last - created).days)
            except Exception:
                pass

        prompt = _FAILURE_PROMPT.format(
            name=project.get("name", "Unknown"),
            description=(project.get("description") or "")[:500],
            category=self._infer_category(project),
            cost=project.get("cost_total", 0.0) or 0.0,
            revenue=project.get("revenue_total", 0.0) or 0.0,
            days=days,
            reason=(project.get("archived_reason") or "")[:300],
        )
        response = self.llm.complete(prompt, level="complex", max_tokens=400)
        raw = response.content if hasattr(response, "content") else response.get("result", "")
        return self._parse_json_safe(raw)

    def _extract_success_learning(self, project: dict) -> Optional[dict]:
        prompt = _SUCCESS_PROMPT.format(
            name=project.get("name", "Unknown"),
            description=(project.get("description") or "")[:500],
            category=self._infer_category(project),
            revenue_30d=project.get("revenue_30d", 0.0) or 0.0,
            viability_score=project.get("viability_score") or "unknown",
        )
        response = self.llm.complete(prompt, level="complex", max_tokens=400)
        raw = response.content if hasattr(response, "content") else response.get("result", "")
        return self._parse_json_safe(raw)

    def _merge_learning_into_data(self, data: dict, learning: dict,
                                   outcome: str, project: dict) -> None:
        name = project.get("name", "Unknown")
        project_id = project.get("id", "")
        category = learning.get("category") or self._infer_category(project)

        if outcome == "failure":
            entry = {
                "project": name,
                "category": category,
                "failure_reason": learning.get("failure_reason", ""),
                "lesson": learning.get("lesson", ""),
                "avoid_pattern": learning.get("avoid_pattern", ""),
                "cost_wasted": learning.get("cost_wasted", 0),
            }
            patterns = data["failure_patterns"]
            patterns.append(entry)
            if len(patterns) > 20:
                data["failure_patterns"] = patterns[-20:]

            # Update avoid_list: add pattern if it has appeared >=2 times
            avoid_pat = learning.get("avoid_pattern", "").strip()
            if avoid_pat:
                existing_count = sum(
                    1 for fp in data["failure_patterns"]
                    if fp.get("avoid_pattern", "").lower() == avoid_pat.lower()
                )
                avoid_list = data["avoid_list"]
                already_listed = any(
                    a.lower() == avoid_pat.lower() for a in avoid_list
                )
                if existing_count >= 2 and not already_listed:
                    avoid_list.append(avoid_pat)
                    if len(avoid_list) > 15:
                        data["avoid_list"] = avoid_list[-15:]

            # Update category performance
            self._update_category_perf(
                data, category, success=False,
                revenue=project.get("revenue_30d", 0.0) or 0.0,
                viability_score=project.get("viability_score"),
            )
            # Update viability insights
            score = project.get("viability_score")
            if score is not None:
                vi = data["viability_insights"]
                self._update_rolling_avg(vi, "avg_score_of_failures", float(score))

        else:  # success
            entry = {
                "project": name,
                "category": category,
                "why_it_worked": learning.get("why_it_worked", ""),
                "replicable_pattern": learning.get("replicable_pattern", ""),
                "success_factors": learning.get("success_factors", []),
            }
            patterns = data["successful_patterns"]
            patterns.append(entry)
            if len(patterns) > 20:
                data["successful_patterns"] = patterns[-20:]

            # Add recommended niches to market_insights
            for niche in learning.get("recommended_niches", []):
                if niche and niche not in data["market_insights"]:
                    data["market_insights"].append(niche)
            if len(data["market_insights"]) > 10:
                data["market_insights"] = data["market_insights"][-10:]

            # Update category performance
            self._update_category_perf(
                data, category, success=True,
                revenue=project.get("revenue_30d", 0.0) or 0.0,
                viability_score=project.get("viability_score"),
            )
            # Update viability insights
            score = project.get("viability_score")
            if score is not None:
                vi = data["viability_insights"]
                self._update_rolling_avg(vi, "avg_score_of_successes", float(score))

        # Meta
        data["meta"]["total_projects_analyzed"] += 1
        if project_id:
            data["meta"]["analyzed_project_ids"].append(project_id)

    def _update_category_perf(self, data: dict, category: str,
                               success: bool, revenue: float,
                               viability_score) -> None:
        perf = data["category_performance"]
        if category not in perf:
            perf[category] = {"avg_revenue": 0.0, "success_rate": 0.0, "count": 0}
        cat = perf[category]
        n = cat["count"]
        cat["avg_revenue"] = (cat["avg_revenue"] * n + revenue) / (n + 1)
        cat["success_rate"] = (cat["success_rate"] * n + (1.0 if success else 0.0)) / (n + 1)
        cat["count"] = n + 1

    @staticmethod
    def _update_rolling_avg(container: dict, key: str, new_value: float) -> None:
        current = container.get(key)
        if current is None:
            container[key] = new_value
        else:
            container[key] = (current + new_value) / 2

    def _build_brief_text(self, data: dict) -> str:
        """Build a human-readable brief ≤6000 chars from the learnings data."""
        n = data["meta"]["total_projects_analyzed"]
        if n == 0:
            return ""

        lines = [
            "=== WHAT WE KNOW FROM PAST PROJECTS ===",
            f"(Based on {n} analyzed project{'s' if n != 1 else ''})",
            "",
        ]

        if data["successful_patterns"]:
            lines.append("WHAT WORKS:")
            for p in data["successful_patterns"][-5:]:
                cat = p.get("category", "?")
                pat = p.get("replicable_pattern") or p.get("why_it_worked", "")
                lines.append(f"  - [{cat}] {pat}")
            lines.append("")

        if data["failure_patterns"]:
            lines.append("WHAT FAILED:")
            for p in data["failure_patterns"][-5:]:
                cat = p.get("category", "?")
                cost = p.get("cost_wasted", 0)
                lesson = p.get("lesson") or p.get("failure_reason", "")
                lines.append(f"  - [{cat}] {lesson} (wasted ${cost:.2f})")
            lines.append("")

        if data["category_performance"]:
            lines.append("CATEGORY PERFORMANCE:")
            for cat, stats in data["category_performance"].items():
                sr = stats["success_rate"] * 100
                avg_rev = stats["avg_revenue"]
                cnt = stats["count"]
                lines.append(
                    f"  - {cat}: {sr:.0f}% success, avg ${avg_rev:.0f}/30d, n={cnt}"
                )
            lines.append("")

        if data["avoid_list"]:
            lines.append("AVOID: " + " | ".join(data["avoid_list"]))
            lines.append("")

        vi = data["viability_insights"]
        if vi.get("avg_score_of_successes") is not None or vi.get("avg_score_of_failures") is not None:
            s_avg = vi.get("avg_score_of_successes")
            f_avg = vi.get("avg_score_of_failures")
            parts = []
            if s_avg is not None:
                parts.append(f"Successes avg {s_avg:.0f}/100")
            if f_avg is not None:
                parts.append(f"failures avg {f_avg:.0f}/100")
            lines.append(f"VIABILITY CALIBRATION: {', '.join(parts)}")
            lines.append("")

        if data["market_insights"]:
            lines.append("PROMISING NICHES: " + ", ".join(data["market_insights"][:5]))
            lines.append("")

        lines.append("=== END OF LEARNINGS ===")
        return "\n".join(lines)

    @staticmethod
    def _infer_category(project: dict) -> str:
        desc = (
            (project.get("description") or "") + " " +
            (project.get("name") or "")
        ).lower()
        for cat in ("trading", "saas", "content", "data", "service"):
            if cat in desc:
                return cat
        return "other"

    @staticmethod
    def _summarize_projects(projects: list) -> str:
        lines = []
        for p in projects[:30]:
            lines.append(
                f"- {p.get('name','?')} [{p.get('status','?')}] "
                f"revenue=${p.get('revenue_30d',0):.2f}/30d "
                f"score={p.get('viability_score','?')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_json_safe(text: str) -> Optional[dict]:
        import re
        for pattern in [r"```json\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```",
                        r"(\{[\s\S]*\})"]:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    continue
        try:
            return json.loads(text)
        except Exception:
            return None
