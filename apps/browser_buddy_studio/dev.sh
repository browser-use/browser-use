#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"

if ! command -v node >/dev/null 2>&1; then
	for node_bin in "$HOME"/.nvm/versions/node/*/bin; do
		if [[ -x "$node_bin/node" ]]; then
			export PATH="$node_bin:$PATH"
		fi
	done
fi

if ! command -v uv >/dev/null 2>&1; then
	for uv_bin in "$HOME/.local/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
		if [[ -x "$uv_bin" ]]; then
			export PATH="$(dirname "$uv_bin"):$PATH"
			break
		fi
	done
fi

cd "$APP_DIR"
if [[ ! -d .venv ]]; then
	uv venv --python 3.11 .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
uv pip install -e "$ROOT_DIR" fastapi uvicorn keyring httpx beautifulsoup4 >/dev/null

cd "$APP_DIR/frontend"
if [[ ! -d node_modules ]]; then
	npm install
fi

cleanup() {
	if [[ -n "${BACKEND_PID:-}" ]]; then
		kill "$BACKEND_PID" 2>/dev/null || true
	fi
}
trap cleanup EXIT

cd "$APP_DIR"
uvicorn backend.server:app --host 127.0.0.1 --port 8765 >"$APP_DIR/dev-backend.log" 2>&1 &
BACKEND_PID=$!

cd "$APP_DIR/frontend"
npm run dev
