#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
APP_NAME="BrowserBuddy"

cd "$APP_DIR"

if ! command -v uv >/dev/null 2>&1; then
	echo "uv is required: https://docs.astral.sh/uv/" >&2
	exit 1
fi

if [[ ! -d "$ROOT_DIR/browser_use" ]]; then
	echo "Could not find browser_use at $ROOT_DIR/browser_use" >&2
	exit 1
fi

echo "==> Creating build environment"
uv venv --python 3.11 --clear .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing app dependencies"
uv pip install -e "$ROOT_DIR" gradio keyring pyinstaller playwright

# Some macOS installs have a mixed-architecture Command Line Tools bundle:
# /usr/bin/lipo picks its arm64e slice, which cannot load the x86_64 libxcrun.
# Falling back to the x86_64 lipo slice keeps PyInstaller's bootloader thinning working.
if ! xcrun --show-sdk-path >/dev/null 2>&1; then
	echo "==> xcrun is broken; using x86_64 lipo shim"
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
	--osx-bundle-identifier "com.example.browserbuddy"
	--collect-all browser_use
	--collect-all gradio
	--collect-all gradio_client
	--collect-all playwright
	--collect-all cdp_use
	--collect-all keyring
	--collect-all safehttpx
	--collect-all groovy
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
pyinstaller "${PYINSTALLER_ARGS[@]}" app.py

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
