"""
agents/research_agent.py

Analyzes business ideas for viability, competition, and monetization potential.
Outputs a structured report and a viability score (0-100).
"""

import json
import logging
import re

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are a business viability analyst for an autonomous AI agent farm.
Your job is to evaluate business ideas and determine if they're worth pursuing.

Focus on:
- Speed to first dollar (days/weeks/meses)
- Whether people are already paying for something similar
- Whether an AI agent can execute it without human help
- Low execution cost relative to revenue potential
- Scalability

Always output valid JSON in your responses when asked.
Be realistic and conservative in revenue estimates.
Prioritize quick wins over ambitious long-term projects."""


VIABILITY_PROMPT = """Evaluate this business idea and return ONLY a JSON object:

IDEA: {idea_name}
DESCRIPTION: {description}
GOAL: {goal}

Score each criterion from 0-100 and provide a brief rationale:

{{
  "time_to_revenue": {{
    "score": 0-100,
    "days_estimate": <number>,
    "rationale": "..."
  }},
  "market_exists": {{
    "score": 0-100,
    "evidence": "...",
    "rationale": "..."
  }},
  "execution_cost": {{
    "score": 0-100,
    "estimated_cost_usd": <number>,
    "rationale": "..."
  }},
  "autonomy": {{
    "score": 0-100,
    "human_touch_points": ["..."],
    "rationale": "..."
  }},
  "scalability": {{
    "score": 0-100,
    "rationale": "..."
  }},
  "overall_score": <weighted average>,
  "recommendation": "ACTIVATE" | "REJECT" | "NEEDS_RESEARCH",
  "next_steps": ["step1", "step2", "step3"],
  "monetization_model": "...",
  "competitive_advantage": "..."
}}

Weights: time_to_revenue=25%, market_exists=20%, execution_cost=20%, autonomy=20%, scalability=15%"""


TASK_PLAN_PROMPT = """Given this research result for project '{project_name}', create an execution task plan.

RESEARCH SUMMARY:
{research_summary}

Create a JSON array of tasks to execute this project. Each task should be doable by an AI agent:

[
  {{
    "title": "...",
    "instructions": "Detailed prompt/instructions for the agent executing this task...",
    "priority": "high" | "medium" | "low",
    "agent_type": "code" | "content" | "research" | "trading",
    "requires_human": false
  }},
  ...
]

Include 3-7 concrete tasks. Be specific in instructions - they will be passed directly to agents.
Start with the task that generates first revenue fastest."""


class ResearchAgent(BaseAgent):
    AGENT_TYPE = "research"
    DEFAULT_LLM_LEVEL = "complex"

    def _default_system_prompt(self) -> str:
        return RESEARCH_SYSTEM_PROMPT

    def _load_learnings_brief(self) -> str:
        try:
            return self.notion.get_config_value("learnings_brief_cache", "")
        except Exception:
            return ""

    def _execute(self, task: dict) -> dict:
        """
        Research task types:
        - viability_check: Score a project idea (0-100) and decide to activate
        - market_research: Deep dive into a specific market/niche
        - generate_ideas: Auto-generate new project ideas
        """
        instructions = task.get("instructions", "")
        project = task.get("project", "")

        # Detect task subtype from instructions
        if "VIABILITY_CHECK" in instructions.upper():
            return self._viability_check(task)
        elif "GENERATE_IDEAS" in instructions.upper():
            return self._generate_ideas(task)
        else:
            return self._general_research(task)

    def _viability_check(self, task: dict) -> dict:
        """Score a project idea and create execution plan if viable."""
        project_name = task.get("project", "Unknown Project")
        instructions = task.get("instructions", "")

        # Extract description/goal from instructions
        description = self._extract_field(instructions, "DESCRIPTION") or instructions
        goal = self._extract_field(instructions, "GOAL") or "Generate revenue"

        # Step 1: Get viability score (with historical calibration if available)
        base_prompt = VIABILITY_PROMPT.format(
            idea_name=project_name,
            description=description,
            goal=goal,
        )
        learnings_context = self._load_learnings_brief()
        if learnings_context:
            prompt = (
                learnings_context + "\n\n"
                "Use the above context to calibrate your scores. "
                "If this idea matches a known failure pattern, score lower. "
                "If it matches a success pattern, increase time_to_revenue and market_exists scores.\n\n"
                + base_prompt
            )
        else:
            prompt = base_prompt
        llm_response = self._call_llm(prompt, max_tokens=2000, level="complex")
        raw = llm_response["result"]

        # Parse JSON
        try:
            analysis = self._parse_json(raw)
        except Exception as e:
            logger.warning(f"Failed to parse viability JSON: {e}. Raw: {raw[:200]}")
            analysis = {"overall_score": 0, "recommendation": "NEEDS_RESEARCH"}

        overall_score = float(analysis.get("overall_score", 0))
        recommendation = analysis.get("recommendation", "REJECT")

        # Update project viability score in Notion
        projects = self.notion.get_projects()
        project_row = next((p for p in projects if p["name"] == project_name), None)
        if project_row:
            self.notion.update_project_viability(project_row["id"], overall_score)

        result_text = f"Viability Score: {overall_score}/100\nRecommendation: {recommendation}\n\n"

        if recommendation == "ACTIVATE" and overall_score >= 60:
            # Create execution tasks
            plan_prompt = TASK_PLAN_PROMPT.format(
                project_name=project_name,
                research_summary=json.dumps(analysis, indent=2)[:3000],
            )
            plan_response = self._call_llm(plan_prompt, max_tokens=2000, level="complex")
            try:
                tasks = self._parse_json(plan_response["result"])
                if isinstance(tasks, list):
                    for t in tasks:
                        self.notion.create_task(
                            title=t.get("title", "Task"),
                            project=project_name,
                            instructions=t.get("instructions", ""),
                            priority=t.get("priority", "medium"),
                            requires_human=t.get("requires_human", False),
                        )
                    result_text += f"Created {len(tasks)} execution tasks.\n"
                    result_text += f"First task: {tasks[0].get('title', '')}\n"
            except Exception as e:
                logger.warning(f"Failed to create task plan: {e}")

            # Activate project
            if project_row:
                self.notion.update_project_status(project_row["id"], "active")
            result_text += "\nProject ACTIVATED."

        elif recommendation == "REJECT" or overall_score < 60:
            if project_row:
                self.notion.update_project_status(
                    project_row["id"], "archived",
                    reason=f"Viability score {overall_score}/100 below threshold. {analysis.get('recommendation', '')}"
                )
            result_text += "\nProject ARCHIVED (below viability threshold)."

        result_text += f"\n\nFull Analysis:\n{json.dumps(analysis, indent=2)}"

        total_tokens = llm_response["tokens_used"]
        total_cost = llm_response["cost_usd"]

        return {
            "result":      result_text,
            "tokens_used": total_tokens,
            "cost_usd":    total_cost,
            "model_used":  llm_response["model_used"],
        }

    def _generate_ideas(self, task: dict) -> dict:
        """Auto-generate new project ideas and add them to Notion Projects."""
        instructions = task.get("instructions", "")
        count = 3

        has_learnings = "WHAT WE KNOW FROM PAST PROJECTS" in instructions

        prompt = f"""Generate {count} profitable micro-SaaS or digital product ideas that AI agents can execute autonomously.

