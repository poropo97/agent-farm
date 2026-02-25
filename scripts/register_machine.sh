#!/usr/bin/env bash
# scripts/register_machine.sh
# Register this machine in Notion Machines database.
# Called by init.sh and can be run standalone.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$REPO_ROOT/.env" 2>/dev/null || true

echo "📝 Registering machine in Notion..."

python3 - <<'EOF'
import os, sys, socket, platform
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

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
        except:
            return "127.0.0.1"

    def get_ollama_models():
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=3)
            return [m["name"] for m in r.json().get("models", [])]
        except:
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
EOF
