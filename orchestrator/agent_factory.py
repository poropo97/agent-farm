"""
orchestrator/agent_factory.py

Instantiates the correct agent class based on Notion agent config.
"""

import logging
from typing import Optional

from agents.base_agent import BaseAgent
from agents.research_agent import ResearchAgent
from agents.code_agent import CodeAgent
from agents.content_agent import ContentAgent
from agents.trading_agent import TradingAgent

logger = logging.getLogger(__name__)

AGENT_CLASS_MAP = {
    "research": ResearchAgent,
    "code":     CodeAgent,
    "content":  ContentAgent,
    "trading":  TradingAgent,
}


def create_agent(agent_config: dict, notion_client, llm_client) -> Optional[BaseAgent]:
    """
    Instantiate an agent from its Notion config dict.

    Args:
        agent_config: dict from NotionFarmClient.get_agents()
        notion_client: NotionFarmClient instance
        llm_client: LLMClient instance

    Returns:
        BaseAgent subclass instance, or None if type unknown
    """
    agent_type = (agent_config.get("type") or "").lower()
    klass = AGENT_CLASS_MAP.get(agent_type)

    if not klass:
        logger.warning(f"Unknown agent type '{agent_type}' for agent '{agent_config.get('name')}'")
        return None

    return klass(notion_client, llm_client, agent_config)


def get_agent_for_task(task: dict, available_agents: list[dict],
                       notion_client, llm_client) -> Optional[BaseAgent]:
    """
    Match a task to the best available agent.

    Priority:
    1. Agent explicitly named in task.agent field
    2. Agent by type matching task keywords
    3. Any idle agent
    """
    # 1. Explicit agent assignment
    assigned_agent_name = (task.get("agent") or "").strip()
    if assigned_agent_name:
        agent_config = next(
            (a for a in available_agents if a["name"] == assigned_agent_name
             and a.get("status") != "working"),
            None
        )
        if agent_config:
            return create_agent(agent_config, notion_client, llm_client)

    # 2. Match by task content
    instructions = (task.get("instructions") or "").upper()
    title = (task.get("title") or "").upper()
    combined = instructions + " " + title

    preferred_type = _infer_agent_type(combined)

    idle_agents = [a for a in available_agents if a.get("status") in ("idle", None, "")]
    if preferred_type:
        typed_agents = [a for a in idle_agents if a.get("type") == preferred_type]
        if typed_agents:
            return create_agent(typed_agents[0], notion_client, llm_client)

    # 3. Any idle agent
    if idle_agents:
        return create_agent(idle_agents[0], notion_client, llm_client)

    logger.warning("No available agent found for task")
    return None


def _infer_agent_type(text: str) -> str:
    """Infer agent type from task text."""
    keywords = {
        "research":  ["RESEARCH", "VIABILITY", "ANALYZE", "MARKET", "OPPORTUNITY", "GENERATE_IDEAS"],
        "code":      ["CODE", "WRITE_CODE", "CREATE_API", "LANDING", "SCRIPT", "DEPLOY", "BUILD"],
        "content":   ["CONTENT", "ARTICLE", "BLOG", "SEO", "EMAIL", "SOCIAL", "COPY", "WRITE"],
        "trading":   ["TRADING", "CRYPTO", "MARKET", "ARBITRAGE", "BACKTEST", "FINANCIAL"],
    }
    for agent_type, kws in keywords.items():
        if any(kw in text for kw in kws):
            return agent_type
    return "research"  # default
