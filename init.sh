#!/usr/bin/env bash
# init.sh — Agent Farm Bootstrap
# Run this once on any new machine after cloning the repo.
#
# What it does:
#   1. Detects OS (Linux/macOS)
#   2. Verifies Python 3.10+
#   3. Creates virtualenv and installs requirements
#   4. Installs Ollama (if missing)
#   5. Detects RAM and pulls best local model
#   6. Runs notion_setup/setup.py (idempotent: creates 7 DBs)
#   7. Registers this machine in Notion
#   8. Installs systemd (Linux) or launchd (macOS) service
#   9. Starts the orchestrator

set -euo pipefail

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${BLUE}→${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }
step() { echo -e "\n${BOLD}${BLUE}[$1]${NC} $2"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo ""
echo -e "${BOLD}${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║     🤖  Agent Farm  Bootstrap        ║${NC}"
echo -e "${BOLD}${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ─── Step 1: Detect OS ────────────────────────────────────────────────────────
step "1/9" "Detecting OS"
OS="$(uname -s)"
case "$OS" in
    Linux*)  OS_NAME="Linux" ;;
    Darwin*) OS_NAME="macOS" ;;
    *)
        err "Unsupported OS: $OS. Only Linux and macOS are supported."
        exit 1
        ;;
esac
log "OS: $OS_NAME"

# Detect RAM
if [ "$OS_NAME" = "Linux" ]; then
    RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    RAM_GB=$((RAM_KB / 1024 / 1024))
else
    RAM_BYTES=$(sysctl -n hw.memsize)
    RAM_GB=$((RAM_BYTES / 1024 / 1024 / 1024))
fi
log "RAM: ${RAM_GB}GB detected"

# ─── Step 2: Check Python 3.10+ ───────────────────────────────────────────────
step "2/9" "Checking Python"
PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    err "Python 3.10+ not found."
    if [ "$OS_NAME" = "Linux" ]; then
        info "Install with: sudo apt install python3.11 python3.11-venv"
    else
        info "Install with: brew install python@3.11"
    fi
    exit 1
fi
log "Python: $($PY --version)"

# ─── Step 3: Virtualenv + requirements ────────────────────────────────────────
step "3/9" "Setting up virtualenv and installing dependencies"
if [ ! -d ".venv" ]; then
    info "Creating virtualenv..."
    "$PY" -m venv .venv
fi
source .venv/bin/activate
log "Virtualenv activated: $(python --version)"

info "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
log "Dependencies installed"

# ─── Step 4: Check .env ───────────────────────────────────────────────────────
step "4/9" "Checking environment configuration"
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from template. Please edit it and re-run init.sh."
    warn "Required: NOTION_TOKEN"
    warn "Optional: ANTHROPIC_API_KEY, GROQ_API_KEY"
    echo ""
    echo -e "${YELLOW}Open .env and fill in your tokens, then re-run:${NC}"
    echo -e "  ${BOLD}nano .env${NC}"
    echo -e "  ${BOLD}bash init.sh${NC}"
    exit 0
fi

# Validate NOTION_TOKEN
source .env
if [ -z "${NOTION_TOKEN:-}" ] || [ "${NOTION_TOKEN}" = "secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]; then
    err "NOTION_TOKEN not set in .env"
    err "Get yours at: https://www.notion.so/my-integrations"
    exit 1
fi
log ".env configured"

# ─── Step 5: Install Ollama ───────────────────────────────────────────────────
step "5/9" "Installing Ollama"
if command -v ollama &>/dev/null; then
    log "Ollama already installed: $(ollama --version 2>/dev/null || echo 'ok')"
else
    info "Installing Ollama..."
    if [ "$OS_NAME" = "Linux" ]; then
        curl -fsSL https://ollama.com/install.sh | sh
    else
        warn "On macOS, install Ollama manually from: https://ollama.com/download"
        warn "Then re-run init.sh"
    fi
fi

# Ensure Ollama is running
if [ "$OS_NAME" = "Linux" ]; then
    if ! systemctl is-active --quiet ollama 2>/dev/null; then
        info "Starting Ollama service..."
        sudo systemctl start ollama 2>/dev/null || ollama serve &>/dev/null &
        sleep 3
    fi
fi

# ─── Step 6: Pull appropriate Ollama model ────────────────────────────────────
step "6/9" "Pulling local AI model (based on ${RAM_GB}GB RAM)"
if [ "$RAM_GB" -lt 8 ]; then
    MODEL="llama3.2:3b"
    info "Low RAM (<8GB): pulling $MODEL (2GB download)"
elif [ "$RAM_GB" -lt 16 ]; then
    MODEL="mistral:7b"
    info "Medium RAM (<16GB): pulling $MODEL (4GB download)"
else
    MODEL="llama3.1:8b"
    info "High RAM (≥16GB): pulling $MODEL (5GB download)"
fi

if ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
    log "Model already downloaded: $MODEL"
else
    info "Pulling $MODEL (this may take a few minutes)..."
    ollama pull "$MODEL" || warn "Model pull failed — you can retry with: ollama pull $MODEL"
fi

# ─── Step 7: Notion setup (7 databases) ──────────────────────────────────────
step "7/9" "Setting up Notion databases"
python notion_setup/setup.py
log "Notion databases ready"

# ─── Step 8: Register machine ─────────────────────────────────────────────────
step "8/9" "Registering this machine in Notion"
bash scripts/register_machine.sh
log "Machine registered"

# ─── Service install functions ────────────────────────────────────────────────
function _install_systemd() {
    SERVICE_FILE="/etc/systemd/system/agent-farm.service"
    VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Agent Farm Orchestrator
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_ROOT
EnvironmentFile=$REPO_ROOT/.env
ExecStart=$VENV_PYTHON -m orchestrator.main
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable agent-farm
    sudo systemctl start agent-farm
    log "systemd service installed and started: agent-farm"
    info "Check status: sudo systemctl status agent-farm"
    info "View logs:    journalctl -u agent-farm -f"
}

function _install_launchd() {
    PLIST_LABEL="com.agentfarm.orchestrator"
    PLIST_FILE="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
    VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_PYTHON}</string>
        <string>${REPO_ROOT}/orchestrator/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NOTION_TOKEN</key>
        <string>${NOTION_TOKEN}</string>
        <key>ANTHROPIC_API_KEY</key>
        <string>${ANTHROPIC_API_KEY:-}</string>
        <key>GROQ_API_KEY</key>
        <string>${GROQ_API_KEY:-}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${REPO_ROOT}/logs/orchestrator.log</string>
    <key>StandardErrorPath</key>
    <string>${REPO_ROOT}/logs/orchestrator.error.log</string>
</dict>
</plist>
EOF

    mkdir -p "$REPO_ROOT/logs"
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    launchctl load -w "$PLIST_FILE"
    log "launchd service installed: $PLIST_LABEL"
    info "Check status: launchctl list | grep agentfarm"
    info "View logs:    tail -f $REPO_ROOT/logs/orchestrator.log"
}

# ─── Step 9: Install service ──────────────────────────────────────────────────
step "9/9" "Installing system service for auto-start"
if [ "$OS_NAME" = "Linux" ]; then
    _install_systemd
elif [ "$OS_NAME" = "macOS" ]; then
    _install_launchd
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║   ✅  Agent Farm is up and running!      ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Notion HQ:${NC} Open Notion → Agent Farm page"
echo -e "  ${BOLD}Add idea:${NC}  Create row in 💡 Projects with status=idea"
echo -e "  ${BOLD}Logs:${NC}      journalctl -u agent-farm -f   (Linux)"
echo ""
