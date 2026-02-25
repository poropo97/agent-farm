"""
orchestrator/notion_client.py

Wrapper around the Notion API for all Agent Farm read/write operations.
Handles all 7 databases via typed methods.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from notion_client import Client
from tenacity import retry, stop_after_attempt, wait_exponential

# Load DB IDs from the setup file
_DB_IDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "notion_setup", "db_ids.json"
)


def _load_db_ids() -> dict:
    if os.path.exists(_DB_IDS_PATH):
        with open(_DB_IDS_PATH) as f:
            return json.load(f)
    return {}


class NotionFarmClient:
    """
    Central client for all Notion operations in Agent Farm.
    Uses database IDs from notion_setup/db_ids.json.
    """

    DB_SYSTEM_CONFIG = "⚙️ System Config"
    DB_MACHINES      = "🖥️ Machines"
    DB_AGENTS        = "🧠 Agents"
    DB_PROJECTS      = "💡 Projects"
    DB_TASKS         = "✅ Tasks"
    DB_REVENUE_LOG   = "💰 Revenue Log"
    DB_ACTIVITY_LOG  = "📋 Activity Log"

    def __init__(self):
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            raise ValueError("NOTION_TOKEN not set in environment")
        self.notion = Client(auth=token)
        self._db_ids = _load_db_ids()

    def _db(self, name: str) -> str:
        if name not in self._db_ids:
            raise KeyError(
                f"Database '{name}' not found in db_ids.json. "
                "Run `python notion_setup/setup.py` first."
            )
        return self._db_ids[name]

    # ─── Generic helpers ────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _query(self, db_name: str, filter_: Optional[dict] = None,
               sorts: Optional[list] = None) -> list[dict]:
        kwargs: dict[str, Any] = {"database_id": self._db(db_name)}
        if filter_:
            kwargs["filter"] = filter_
        if sorts:
            kwargs["sorts"] = sorts
        results = []
        while True:
            resp = self.notion.databases.query(**kwargs)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            kwargs["start_cursor"] = resp["next_cursor"]
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _create(self, db_name: str, properties: dict) -> dict:
        return self.notion.pages.create(
            parent={"database_id": self._db(db_name)},
            properties=properties,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def _update(self, page_id: str, properties: dict) -> dict:
        return self.notion.pages.update(page_id=page_id, properties=properties)

    # ─── Property builders ───────────────────────────────────────────────────

    @staticmethod
    def _title(text: str) -> dict:
        return {"title": [{"text": {"content": text[:2000]}}]}

    @staticmethod
    def _text(text: str) -> dict:
        return {"rich_text": [{"text": {"content": str(text)[:2000]}}]}

    @staticmethod
    def _select(option: str) -> dict:
        return {"select": {"name": option}}

    @staticmethod
    def _multiselect(options: list[str]) -> dict:
        return {"multi_select": [{"name": o} for o in options]}

    @staticmethod
    def _number(value: float) -> dict:
        return {"number": value}

    @staticmethod
    def _checkbox(value: bool) -> dict:
        return {"checkbox": value}

    @staticmethod
    def _date(dt: Optional[datetime] = None) -> dict:
        if dt is None:
            dt = datetime.now(timezone.utc)
        return {"date": {"start": dt.isoformat()}}

    # ─── Property readers ────────────────────────────────────────────────────

    @staticmethod
    def _read_title(page: dict, key: str) -> str:
        parts = page.get("properties", {}).get(key, {}).get("title", [])
        return "".join(p.get("plain_text", "") for p in parts)

    @staticmethod
    def _read_text(page: dict, key: str) -> str:
        parts = page.get("properties", {}).get(key, {}).get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts)

    @staticmethod
    def _read_select(page: dict, key: str) -> Optional[str]:
        sel = page.get("properties", {}).get(key, {}).get("select")
        return sel["name"] if sel else None

    @staticmethod
    def _read_multiselect(page: dict, key: str) -> list[str]:
        items = page.get("properties", {}).get(key, {}).get("multi_select", [])
        return [i["name"] for i in items]

    @staticmethod
    def _read_number(page: dict, key: str) -> Optional[float]:
        return page.get("properties", {}).get(key, {}).get("number")

    @staticmethod
    def _read_checkbox(page: dict, key: str) -> bool:
        return page.get("properties", {}).get(key, {}).get("checkbox", False)

    @staticmethod
    def _read_date(page: dict, key: str) -> Optional[datetime]:
        d = page.get("properties", {}).get(key, {}).get("date")
        if d and d.get("start"):
            try:
                return datetime.fromisoformat(d["start"].replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    # ─── System Config ───────────────────────────────────────────────────────

    def get_system_config(self) -> dict[str, str]:
        """Returns all config as {key: value} dict."""
        rows = self._query(self.DB_SYSTEM_CONFIG)
        config = {}
        for row in rows:
            k = self._read_title(row, "key")
            v = self._read_text(row, "value")
            if k:
                config[k] = v
        return config

    def get_config_value(self, key: str, default: str = "") -> str:
        config = self.get_system_config()
        return config.get(key, default)

    def set_config_value(self, key: str, value: str) -> str:
        """Upsert a single key in System Config. Returns page_id."""
        existing = self._query(
            self.DB_SYSTEM_CONFIG,
            filter_={"property": "key", "title": {"equals": key}}
        )
        props = {
            "key":   self._title(key),
            "value": self._text(str(value)[:2000]),
        }
        if existing:
            page_id = existing[0]["id"]
            self._update(page_id, props)
            return page_id
        else:
            page = self._create(self.DB_SYSTEM_CONFIG, props)
            return page["id"]

    def set_config_value_large(self, key: str, value: str) -> None:
        """Store a large string by chunking into 1900-char pieces.

        Saves: key, key__1, key__2, ... key__N  plus  key__chunks = N+1
        """
        chunk_size = 1900
        chunks = [value[i:i + chunk_size] for i in range(0, max(len(value), 1), chunk_size)]
        for idx, chunk in enumerate(chunks):
            chunk_key = key if idx == 0 else f"{key}__{idx}"
            self.set_config_value(chunk_key, chunk)
        # Remove any stale chunks beyond current count
        self.set_config_value(f"{key}__chunks", str(len(chunks)))

    def get_config_value_large(self, key: str, default: str = "") -> str:
        """Reassemble a value stored via set_config_value_large."""
        config = self.get_system_config()
        n_str = config.get(f"{key}__chunks", "0")
        try:
            n = int(n_str)
        except ValueError:
            n = 0
        if n == 0:
            return config.get(key, default)
        parts = []
        for idx in range(n):
            chunk_key = key if idx == 0 else f"{key}__{idx}"
            parts.append(config.get(chunk_key, ""))
        return "".join(parts)

    # ─── Machines ────────────────────────────────────────────────────────────

    def upsert_machine(self, name: str, status: str, ip: str, os_name: str,
                       ram_gb: float, cpu_cores: int, models: list[str]) -> str:
        """Create or update machine record. Returns page_id."""
        existing = self._query(
            self.DB_MACHINES,
            filter_={"property": "name", "title": {"equals": name}}
        )
        props = {
            "name":          self._title(name),
            "status":        self._select(status),
            "ip":            self._text(ip),
            "os":            self._text(os_name),
            "ram_gb":        self._number(ram_gb),
            "cpu_cores":     self._number(cpu_cores),
            "ollama_models": self._multiselect(models),
            "last_seen":     self._date(),
        }
        if existing:
            page_id = existing[0]["id"]
            self._update(page_id, props)
            return page_id
        else:
            page = self._create(self.DB_MACHINES, props)
            return page["id"]

    def heartbeat(self, machine_name: str) -> None:
        """Update last_seen and status=online for this machine."""
        existing = self._query(
            self.DB_MACHINES,
            filter_={"property": "name", "title": {"equals": machine_name}}
        )
        if existing:
            self._update(existing[0]["id"], {
                "status":    self._select("online"),
                "last_seen": self._date(),
            })

    # ─── Agents ──────────────────────────────────────────────────────────────

    def get_agents(self, machine: Optional[str] = None,
                   status: Optional[str] = None) -> list[dict]:
        filters = []
        if machine:
            filters.append({"property": "machine", "rich_text": {"contains": machine}})
        if status:
            filters.append({"property": "status", "select": {"equals": status}})

        if len(filters) == 1:
            f = filters[0]
        elif len(filters) > 1:
            f = {"and": filters}
        else:
            f = None

        rows = self._query(self.DB_AGENTS, filter_=f)
        return [self._parse_agent(r) for r in rows]

    def _parse_agent(self, row: dict) -> dict:
        return {
            "id":              row["id"],
            "name":            self._read_title(row, "name"),
            "type":            self._read_select(row, "type"),
            "model":           self._read_text(row, "model"),
            "machine":         self._read_text(row, "machine"),
            "status":          self._read_select(row, "status"),
            "system_prompt":   self._read_text(row, "system_prompt"),
            "tasks_completed": self._read_number(row, "tasks_completed") or 0,
            "success_rate":    self._read_number(row, "success_rate") or 0,
        }

    def update_agent_status(self, agent_id: str, status: str) -> None:
        self._update(agent_id, {
            "status":      self._select(status),
            "last_active": self._date(),
        })

    def increment_agent_stats(self, agent_id: str, success: bool,
                              current_completed: int, current_rate: float) -> None:
        new_completed = int(current_completed) + 1
        # Rolling average success rate
        new_rate = ((current_rate * current_completed) + (1.0 if success else 0.0)) / new_completed
        self._update(agent_id, {
            "tasks_completed": self._number(new_completed),
            "success_rate":    self._number(new_rate),
        })

    # ─── Projects ────────────────────────────────────────────────────────────

    def get_projects(self, status: Optional[str] = None) -> list[dict]:
        f = None
        if status:
            f = {"property": "status", "select": {"equals": status}}
        rows = self._query(self.DB_PROJECTS, filter_=f)
        return [self._parse_project(r) for r in rows]

    def _parse_project(self, row: dict) -> dict:
        return {
            "id":              row["id"],
            "name":            self._read_title(row, "name"),
            "status":          self._read_select(row, "status"),
            "source":          self._read_select(row, "source"),
            "description":     self._read_text(row, "description"),
            "goal":            self._read_text(row, "goal"),
            "revenue_total":   self._read_number(row, "revenue_total") or 0.0,
            "revenue_30d":     self._read_number(row, "revenue_30d") or 0.0,
            "cost_total":      self._read_number(row, "cost_total") or 0.0,
            "viability_score": self._read_number(row, "viability_score"),
            "agent_lead":      self._read_text(row, "agent_lead"),
            "archived_reason": self._read_text(row, "archived_reason"),
            "created_at":      self._read_date(row, "created_at"),
            "last_activity":   self._read_date(row, "last_activity"),
        }

    def update_project_status(self, project_id: str, status: str,
                               reason: Optional[str] = None) -> None:
        props = {
            "status":        self._select(status),
            "last_activity": self._date(),
        }
        if reason:
            props["archived_reason"] = self._text(reason)
        self._update(project_id, props)

    def update_project_revenue(self, project_id: str, total: float,
                                revenue_30d: float) -> None:
        self._update(project_id, {
            "revenue_total": self._number(total),
            "revenue_30d":   self._number(revenue_30d),
        })

    def update_project_viability(self, project_id: str, score: float) -> None:
        self._update(project_id, {
            "viability_score": self._number(score),
            "last_activity":   self._date(),
        })

    # ─── Tasks ───────────────────────────────────────────────────────────────

    def get_tasks(self, status: Optional[str] = None,
                  agent: Optional[str] = None,
                  project: Optional[str] = None) -> list[dict]:
        filters = []
        if status:
            filters.append({"property": "status", "select": {"equals": status}})
        if agent:
            filters.append({"property": "agent", "rich_text": {"contains": agent}})
        if project:
            filters.append({"property": "project", "rich_text": {"contains": project}})

        if len(filters) == 1:
            f = filters[0]
        elif len(filters) > 1:
            f = {"and": filters}
        else:
            f = None

        rows = self._query(self.DB_TASKS, filter_=f,
                           sorts=[{"property": "created_at", "direction": "ascending"}])
        return [self._parse_task(r) for r in rows]

    def _parse_task(self, row: dict) -> dict:
        return {
            "id":             row["id"],
            "title":          self._read_title(row, "title"),
            "project":        self._read_text(row, "project"),
            "agent":          self._read_text(row, "agent"),
            "status":         self._read_select(row, "status"),
            "priority":       self._read_select(row, "priority"),
            "instructions":   self._read_text(row, "instructions"),
            "result":         self._read_text(row, "result"),
            "requires_human": self._read_checkbox(row, "requires_human"),
            "created_at":     self._read_date(row, "created_at"),
            "completed_at":   self._read_date(row, "completed_at"),
        }

    def create_task(self, title: str, project: str, instructions: str,
                    priority: str = "medium", agent: str = "",
                    requires_human: bool = False) -> str:
        page = self._create(self.DB_TASKS, {
            "title":          self._title(title),
            "project":        self._text(project),
            "agent":          self._text(agent),
            "status":         self._select("pending"),
            "priority":       self._select(priority),
            "instructions":   self._text(instructions),
            "requires_human": self._checkbox(requires_human),
            "created_at":     self._date(),
        })
        return page["id"]

    def update_task(self, task_id: str, status: str, result: str = "",
                    agent: str = "", tokens_used: int = 0,
                    cost_usd: float = 0.0) -> None:
        props: dict = {"status": self._select(status)}
        if result:
            props["result"] = self._text(result)
        if agent:
            props["agent"] = self._text(agent)
        if tokens_used:
            props["tokens_used"] = self._number(tokens_used)
        if cost_usd:
            props["cost_usd"] = self._number(cost_usd)
        if status in ("done", "failed"):
            props["completed_at"] = self._date()
        self._update(task_id, props)

    # ─── Revenue Log ─────────────────────────────────────────────────────────

    def log_revenue(self, project: str, amount: float, source: str,
                    currency: str = "USD", notes: str = "") -> str:
        page = self._create(self.DB_REVENUE_LOG, {
            "description": self._title(f"{source} - {project}"),
            "project":     self._text(project),
            "amount":      self._number(amount),
            "currency":    self._select(currency),
            "source":      self._select(source),
            "date":        self._date(),
            "notes":       self._text(notes),
        })
        return page["id"]

    def get_revenue_for_project(self, project_name: str,
                                 since_days: int = 30) -> float:
        """Sum revenue for a project in the last N days."""
        rows = self._query(
            self.DB_REVENUE_LOG,
            filter_={"property": "project", "rich_text": {"contains": project_name}},
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        total = 0.0
        for row in rows:
            date = self._read_date(row, "date")
            amount = self._read_number(row, "amount") or 0.0
            if date and date >= cutoff:
                total += amount
        return total

    # ─── Activity Log ────────────────────────────────────────────────────────

    def log_activity(self, agent: str, project: str, action: str,
                     result: str = "", model_used: str = "",
                     tokens_used: int = 0, cost_usd: float = 0.0) -> None:
        summary = f"{action}: {agent}"
        if project:
            summary += f" → {project}"
        self._create(self.DB_ACTIVITY_LOG, {
            "summary":     self._title(summary[:200]),
            "agent":       self._text(agent),
            "project":     self._text(project),
            "action":      self._select(action),
            "result":      self._text(result[:2000] if result else ""),
            "model_used":  self._text(model_used),
            "tokens_used": self._number(tokens_used),
            "cost_usd":    self._number(cost_usd),
            "timestamp":   self._date(),
        })
