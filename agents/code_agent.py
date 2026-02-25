"""
agents/code_agent.py

Writes, reviews, and deploys code for Agent Farm projects.
Specializes in micro-SaaS, landing pages, APIs, automation scripts.
"""

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

CODE_SYSTEM_PROMPT = """You are an expert software engineer working for an autonomous AI agent farm.
Your goal is to write clean, production-ready code that generates revenue.

Specialties:
- Python backends (FastAPI, Flask)
- Landing pages (HTML/CSS/JS, Tailwind)
- Stripe payment integration
- REST APIs
- Web scraping and data pipelines
- Automation scripts

Always:
- Write complete, runnable code (not snippets)
- Include error handling
- Comment key decisions
- Prioritize simplicity and speed to deploy
- Output code in markdown code blocks with language tags"""


class CodeAgent(BaseAgent):
    AGENT_TYPE = "code"
    DEFAULT_LLM_LEVEL = "medium"

    def _default_system_prompt(self) -> str:
        return CODE_SYSTEM_PROMPT

    def _execute(self, task: dict) -> dict:
        instructions = task.get("instructions", "")
        instructions_upper = instructions.upper()

        if "WRITE_CODE" in instructions_upper or "CREATE_FILE" in instructions_upper:
            return self._write_code(task)
        elif "REVIEW_CODE" in instructions_upper:
            return self._review_code(task)
        elif "CREATE_LANDING" in instructions_upper:
            return self._create_landing_page(task)
        elif "CREATE_API" in instructions_upper:
            return self._create_api(task)
        else:
            return self._general_code_task(task)

    def _write_code(self, task: dict) -> dict:
        """Write code based on specifications."""
        prompt = f"""Write the following code:

{task.get('instructions', '')}

Requirements:
- Production ready, no placeholders
- Include all imports
- Handle errors gracefully
- Add brief inline comments for non-obvious logic

Output each file as a markdown code block with the filename as a comment at the top:
```python
# filename: main.py
...code...
```"""
        response = self._call_llm(prompt, max_tokens=4096, level="medium")

        # Extract and save files if output path specified
        output = self._extract_and_save_files(response["result"], task)
        response["result"] = output or response["result"]
        return response

    def _review_code(self, task: dict) -> dict:
        """Review code for bugs, security issues, and improvements."""
        prompt = f"""Review the following code and provide:
1. Security issues (critical → nice-to-have)
2. Bugs or logic errors
3. Performance improvements
4. Code quality suggestions

Be concise. Format as numbered lists.

Code to review:
{task.get('instructions', '')}"""
        return self._call_llm(prompt, max_tokens=2000, level="medium")

    def _create_landing_page(self, task: dict) -> dict:
        """Generate a complete HTML landing page."""
        prompt = f"""Create a complete, modern landing page HTML file.

Requirements:
{task.get('instructions', '')}

Use:
- Tailwind CSS (CDN)
- Clean, conversion-optimized layout
- Hero section, features, CTA, footer
- Mobile responsive
- Stripe checkout button (placeholder with TODO comment)
- No external images (use CSS gradients/shapes)

Output as single HTML file in a code block."""
        return self._call_llm(prompt, max_tokens=4096, level="medium")

    def _create_api(self, task: dict) -> dict:
        """Generate a FastAPI/Flask REST API."""
        prompt = f"""Create a complete FastAPI REST API.

Specifications:
{task.get('instructions', '')}

Include:
- All route handlers with proper HTTP methods
- Pydantic models for request/response
- Basic auth or API key middleware if needed
- Health check endpoint
- requirements.txt
- Brief README with usage examples

Output each file in separate code blocks."""
        return self._call_llm(prompt, max_tokens=4096, level="medium")

    def _general_code_task(self, task: dict) -> dict:
        """Handle general coding tasks."""
        return self._call_llm(
            task.get("instructions", ""),
            max_tokens=4096,
            level="medium",
        )

    def _extract_and_save_files(self, llm_output: str, task: dict) -> str:
        """Extract code blocks and save to project directory if path is specified."""
        project = task.get("project", "").replace(" ", "_").lower()
        if not project:
            return ""

        # Look for project output directory
        output_dir = Path(os.environ.get("PROJECTS_DIR", "/tmp/agent-farm-projects")) / project
        output_dir.mkdir(parents=True, exist_ok=True)

        # Find all code blocks with filename comments
        pattern = r"```(\w+)?\n#\s*filename:\s*(.+?)\n([\s\S]*?)```"
        matches = re.findall(pattern, llm_output, re.IGNORECASE)

        if not matches:
            return ""

        saved = []
        for lang, filename, code in matches:
            filename = filename.strip()
            filepath = output_dir / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(code.strip())
            saved.append(str(filepath))
            logger.info(f"[{self.name}] Saved: {filepath}")

        if saved:
            return f"Saved {len(saved)} files to {output_dir}:\n" + "\n".join(
                f"  - {Path(p).name}" for p in saved
            ) + f"\n\n--- LLM Output ---\n{llm_output}"
        return ""
