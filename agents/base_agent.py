"""
agents/base_agent.py

Base class for all Agent Farm agents.
Reads task from Notion, executes via LLM, writes result back.
"""

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Every agent:
    1. Receives a task dict from Notion (via orchestrator)
    2. Builds a prompt from task.instructions + agent system_prompt
    3. Calls the LLM
    4. Writes result back to Notion
    5. Logs activity
    """

    # Override in subclasses
    AGENT_TYPE: str = "base"
    DEFAULT_LLM_LEVEL: str = "medium"

    def __init__(self, notion_client, llm_client, agent_config: dict):
        """
        Args:
            notion_client: NotionFarmClient instance
            llm_client: LLMClient instance
            agent_config: Agent row from Notion {id, name, type, model, system_prompt, ...}
        """
        self.notion = notion_client
        self.llm = llm_client
        self.config = agent_config
        self.name = agent_config.get("name", self.AGENT_TYPE)
        self.agent_id = agent_config.get("id", "")
        self.system_prompt = agent_config.get("system_prompt", "") or self._default_system_prompt()

        # Model override from Notion config
        model_override = agent_config.get("model", "").strip()
        self.llm_level = model_override if model_override and model_override != "auto" \
                         else self.DEFAULT_LLM_LEVEL

    def _default_system_prompt(self) -> str:
        return (
            f"You are an AI agent of type '{self.AGENT_TYPE}' working in the Agent Farm system. "
            "Your goal is to help generate revenue through autonomous work. "
            "Be concise, practical, and output structured results. "
            "Always think about ROI and time-to-revenue."
        )

    def run(self, task: dict) -> dict:
        """
        Main entry point. Execute a task and return result dict.
        Returns: {success, result, tokens_used, cost_usd, error}
        """
        task_id = task["id"]
        task_title = task.get("title", "unknown")
        project = task.get("project", "")

        logger.info(f"[{self.name}] Starting task: {task_title}")

        # Mark task in_progress
        self.notion.update_task(task_id, "in_progress", agent=self.name)
        if self.agent_id:
            self.notion.update_agent_status(self.agent_id, "working")

        try:
            result = self._execute(task)

            # Write result back to Notion
            self.notion.update_task(
                task_id,
                status="done",
                result=result["result"],
                agent=self.name,
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
            )

            # Log activity
            self.notion.log_activity(
                agent=self.name,
                project=project,
                action="task_completed",
                result=result["result"][:500],
                model_used=result.get("model_used", ""),
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
            )

            # Update agent stats
            if self.agent_id:
                self.notion.increment_agent_stats(
                    self.agent_id,
                    success=True,
                    current_completed=int(self.config.get("tasks_completed", 0)),
                    current_rate=float(self.config.get("success_rate", 0)),
                )
                self.notion.update_agent_status(self.agent_id, "idle")

            logger.info(f"[{self.name}] Task completed: {task_title}")
            return {**result, "success": True}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{self.name}] Task failed: {task_title} — {error_msg}")

            self.notion.update_task(
                task_id,
                status="failed",
                result=f"Error: {error_msg}",
                agent=self.name,
            )
            self.notion.log_activity(
                agent=self.name,
                project=project,
                action="task_failed",
                result=error_msg[:500],
            )

            if self.agent_id:
                self.notion.increment_agent_stats(
                    self.agent_id,
                    success=False,
                    current_completed=int(self.config.get("tasks_completed", 0)),
                    current_rate=float(self.config.get("success_rate", 0)),
                )
                self.notion.update_agent_status(self.agent_id, "error")

            return {"success": False, "error": error_msg, "result": "", "tokens_used": 0, "cost_usd": 0.0}

    @abstractmethod
    def _execute(self, task: dict) -> dict:
        """
        Subclasses implement this.
        Returns: {result: str, tokens_used: int, cost_usd: float, model_used: str}
        """

    def _call_llm(self, prompt: str, system_prompt: Optional[str] = None,
                  max_tokens: int = 2048, level: Optional[str] = None) -> dict:
        """Helper: call LLM and return standardized response dict."""
        response = self.llm.complete(
            prompt=prompt,
            level=level or self.llm_level,
            system_prompt=system_prompt or self.system_prompt,
            max_tokens=max_tokens,
        )
        return {
            "result":      response.content,
            "tokens_used": response.tokens_used,
            "cost_usd":    response.cost_usd,
            "model_used":  f"{response.provider}/{response.model}",
        }
