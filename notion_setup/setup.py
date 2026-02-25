"""
notion_setup/setup.py

Idempotently creates all 7 Agent Farm databases in Notion.
Run this once on a new workspace, or re-run safely — it won't duplicate.

Usage:
    python notion_setup/setup.py
"""

import os
import sys
import json
from datetime import datetime, timezone

from dotenv import load_dotenv
from notion_client import Client
from rich.console import Console
from rich.table import Table

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notion_setup.schemas import (
    ALL_SCHEMAS,
    SYSTEM_CONFIG_SCHEMA,
    SYSTEM_CONFIG_DEFAULTS,
)

load_dotenv()
console = Console()


def get_notion_client() -> Client:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        console.print("[red]Error: NOTION_TOKEN not set in .env[/red]")
        sys.exit(1)
    return Client(auth=token)


def get_parent_page_id(notion: Client) -> str:
    """
    Looks for a page named 'Agent Farm' in the workspace.
    If not found, creates it at the top level (requires integration to have access).
    Returns page_id.
    """
    results = notion.search(query="Agent Farm", filter={"property": "object", "value": "page"}).get("results", [])
    for r in results:
        if r["object"] == "page":
            title_parts = r.get("properties", {}).get("title", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            if title == "Agent Farm":
                console.print(f"[green]Found existing 'Agent Farm' page: {r['id']}[/green]")
                return r["id"]

    # Create the parent page
    console.print("[yellow]Creating 'Agent Farm' parent page...[/yellow]")
    new_page = notion.pages.create(
        parent={"type": "workspace", "workspace": True},
        properties={"title": {"title": [{"text": {"content": "Agent Farm"}}]}},
        icon={"type": "emoji", "emoji": "🤖"},
    )
    console.print(f"[green]Created 'Agent Farm' page: {new_page['id']}[/green]")
    return new_page["id"]


def list_existing_databases(notion: Client, parent_id: str) -> dict:
    """Returns {db_name: db_id} for all databases under parent_id."""
    existing = {}
    results = notion.search(filter={"property": "object", "value": "database"}).get("results", [])
    for db in results:
        title_parts = db.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts)
        # Check if this DB is under our parent page
        parent = db.get("parent", {})
        if parent.get("type") == "page_id" and parent.get("page_id") == parent_id:
            existing[title] = db["id"]
    return existing


def create_database(notion: Client, parent_id: str, schema: dict) -> str:
    """Creates a Notion database from schema dict. Returns db_id."""
    db = notion.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": schema["name"]}}],
        properties=schema["properties"],
    )
    return db["id"]


def seed_system_config(notion: Client, db_id: str) -> None:
    """Insert default System Config rows if the database is empty."""
    existing = notion.databases.query(database_id=db_id).get("results", [])
    if existing:
        console.print("[dim]System Config already has rows, skipping seed.[/dim]")
        return

    console.print("[cyan]Seeding System Config defaults...[/cyan]")
    for row in SYSTEM_CONFIG_DEFAULTS:
        notion.pages.create(
            parent={"database_id": db_id},
            properties={
                "key":         {"title":      [{"text": {"content": row["key"]}}]},
                "value":       {"rich_text":  [{"text": {"content": row["value"]}}]},
                "description": {"rich_text":  [{"text": {"content": row["description"]}}]},
            },
        )
    console.print(f"[green]Seeded {len(SYSTEM_CONFIG_DEFAULTS)} config rows.[/green]")


def save_db_ids(db_map: dict) -> None:
    """Save database IDs to a local JSON file for quick access."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_ids.json")
    with open(path, "w") as f:
        json.dump(db_map, f, indent=2)
    console.print(f"[green]Database IDs saved to {path}[/green]")


def main():
    console.rule("[bold blue]Agent Farm - Notion Setup[/bold blue]")
    notion = get_notion_client()

    # Get or create parent page
    parent_id = get_parent_page_id(notion)

    # List existing DBs
    existing = list_existing_databases(notion, parent_id)
    console.print(f"[dim]Found {len(existing)} existing database(s) under Agent Farm page.[/dim]")

    db_map = {}
    table = Table(title="Database Status", show_header=True, header_style="bold magenta")
    table.add_column("Database", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("ID")

    for schema in ALL_SCHEMAS:
        name = schema["name"]
        if name in existing:
            db_id = existing[name]
            table.add_row(name, "EXISTS", db_id)
        else:
            db_id = create_database(notion, parent_id, schema)
            table.add_row(name, "CREATED", db_id)
            console.print(f"[green]Created: {name}[/green]")

        db_map[name] = db_id

        # Seed System Config if it was just created or is empty
        if name == SYSTEM_CONFIG_SCHEMA["name"]:
            seed_system_config(notion, db_id)

    console.print(table)

    # Persist IDs for orchestrator to use
    save_db_ids(db_map)

    console.rule("[bold green]Setup Complete[/bold green]")
    console.print(
        "\n[bold]Next steps:[/bold]\n"
        "1. Open Notion and verify the 7 databases are visible under 'Agent Farm'\n"
        "2. Run: [cyan]python scripts/register_machine.sh[/cyan]\n"
        "3. Run: [cyan]python orchestrator/main.py[/cyan]\n"
    )


if __name__ == "__main__":
    main()
