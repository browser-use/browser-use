#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
APP_NAME="BrowserBuddy"

cd "$APP_DIR"

if ! command -v node >/dev/null 2>&1; then
	for node_bin in "$HOME"/.nvm/versions/node/*/bin; do
		if [[ -x "$node_bin/node" ]]; then
			export PATH="$node_bin:$PATH"
		fi
	done
fi

if ! command -v node >/dev/null 2>&1; then
	echo "Node.js is required to build the React frontend." >&2
	exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
	for uv_bin in "$HOME/.local/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
		if [[ -x "$uv_bin" ]]; then
			export PATH="$(dirname "$uv_bin"):$PATH"
			break
		fi
	done
fi

if ! command -v uv >/dev/null 2>&1; then
	echo "uv is required: https://docs.astral.sh/uv/" >&2
	exit 1
fi

echo "==> Building React frontend"
cd "$APP_DIR/frontend"
npm install
npm run build

echo "==> Creating Python build environment"
cd "$APP_DIR"
uv venv --python 3.11 --clear .venv
# shellcheck disable=SC1091
source .venv/bin/activate
uv pip install -e "$ROOT_DIR" fastapi uvicorn pywebview keyring httpx beautifulsoup4 pyinstaller playwright

# Some macOS Command Line Tools installs have a mixed-architecture libxcrun.
# Fall back to the x86_64 slices for tools that PyInstaller invokes.
if ! xcrun --show-sdk-path >/dev/null 2>&1; then
	echo "==> xcrun is broken; using x86_64 tool shims"
	mkdir -p "$APP_DIR/.build-tools"
	printf '#!/bin/bash\nexec arch -x86_64 /usr/bin/lipo "$@"\n' > "$APP_DIR/.build-tools/lipo"
	printf '#!/bin/bash\nexec arch -x86_64 /usr/bin/install_name_tool "$@"\n' > "$APP_DIR/.build-tools/install_name_tool"
	chmod +x "$APP_DIR/.build-tools/lipo" "$APP_DIR/.build-tools/install_name_tool"
	export PATH="$APP_DIR/.build-tools:$PATH"
fi

MODE=(--windowed)
if [[ "${CONSOLE:-0}" == "1" ]]; then
	MODE=(--console)
fi

PYINSTALLER_ARGS=(
	--noconfirm
	--clean
	"${MODE[@]}"
	--name "$APP_NAME"
	--osx-bundle-identifier "com.example.browserbuddystudio"
	--collect-all browser_use
	--collect-all webview
	--collect-all keyring
	--collect-all safehttpx
	--collect-all groovy
	--collect-all uvicorn
	--collect-all fastapi
	--hidden-import webview.platforms.cocoa
	--exclude-module browser_use.llm.oci_raw
	--add-data "frontend/dist:frontend/dist"
)

CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BUNDLE_CHROMIUM="${BUNDLE_CHROMIUM:-auto}"

if [[ "$BUNDLE_CHROMIUM" == "1" || ! -x "$CHROME_PATH" ]]; then
	echo "==> Installing Chromium into the bundle"
	PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/ms-playwright" python -m playwright install chromium
	PYINSTALLER_ARGS+=(--add-data "ms-playwright:ms-playwright")
else
	echo "==> Found system Google Chrome; skipping bundled Chromium"
	echo "    Set BUNDLE_CHROMIUM=1 if friends do not have Chrome."
fi

echo "==> Building .app"
rm -rf build dist
pyinstaller "${PYINSTALLER_ARGS[@]}" main.py

if [[ -n "${APPLE_SIGN_IDENTITY:-}" ]]; then
	echo "==> Signing app"
	codesign --deep --force --options runtime \
		--sign "$APPLE_SIGN_IDENTITY" "dist/$APP_NAME.app"
fi

echo "==> Creating DMG"
hdiutil create \
	-volname "$APP_NAME" \
	-srcfolder "dist/$APP_NAME.app" \
	-ov -format UDZO \
	"dist/$APP_NAME.dmg"

echo
echo "Done:"
echo "  App: $APP_DIR/dist/$APP_NAME.app"
echo "  DMG: $APP_DIR/dist/$APP_NAME.dmg"
echo
echo "Unsigned app: tell friends to right-click the app, choose Open, then Open again."
