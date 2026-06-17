#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if tmuxp is available
if ! command -v tmuxp &> /dev/null; then
    echo "tmuxp is not installed."
    echo "Install it with one of:"
    echo "  uv tool install tmuxp"
    echo "  pip install --user tmuxp"
    echo "  brew install tmuxp"
    exit 1
fi

# Check if tmux is available
if ! command -v tmux &> /dev/null; then
    echo "tmux is not installed."
    echo "Install it with: brew install tmux"
    exit 1
fi

cd "$SCRIPT_DIR"

# The backend requires environment variables from .env (TELEGRAM_API_ID/HASH,
# CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY) or it will fail to start.
if [ ! -f .env ]; then
    echo "Warning: .env not found — the backend pane will crash on startup."
    echo "Create it first:  cp .env.example .env  (then fill in the values)"
    echo
fi

tmuxp load -y .tmuxp.yaml
