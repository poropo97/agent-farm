"""
scripts/register_machine.py
Register this machine in the Notion Machines database.
"""
import os
import sys
import socket
import platform

# Repo root = parent of scripts/
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(REPO_ROOT, ".env"))

try:
    import psutil
    from orchestrator.notion_client import NotionFarmClient

    machine_name = os.environ.get("MACHINE_NAME", "").strip() or socket.gethostname()
    vm = psutil.virtual_memory()
    ram_gb = round(vm.total / (1024 ** 3), 1)
    cpu_cores = psutil.cpu_count(logical=False) or 1

    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def get_ollama_models():
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=3)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    notion = NotionFarmClient()
    page_id = notion.upsert_machine(
        name=machine_name,
        status="online",
        ip=get_local_ip(),
        os_name=f"{platform.system()} {platform.release()}",
        ram_gb=ram_gb,
        cpu_cores=cpu_cores,
        models=get_ollama_models(),
    )
    print(f"✅ Machine '{machine_name}' registered in Notion (page: {page_id})")

except KeyError as e:
    print(f"❌ Database not found: {e}")
    print("   Run: python notion_setup/setup.py first")
    sys.exit(1)
except Exception as e:
    print(f"❌ Registration failed: {e}")
    sys.exit(1)
