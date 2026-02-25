"""
orchestrator/main.py

Main orchestrator loop for Agent Farm.
Runs every N seconds (default 300 = 5 minutes) and:
1. Reads System Config
2. Sends machine heartbeat
3. Processes human queue notifications
4. Picks up new project ideas → creates research tasks
5. Evaluates active projects (scale / archive)
6. Assigns pending tasks to available agents
7. Checks for self-updates (if enabled)
"""

import logging
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone

import psutil
import schedule
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from orchestrator.notion_client import NotionFarmClient
from orchestrator.llm_client import LLMClient
from orchestrator.project_manager import ProjectManager
from orchestrator.agent_factory import get_agent_for_task
from orchestrator.learnings_manager import LearningsManager

# ─── Logging setup ───────────────────────────────────────────────────────────
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger("orchestrator")
console = Console()

# ─── Machine info ─────────────────────────────────────────────────────────────

def get_machine_name() -> str:
    name = os.environ.get("MACHINE_NAME", "").strip()
    if not name:
        name = socket.gethostname()
    return name


def get_machine_info() -> dict:
    vm = psutil.virtual_memory()
    return {
        "name":      get_machine_name(),
        "ip":        _get_local_ip(),
        "os":        f"{platform.system()} {platform.release()}",
        "ram_gb":    round(vm.total / (1024 ** 3), 1),
        "cpu_cores": psutil.cpu_count(logical=False) or 1,
    }


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ─── Main orchestrator ────────────────────────────────────────────────────────

