#!/usr/bin/env bash
# scripts/start.sh
# Start the Agent Farm orchestrator.
# Used by systemd/launchd service or manual startup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

# Load .env if present
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs) 2>/dev/null || true
fi

# Activate virtualenv if it exists
if [ -d ".venv/bin" ]; then
    source .venv/bin/activate
elif [ -d "venv/bin" ]; then
    source venv/bin/activate
fi

echo "🤖 Starting Agent Farm Orchestrator..."
echo "   Machine: $(hostname)"
echo "   Python:  $(python3 --version)"
echo "   Time:    $(date)"

exec python3 orchestrator/main.py
