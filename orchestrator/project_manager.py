"""
orchestrator/project_manager.py

Manages project lifecycle: idea → research → active → scaling/archived.
Evaluates projects and auto-generates new ideas.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class ProjectManager:
    def __init__(self, notion_client, llm_client, config: dict, learnings_manager=None):
        self.notion = notion_client
        self.llm = llm_client
        self.config = config
        self.learnings = learnings_manager

        # Config values
        self.scale_threshold   = float(config.get("scale_threshold_usd", "10"))
        self.archive_days      = int(config.get("archive_days_no_revenue", "21"))
        self.max_cost          = float(config.get("max_cost_per_project_usd", "5"))
        self.parallel_max      = int(config.get("parallel_projects_max", "10"))
        self.viability_threshold = float(config.get("viability_threshold", "60"))

    def process_new_ideas(self) -> int:
        """
        Pick up projects with status=idea and create viability research tasks.
        Returns number of ideas processed.
        """
        ideas = self.notion.get_projects(status="idea")
        created = 0

        for project in ideas:
            project_id = project["id"]
            name = project["name"]

            # Check if already has a pending/in_progress research task
            existing_tasks = self.notion.get_tasks(
                status=None, project=name
            )
            has_research_task = any(
                "viability" in (t.get("title") or "").lower() or
                "research" in (t.get("title") or "").lower()
                for t in existing_tasks
                if t.get("status") in ("pending", "in_progress")
            )

            if has_research_task:
                logger.debug(f"Project '{name}' already has a research task, skipping")
                continue

            # Create research task
            instructions = (
                f"VIABILITY_CHECK\n"
                f"DESCRIPTION: {project.get('description', 'No description provided')}\n"
                f"GOAL: {project.get('goal', 'Generate revenue')}"
            )

            self.notion.create_task(
                title=f"Research: Viability check for '{name}'",
                project=name,
                instructions=instructions,
                priority="high",
            )

            # Move project to research status
            self.notion.update_project_status(project_id, "research")

            self.notion.log_activity(
                agent="orchestrator",
                project=name,
                action="project_created",
                result=f"Moved to research phase, viability task created",
            )

            logger.info(f"Created viability research task for project: {name}")
            created += 1

        return created

    def evaluate_active_projects(self) -> dict:
        """
        Evaluate all active/scaling projects:
        - Scale if revenue_30d > threshold
        - Archive if no revenue for too long and high cost
        Returns dict with actions taken.
        """
        actions = {"scaled": [], "archived": [], "evaluated": 0}
        active = self.notion.get_projects(status="active")
        scaling = self.notion.get_projects(status="scaling")
        projects = active + scaling

        now = datetime.now(timezone.utc)
        actions["evaluated"] = len(projects)

        for project in projects:
            name = project["name"]
            project_id = project["id"]
            revenue_30d = project.get("revenue_30d", 0.0) or 0.0
            cost_total = project.get("cost_total", 0.0) or 0.0
            last_activity = project.get("last_activity")

            # Recalculate revenue from Revenue Log
            actual_30d = self.notion.get_revenue_for_project(name, since_days=30)
            if abs(actual_30d - revenue_30d) > 0.01:
                # Recalculate total too
                actual_total = self.notion.get_revenue_for_project(name, since_days=3650)
                self.notion.update_project_revenue(project_id, actual_total, actual_30d)
                revenue_30d = actual_30d

            # Check for scaling
            if revenue_30d >= self.scale_threshold and project.get("status") != "scaling":
                self._scale_project(project)
                actions["scaled"].append(name)
                continue

            # Check for archiving
            days_since_activity = 999
            if last_activity:
                days_since_activity = (now - last_activity).days

            should_archive = (
                days_since_activity > self.archive_days and
                revenue_30d == 0.0 and
                project.get("status") != "scaling"
            )
            if should_archive:
                reason = (
                    f"No revenue in {days_since_activity} days "
                    f"(threshold: {self.archive_days}d). "
                    f"Cost incurred: ${cost_total:.2f}"
                )
                self.notion.update_project_status(project_id, "archived", reason=reason)
                self.notion.log_activity(
                    agent="orchestrator",
                    project=name,
                    action="project_archived",
                    result=reason,
                )
                logger.info(f"Archived project: {name} — {reason}")
                if self.learnings:
                    self.learnings.extract_from_project(project, outcome="failure")
                actions["archived"].append(name)

        return actions

    def _scale_project(self, project: dict) -> None:
        """Mark project for scaling and create a scaling task."""
        project_id = project["id"]
        name = project["name"]
        revenue_30d = project.get("revenue_30d", 0.0)

        self.notion.update_project_status(project_id, "scaling")
        if self.learnings:
            self.learnings.extract_from_project(project, outcome="success")

        # Create scaling analysis task
        self.notion.create_task(
            title=f"Scale: Analyze scaling opportunities for '{name}'",
            project=name,
            instructions=(
                f"RESEARCH: Scaling analysis\n"
                f"Project '{name}' is generating ${revenue_30d:.2f}/month.\n"
                f"Analyze:\n"
                f"1. Current bottlenecks\n"
                f"2. Top 3 scaling opportunities (traffic, pricing, new markets)\n"
                f"3. Required resources and timeline\n"
                f"4. Recommended immediate action\n"
                f"Output a concrete action plan."
            ),
            priority="high",
        )

        self.notion.log_activity(
            agent="orchestrator",
            project=name,
            action="project_scaled",
            result=f"Revenue ${revenue_30d:.2f}/30d exceeded threshold ${self.scale_threshold:.2f}",
        )
        logger.info(f"Scaling project: {name} (${revenue_30d:.2f}/30d)")

    def auto_generate_ideas(self) -> int:
        """
        Auto-generate new project ideas if below parallel_max.
        Returns number of ideas generated (tasks created).
        """
        active_projects = (
            self.notion.get_projects(status="active") +
            self.notion.get_projects(status="research") +
            self.notion.get_projects(status="scaling")
        )

        if len(active_projects) >= self.parallel_max:
            logger.debug(f"At max projects ({self.parallel_max}), skipping idea generation")
            return 0

        learnings_brief = self.learnings.get_intelligence_brief() if self.learnings else ""
        strategy_brief = self.notion.get_config_value("strategy_brief", "")

        instructions = (
            "GENERATE_IDEAS\n"
            f"Generate 3 new profitable micro-project ideas.\n"
            f"Current active projects: {[p['name'] for p in active_projects]}\n"
            "Avoid ideas similar to existing projects. "
            "Focus on quick wins with minimal execution cost.\n"
        )
        if learnings_brief:
            instructions += f"\n{learnings_brief}\n"
        if strategy_brief:
            instructions += f"\nSTRATEGIC DIRECTION:\n{strategy_brief}\n"

        self.notion.create_task(
            title="Auto-generate new project ideas",
            project="",
            instructions=instructions,
            priority="low",
        )
        logger.info("Created auto-generate ideas task")
        return 1

    def get_pending_tasks_for_machine(self, machine_name: str,
                                       max_concurrent: int) -> list[dict]:
        """
        Get pending tasks that this machine can work on.
        Respects max_concurrent limit.
        """
        # Count currently in-progress tasks on this machine
        in_progress = self.notion.get_tasks(status="in_progress")
        current_load = len([
            t for t in in_progress
            if machine_name.lower() in (t.get("agent") or "").lower()
        ])

        available_slots = max(0, max_concurrent - current_load)
        if available_slots == 0:
            return []

        pending = self.notion.get_tasks(status="pending")
        # Exclude tasks that require human
        actionable = [t for t in pending if not t.get("requires_human")]

        # Sort by priority
        priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        actionable.sort(key=lambda t: priority_order.get(t.get("priority", "medium"), 2))

        return actionable[:available_slots]
