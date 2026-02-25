"""
Notion database schemas for Agent Farm.
Each schema defines properties for one of the 7 core databases.
"""

# ─── 1. System Config ───────────────────────────────────────────────────────
SYSTEM_CONFIG_SCHEMA = {
    "name": "⚙️ System Config",
    "properties": {
        "key": {"title": {}},
        "value": {"rich_text": {}},
        "description": {"rich_text": {}},
    },
}

# Default system config rows inserted on first setup
SYSTEM_CONFIG_DEFAULTS = [
    {"key": "autonomy_level",           "value": "7",   "description": "0=todo requiere humano, 10=máxima autonomía"},
    {"key": "max_concurrent_agents",    "value": "3",   "description": "Máx agentes corriendo en paralelo por máquina"},
    {"key": "default_model",            "value": "auto","description": "Modelo por defecto: auto, ollama, groq, claude"},
    {"key": "loop_interval_seconds",    "value": "300", "description": "Frecuencia del loop del orquestador en segundos"},
    {"key": "scale_threshold_usd",      "value": "10",  "description": "Revenue mínimo en 30d (USD) para escalar proyecto"},
    {"key": "archive_days_no_revenue",  "value": "21",  "description": "Días sin ingresos antes de archivar proyecto"},
    {"key": "max_cost_per_project_usd", "value": "5",   "description": "Límite de gasto en tokens por proyecto inactivo"},
    {"key": "parallel_projects_max",    "value": "10",  "description": "Máx proyectos activos simultáneos"},
    {"key": "new_ideas_per_week",       "value": "3",   "description": "Ideas auto-generadas semanalmente"},
    {"key": "monthly_budget_usd",       "value": "20",  "description": "Presupuesto mensual máximo en APIs cloud"},
    {"key": "viability_threshold",      "value": "60",  "description": "Puntuación mínima (0-100) para activar un proyecto"},
    {"key": "self_update_enabled",      "value": "true","description": "¿El orquestador se auto-actualiza desde git?"},
    {"key": "research_model",           "value": "auto","description": "Modelo para research_agent"},
    {"key": "code_model",               "value": "auto","description": "Modelo para code_agent"},
    {"key": "content_model",            "value": "auto","description": "Modelo para content_agent"},
]

# ─── 2. Machines ─────────────────────────────────────────────────────────────
MACHINES_SCHEMA = {
    "name": "🖥️ Machines",
    "properties": {
        "name": {"title": {}},
        "status": {
            "select": {
                "options": [
                    {"name": "online",  "color": "green"},
                    {"name": "offline", "color": "red"},
                    {"name": "idle",    "color": "yellow"},
                ]
            }
        },
        "ip": {"rich_text": {}},
        "os": {"rich_text": {}},
        "ram_gb": {"number": {"format": "number"}},
        "cpu_cores": {"number": {"format": "number"}},
        "ollama_models": {"multi_select": {"options": [
            {"name": "llama3.2:3b",  "color": "blue"},
            {"name": "mistral:7b",   "color": "purple"},
            {"name": "llama3.1:8b",  "color": "pink"},
            {"name": "llama3.1:70b", "color": "red"},
        ]}},
        "last_seen": {"date": {}},
        "notes": {"rich_text": {}},
    },
}

# ─── 3. Agents ───────────────────────────────────────────────────────────────
AGENTS_SCHEMA = {
    "name": "🧠 Agents",
    "properties": {
        "name": {"title": {}},
        "type": {
            "select": {
                "options": [
                    {"name": "research", "color": "blue"},
                    {"name": "code",     "color": "green"},
                    {"name": "content",  "color": "yellow"},
                    {"name": "trading",  "color": "orange"},
                    {"name": "custom",   "color": "gray"},
                ]
            }
        },
        "model": {"rich_text": {}},
        "machine": {"rich_text": {}},
        "status": {
            "select": {
                "options": [
                    {"name": "idle",        "color": "gray"},
                    {"name": "working",     "color": "blue"},
                    {"name": "completed",   "color": "green"},
                    {"name": "error",       "color": "red"},
                    {"name": "disabled",    "color": "default"},
                ]
            }
        },
        "system_prompt": {"rich_text": {}},
        "tasks_completed": {"number": {"format": "number"}},
        "success_rate": {"number": {"format": "percent"}},
        "last_active": {"date": {}},
    },
}