Prioritize:
1. Quick time to first revenue (days/weeks)
2. Proven market (people paying for similar things)
3. Minimal human intervention needed
4. Low running cost

For each idea output JSON:
[
  {{
    "name": "Short project name",
    "description": "What it is and how it works",
    "goal": "How it generates revenue",
    "category": "saas|content|service|data|trading",
    "estimated_days_to_revenue": <number>,
    "why_this_will_work": "one sentence connecting to known patterns or market evidence"
  }},
  ...
]

Context/constraints: {instructions}"""

        if has_learnings:
            prompt += "\nCRITICAL: Use the learnings to guide your ideas. Replicate success patterns, avoid failure patterns.\n"

        response = self._call_llm(prompt, max_tokens=2000, level="complex")
        try:
            ideas = self._parse_json(response["result"])
            created = []
            if isinstance(ideas, list):
                for idea in ideas:
                    # Create project in Notion with status=idea
                    self.notion._create(
                        self.notion.DB_PROJECTS,
                        {
                            "name":        self.notion._title(idea.get("name", "New Idea")),
                            "status":      self.notion._select("idea"),
                            "source":      self.notion._select("auto_generated"),
                            "description": self.notion._text(idea.get("description", "")),
                            "goal":        self.notion._text(idea.get("goal", "")),
                            "created_at":  self.notion._date(),
                        }
                    )
                    created.append(idea.get("name", "?"))

            result = f"Generated {len(created)} ideas: {', '.join(created)}"
        except Exception as e:
            result = f"Failed to parse ideas: {e}\nRaw: {response['result'][:500]}"

        return {
            "result":      result,
            "tokens_used": response["tokens_used"],
            "cost_usd":    response["cost_usd"],
            "model_used":  response["model_used"],
        }

    def _general_research(self, task: dict) -> dict:
        """General research/analysis task."""
        prompt = task.get("instructions", "Perform a business research analysis.")
        return self._call_llm(prompt, max_tokens=3000, level="complex")

    @staticmethod
    def _extract_field(text: str, field: str) -> str:
        """Extract FIELD: value from instruction text."""
        pattern = rf"{field}:\s*(.+?)(?:\n[A-Z_]+:|$)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _parse_json(text: str) -> any:
        """Extract and parse JSON from LLM output."""
        # Try direct parse
        try:
            return json.loads(text)
        except Exception:
            pass
        # Find JSON block
        for pattern in [r"```json\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```",
                        r"(\{[\s\S]*\})", r"(\[[\s\S]*\])"]:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    continue
        raise ValueError("No valid JSON found in response")
