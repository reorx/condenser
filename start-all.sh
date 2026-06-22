#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAYOUT_KDL="$SCRIPT_DIR/condenser.kdl"

MODE="tmuxp" # tmuxp | zellij | new-tab

usage() {
    cat <<'EOF'
Usage: start-all.sh [--zellij | --new-tab]

Launch the condenser dev environment (FastAPI backend :8792 + Vite :5792,
side by side).

  (no option)   tmuxp + tmux via .tmuxp.yaml — the default.
  --zellij      Start a new zellij session "condenser" from condenser.kdl.
  --new-tab     Add the layout as a new tab in the CURRENT zellij session
                (run from inside zellij). Implies zellij.
  -h, --help    Show this help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --zellij)  MODE="zellij" ;;
        --new-tab) MODE="new-tab" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; echo; usage; exit 1 ;;
    esac
    shift
done

require_cmd() {
    # require_cmd <command> <message...>
    local cmd="$1"; shift
    if ! command -v "$cmd" &> /dev/null; then
        echo "$cmd is not installed."
        printf '%s\n' "$@"
        exit 1
    fi
}

cd "$SCRIPT_DIR"

# The backend requires environment variables from .env (TELEGRAM_API_ID/HASH,
# CONDENSER_APP_PASSWORD, CONDENSER_SECRET_KEY) or it will fail to start.
if [ ! -f .env ]; then
    echo "Warning: .env not found — the backend pane will crash on startup."
    echo "Create it first:  cp .env.example .env  (then fill in the values)"
    echo
fi

case "$MODE" in
    tmuxp)
        require_cmd tmuxp \
            "Install it with one of:" \
            "  uv tool install tmuxp" \
            "  pip install --user tmuxp" \
            "  brew install tmuxp"
        require_cmd tmux "Install it with: brew install tmux"
        tmuxp load -y .tmuxp.yaml
        ;;

    zellij)
        require_cmd zellij "Install it with: brew install zellij"
        if [ ! -f "$LAYOUT_KDL" ]; then
            echo "Layout not found: $LAYOUT_KDL"
            exit 1
        fi
        # `zellij --layout` starts a session; nesting one inside another only warns
        # and won't add a tab. Point the user at --new-tab instead.
        if [ -n "${ZELLIJ:-}" ]; then
            echo "Already inside a zellij session — use --new-tab to add a tab here."
            exit 1
        fi
        zellij --session condenser --layout "$LAYOUT_KDL"
        ;;

    new-tab)
        require_cmd zellij "Install it with: brew install zellij"
        if [ ! -f "$LAYOUT_KDL" ]; then
            echo "Layout not found: $LAYOUT_KDL"
            exit 1
        fi
        # `action new-tab` talks to a running session; it errors without one.
        if [ -z "${ZELLIJ:-}" ]; then
            echo "Not inside a zellij session — run this from within zellij,"
            echo "or use --zellij to start a fresh 'condenser' session."
            exit 1
        fi
        # --cwd anchors the layout's relative cwds (the frontend pane's "frontend")
        # to the project root regardless of the calling shell's directory.
        zellij action new-tab --layout "$LAYOUT_KDL" --cwd "$SCRIPT_DIR"
        ;;
esac