# ─── 4. Projects ─────────────────────────────────────────────────────────────
PROJECTS_SCHEMA = {
    "name": "💡 Projects",
    "properties": {
        "name": {"title": {}},
        "status": {
            "select": {
                "options": [
                    {"name": "idea",     "color": "gray"},
                    {"name": "research", "color": "blue"},
                    {"name": "active",   "color": "green"},
                    {"name": "paused",   "color": "yellow"},
                    {"name": "scaling",  "color": "purple"},
                    {"name": "archived", "color": "red"},
                ]
            }
        },
        "source": {
            "select": {
                "options": [
                    {"name": "human_idea",      "color": "blue"},
                    {"name": "auto_generated",  "color": "green"},
                ]
            }
        },
        "description": {"rich_text": {}},
        "goal": {"rich_text": {}},
        "revenue_total": {"number": {"format": "dollar"}},
        "revenue_30d": {"number": {"format": "dollar"}},
        "cost_total": {"number": {"format": "dollar"}},
        "viability_score": {"number": {"format": "number"}},
        "agent_lead": {"rich_text": {}},
        "archived_reason": {"rich_text": {}},
        "created_at": {"date": {}},
        "last_activity": {"date": {}},
    },
}

# ─── 5. Tasks ────────────────────────────────────────────────────────────────
TASKS_SCHEMA = {
    "name": "✅ Tasks",
    "properties": {
        "title": {"title": {}},
        "project": {"rich_text": {}},
        "agent": {"rich_text": {}},
        "status": {
            "select": {
                "options": [
                    {"name": "pending",       "color": "gray"},
                    {"name": "in_progress",   "color": "blue"},
                    {"name": "done",          "color": "green"},
                    {"name": "failed",        "color": "red"},
                    {"name": "needs_human",   "color": "orange"},
                ]
            }
        },
        "priority": {
            "select": {
                "options": [
                    {"name": "low",    "color": "gray"},
                    {"name": "medium", "color": "yellow"},
                    {"name": "high",   "color": "orange"},
                    {"name": "urgent", "color": "red"},
                ]
            }
        },
        "instructions": {"rich_text": {}},
        "result": {"rich_text": {}},
        "requires_human": {"checkbox": {}},
        "created_at": {"date": {}},
        "completed_at": {"date": {}},
        "tokens_used": {"number": {"format": "number"}},
        "cost_usd": {"number": {"format": "dollar"}},
    },
}

# ─── 6. Revenue Log ──────────────────────────────────────────────────────────
REVENUE_LOG_SCHEMA = {
    "name": "💰 Revenue Log",
    "properties": {
        "description": {"title": {}},
        "project": {"rich_text": {}},
        "amount": {"number": {"format": "dollar"}},
        "currency": {
            "select": {
                "options": [
                    {"name": "USD", "color": "green"},
                    {"name": "EUR", "color": "blue"},
                    {"name": "BTC", "color": "orange"},
                ]
            }
        },
        "source": {
            "select": {
                "options": [
                    {"name": "stripe",    "color": "purple"},
                    {"name": "affiliate", "color": "blue"},
                    {"name": "manual",    "color": "gray"},
                    {"name": "api",       "color": "green"},
                    {"name": "other",     "color": "default"},
                ]
            }
        },
        "date": {"date": {}},
        "notes": {"rich_text": {}},
    },
}

# ─── 7. Activity Log ─────────────────────────────────────────────────────────
ACTIVITY_LOG_SCHEMA = {
    "name": "📋 Activity Log",
    "properties": {
        "summary": {"title": {}},
        "agent": {"rich_text": {}},
        "project": {"rich_text": {}},
        "action": {
            "select": {
                "options": [
                    {"name": "task_started",    "color": "blue"},
                    {"name": "task_completed",  "color": "green"},
                    {"name": "task_failed",     "color": "red"},
                    {"name": "project_created", "color": "purple"},
                    {"name": "project_scaled",  "color": "pink"},
                    {"name": "project_archived","color": "gray"},
                    {"name": "self_update",     "color": "orange"},
                    {"name": "heartbeat",       "color": "default"},
                    {"name": "error",           "color": "red"},
                ]
            }
        },
        "result": {"rich_text": {}},
        "model_used": {"rich_text": {}},
        "tokens_used": {"number": {"format": "number"}},
        "cost_usd": {"number": {"format": "dollar"}},
        "timestamp": {"date": {}},
    },
}

# All schemas in order
ALL_SCHEMAS = [
    SYSTEM_CONFIG_SCHEMA,
    MACHINES_SCHEMA,
    AGENTS_SCHEMA,
    PROJECTS_SCHEMA,
    TASKS_SCHEMA,
    REVENUE_LOG_SCHEMA,
    ACTIVITY_LOG_SCHEMA,
]
