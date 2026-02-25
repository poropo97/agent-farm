"""
deploy/self_update.py

Checks for new commits in origin/main and self-updates the service.
Called by the orchestrator hourly.
"""

import logging
import os
import subprocess
import sys
import platform

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def check_and_update(machine_name: str, notion_client=None) -> bool:
    """
    Check for new commits and update if available.
    Returns True if an update was applied.
    """
    try:
        # Fetch remote without merging
        _git(["fetch", "origin", "main"])

        # Compare local HEAD with remote
        local  = _git(["rev-parse", "HEAD"]).stdout.strip()
        remote = _git(["rev-parse", "origin/main"]).stdout.strip()

        if local == remote:
            logger.debug("Self-update: already up to date")
            return False

        # Check if critical tasks are in progress
        if notion_client:
            try:
                in_progress = notion_client.get_tasks(status="in_progress")
                if len(in_progress) > 0:
                    logger.info(
                        f"Self-update skipped: {len(in_progress)} tasks in progress"
                    )
                    return False
            except Exception:
                pass

        logger.info(f"Self-update: new commits found ({local[:7]} → {remote[:7]})")

        # Get commit log
        log = _git(["log", "--oneline", f"{local}..origin/main"]).stdout.strip()
        logger.info(f"New commits:\n{log}")

        # Pull changes
        _git(["pull", "origin", "main"])
        logger.info("Self-update: git pull completed")

        # Update dependencies
        pip = sys.executable.replace("python", "pip") if "python" in sys.executable else "pip"
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r",
             os.path.join(REPO_ROOT, "requirements.txt"), "-q"],
            check=True,
        )
        logger.info("Self-update: dependencies updated")

        # Log to Notion
        if notion_client:
            try:
                notion_client.log_activity(
                    agent="orchestrator",
                    project="",
                    action="self_update",
                    result=f"Updated {local[:7]} → {remote[:7]}\n{log}",
                )
            except Exception:
                pass

        # Restart service
        _restart_service()
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"Self-update git error: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Self-update failed: {e}")
        return False


def _restart_service() -> None:
    """Restart the orchestrator service (systemd / launchd / direct)."""
    system = platform.system()

    if system == "Linux":
        # Try systemd
        result = subprocess.run(
            ["systemctl", "is-active", "agent-farm"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info("Restarting via systemd: agent-farm")
            subprocess.run(["sudo", "systemctl", "restart", "agent-farm"], check=False)
            return

    elif system == "Darwin":
        # Try launchd
        plist_label = "com.agentfarm.orchestrator"
        result = subprocess.run(
            ["launchctl", "list", plist_label],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            logger.info(f"Restarting via launchd: {plist_label}")
            subprocess.run(["launchctl", "stop", plist_label], check=False)
            subprocess.run(["launchctl", "start", plist_label], check=False)
            return

    # Fallback: restart by re-executing this Python process
    logger.info("Restarting orchestrator process directly")
    os.execv(sys.executable, [sys.executable] + sys.argv)
