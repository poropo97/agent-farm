#!/usr/bin/env bash
# scripts/register_machine.sh
# Register this machine in Notion Machines database.
# Called by init.sh and can be run standalone.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "📝 Registering machine in Notion..."

# Use venv python if available, else system python3
if [ -f "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

"$PYTHON" "$SCRIPT_DIR/register_machine.py"