class Orchestrator:
    def __init__(self):
        self.notion = NotionFarmClient()
        self.llm = LLMClient()
        self.machine = get_machine_info()
        self.machine_name = self.machine["name"]
        self.config: dict = {}
        self._loop_count = 0
        self.learnings = LearningsManager(self.notion, self.llm)

        logger.info(f"Orchestrator starting on machine: [bold]{self.machine_name}[/bold]")
        logger.info(f"LLM Status: {self.llm.get_status()}")

    def _refresh_config(self) -> None:
        """Reload system config from Notion."""
        try:
            self.config = self.notion.get_system_config()
        except Exception as e:
            logger.error(f"Failed to load system config: {e}")

    def _heartbeat(self) -> None:
        """Update machine status in Notion."""
        try:
            models = self._get_local_ollama_models()
            self.notion.upsert_machine(
                name=self.machine_name,
                status="online",
                ip=self.machine["ip"],
                os_name=self.machine["os"],
                ram_gb=self.machine["ram_gb"],
                cpu_cores=self.machine["cpu_cores"],
                models=models,
            )
        except Exception as e:
            logger.warning(f"Heartbeat failed: {e}")

    def _get_local_ollama_models(self) -> list[str]:
        try:
            import httpx
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            r = httpx.get(f"{base_url}/api/tags", timeout=3)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def _process_human_queue(self) -> int:
        """Log tasks that need human attention. Returns count."""
        try:
            tasks = self.notion.get_tasks(status="needs_human")
            if tasks:
                logger.warning(
                    f"[yellow]⚠️  {len(tasks)} task(s) need human attention:[/yellow]"
                )
                for t in tasks:
                    logger.warning(f"  • [{t.get('priority','?')}] {t.get('title','?')} (Project: {t.get('project','?')})")
            return len(tasks)
        except Exception as e:
            logger.error(f"Human queue check failed: {e}")
            return 0

    def _assign_and_run_tasks(self, project_manager: ProjectManager) -> int:
        """
        Get pending tasks and run them with available agents.
        Returns number of tasks dispatched.
        """
        max_concurrent = int(self.config.get("max_concurrent_agents", "3"))
        autonomy_level = int(self.config.get("autonomy_level", "7"))

        if autonomy_level == 0:
            logger.info("Autonomy level 0 — skipping task execution")
            return 0

        # Get available agents for this machine
        agents = self.notion.get_agents(machine=self.machine_name)
        if not agents:
            # No agents configured in Notion for this machine, run with default config
            agents = self._get_default_agents()

        tasks = project_manager.get_pending_tasks_for_machine(
            self.machine_name, max_concurrent
        )

        if not tasks:
            logger.debug("No pending tasks to process")
            return 0

        dispatched = 0
        for task in tasks:
            agent = get_agent_for_task(task, agents, self.notion, self.llm)
            if not agent:
                logger.warning(f"No agent available for task: {task.get('title')}")
                continue

            logger.info(f"Dispatching task '{task.get('title')}' to agent '{agent.name}'")
            result = agent.run(task)

            if result.get("success"):
                dispatched += 1
                self.notion.log_activity(
                    agent=agent.name,
                    project=task.get("project", ""),
                    action="task_completed",
                    result=result.get("result", "")[:300],
                    model_used=result.get("model_used", ""),
                    tokens_used=result.get("tokens_used", 0),
                    cost_usd=result.get("cost_usd", 0.0),
                )
            else:
                logger.error(f"Task failed: {task.get('title')} — {result.get('error')}")

        return dispatched

    def _get_default_agents(self) -> list[dict]:
        """
        Default agent configs when none are registered in Notion.
        One agent per type, using this machine.
        """
        return [
            {"id": "", "name": "research-default", "type": "research",
             "model": "auto", "machine": self.machine_name, "status": "idle",
             "system_prompt": "", "tasks_completed": 0, "success_rate": 0},
            {"id": "", "name": "code-default",     "type": "code",
             "model": "auto", "machine": self.machine_name, "status": "idle",
             "system_prompt": "", "tasks_completed": 0, "success_rate": 0},
            {"id": "", "name": "content-default",  "type": "content",
             "model": "auto", "machine": self.machine_name, "status": "idle",
             "system_prompt": "", "tasks_completed": 0, "success_rate": 0},
        ]

    def _run_strategy_review(self) -> None:
        """Generate weekly strategic review and log to Activity Log."""
        try:
            logger.info("Running weekly strategy review...")
            strategy = self.learnings.generate_strategy_review()
            if strategy:
                self.notion.log_activity(
                    agent="orchestrator",
                    project="",
                    action="task_completed",
                    result=f"Strategy review: {strategy[:300]}",
                )
        except Exception as e:
            logger.error(f"Strategy review failed: {e}")

    def _check_self_update(self) -> bool:
        """Check if there are new commits and self-update if enabled."""
        if self.config.get("self_update_enabled", "true").lower() != "true":
            return False
        try:
            from deploy.self_update import check_and_update
            return check_and_update(self.machine_name, self.notion)
        except Exception as e:
            logger.warning(f"Self-update check failed: {e}")
            return False

    def run_once(self) -> None:
        """Single orchestrator loop iteration."""
        self._loop_count += 1
        start = time.monotonic()
        logger.info(f"\n[bold blue]─── Orchestrator Loop #{self._loop_count} ───[/bold blue]")

        # 1. Refresh config
        self._refresh_config()

        # 2. Heartbeat
        self._heartbeat()

        # 3. Human queue
        human_count = self._process_human_queue()

        # 4–7. Project management
        pm = ProjectManager(self.notion, self.llm, self.config, self.learnings)

        ideas_processed = pm.process_new_ideas()
        if ideas_processed:
            logger.info(f"Processed {ideas_processed} new idea(s)")

        eval_result = pm.evaluate_active_projects()
        if eval_result["scaled"]:
            logger.info(f"Scaled projects: {eval_result['scaled']}")
        if eval_result["archived"]:
            logger.info(f"Archived projects: {eval_result['archived']}")

        dispatched = self._assign_and_run_tasks(pm)

        # Auto-generate ideas: first loop + every hour after
        if self._loop_count == 1 or self._loop_count % 12 == 0:
            pm.auto_generate_ideas()

        # Self-update check (hourly)
        if self._loop_count % 12 == 0:
            self._check_self_update()

        # Strategy review: loop 1 + weekly (2016 loops × 5 min = 7 days)
        if self._loop_count == 1 or self._loop_count % 2016 == 0:
            self._run_strategy_review()

        elapsed = time.monotonic() - start
        logger.info(
            f"Loop done in {elapsed:.1f}s | "
            f"Human queue: {human_count} | "
            f"Ideas: {ideas_processed} | "
            f"Tasks dispatched: {dispatched}"
        )

    def run_forever(self) -> None:
        """Run the orchestrator loop on a schedule."""
        interval = int(self.config.get("loop_interval_seconds", "300"))
        if interval < 30:
            interval = 30  # Safety minimum

        logger.info(f"Starting orchestrator loop every {interval}s")

        # Run immediately on startup
        self.run_once()

        # Schedule recurring runs
        schedule.every(interval).seconds.do(self.run_once)

        while True:
            schedule.run_pending()
            time.sleep(5)


def main():
    console.rule("[bold green]🤖 Agent Farm Orchestrator[/bold green]")

    try:
        orchestrator = Orchestrator()
    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        console.print("Run: [cyan]cp .env.example .env[/cyan] and fill in NOTION_TOKEN")
        sys.exit(1)
    except KeyError as e:
        console.print(f"[red]Database not found: {e}[/red]")
        console.print("Run: [cyan]python notion_setup/setup.py[/cyan] first")
        sys.exit(1)

    try:
        orchestrator.run_forever()
    except KeyboardInterrupt:
        console.print("\n[yellow]Orchestrator stopped by user.[/yellow]")
        # Update machine status to offline
        try:
            orchestrator.notion.heartbeat(orchestrator.machine_name)
            orchestrator.notion._update(
                orchestrator.notion._query(
                    orchestrator.notion.DB_MACHINES,
                    filter_={"property": "name", "title": {"equals": orchestrator.machine_name}}
                )[0]["id"],
                {"status": orchestrator.notion._select("offline")}
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
