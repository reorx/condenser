#!/usr/bin/env bash
#
# Log an agent-browser session into the local dev app, so a UI walkthrough can start
# behind the auth gate.
#
#   scripts/dev-browser-login.sh [session] [--backend URL] [--frontend URL] [--env FILE]
#
# The app password never reaches a command line, a shell history or an agent
# transcript: envops pipes it into curl over stdin, curl keeps the session in a jar
# file, and only the cookie file path is handed to agent-browser. Both temp files are
# deleted on exit; the session cookie lives on inside the browser profile.
#
# Two things this script exists to encode (both cost an afternoon to rediscover):
#
#   1. agent-browser's cookie file must be bare "k=v; k2=v2". Give it a
#      "Cookie: k=v" header line and it keeps "Cookie: k" as the cookie NAME —
#      the cookie is stored, `cookies get` shows it, and the server never sees it.
#   2. Cookies ignore ports, so a cookie obtained from the backend (:8792) is sent
#      to the Vite dev server (:5792) as long as the host matches. Log in against
#      the backend directly and inject for the frontend origin.
#
# Prerequisites: the dev backend + `pnpm dev` running, `agent-browser` and `envops`
# on PATH. If the backend was started without --reload, restart it or the walkthrough
# verifies stale code:
#   uv run uvicorn condenser.app:create_app --factory --reload --reload-dir condenser --port 8792
set -euo pipefail

SESSION='cond-dev'
BACKEND='http://localhost:8792'
FRONTEND='http://localhost:5792'
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --frontend) FRONTEND="$2"; shift 2 ;;
    --env) ENV_FILE="$2"; shift 2 ;;
    -h | --help) sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^#\( \|$\)//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) SESSION="$1"; shift ;;
  esac
done

for cmd in agent-browser envops curl; do
  command -v "$cmd" >/dev/null || { echo "missing required command: $cmd" >&2; exit 1; }
done

JAR="$(mktemp -t condenser-jar)"
COOKIES="$(mktemp -t condenser-cookies)"
trap 'rm -f "$JAR" "$COOKIES"' EXIT

envops read-value "$ENV_FILE" -K CONDENSER_APP_PASSWORD --unsafe |
  python3 -c 'import json,sys; print(json.dumps({"password": sys.stdin.read().strip()}))' |
  curl -sf -o /dev/null -c "$JAR" -H 'Content-Type: application/json' \
    --data-binary @- "$BACKEND/api/auth/login" ||
  { echo "login failed against $BACKEND" >&2; exit 1; }

# Netscape jar -> "k=v; k2=v2" (see note 1 above)
awk -F'\t' 'NF == 7 { printf "%s%s=%s", sep, $6, $7; sep = "; " } END { print "" }' "$JAR" > "$COOKIES"

agent-browser --session "$SESSION" open "$FRONTEND/" >/dev/null
agent-browser --session "$SESSION" cookies set --curl "$COOKIES" --url "$FRONTEND" --path / >/dev/null
agent-browser --session "$SESSION" reload >/dev/null

status="$(agent-browser --session "$SESSION" eval "fetch('/api/tg/status').then(r => r.status)" | tail -1)"
if [ "$status" = '200' ]; then
  echo "session '$SESSION' is logged in at $FRONTEND"
else
  echo "cookie injected but /api/tg/status returned $status — is $BACKEND up and proxied?" >&2
  exit 1
fi
