#!/usr/bin/env bash
#
# Build a self-contained macOS app + drag-to-install DMG.
#
# End users need neither Python nor Chrome:
#   - CPython and every Python dependency are embedded by PyInstaller.
#   - Chromium is copied into Contents/Frameworks/ms-playwright.
#
# Output:
#   dist/BrowserBuddy.app
#   dist/BrowserBuddy.dmg   (open, drag BrowserBuddy into Applications)
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$APP_DIR/../.." && pwd)"
APP_NAME="BrowserBuddy"
BUNDLE_ID="com.example.browserbuddystudio"
DIST_DIR="$APP_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/$APP_NAME.dmg"

# auto = skip the Chromium download when this Mac already has Chrome/Chromium
# 1    = force shipping Chromium inside the app (universal build)
# 0    = never ship Chromium (smaller build, requires Chrome on the target Mac)
BUNDLE_CHROMIUM="${BUNDLE_CHROMIUM:-auto}"
SKIP_SMOKE_TEST="${SKIP_SMOKE_TEST:-0}"
APP_VERSION="${APP_VERSION:-1.0.0}"
# The official CDN redirects to storage.googleapis.com, which is unreachable in
# mainland China. Use the npmmirror copy by default; override for the official one:
#   PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.playwright.dev ./build_mac.sh
CHROMIUM_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://cdn.npmmirror.com/binaries/playwright}"
export APP_VERSION

detect_system_browser() {
	for candidate in \
		"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
		"/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta" \
		"/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary" \
		"/Applications/Chromium.app/Contents/MacOS/Chromium" \
		"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
		"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
		if [[ -x "$candidate" ]]; then
			printf '%s\n' "$candidate"
			return 0
		fi
	done
	return 1
}

SYSTEM_BROWSER="$(detect_system_browser || true)"
if [[ "$BUNDLE_CHROMIUM" == "auto" ]]; then
	if [[ -n "$SYSTEM_BROWSER" ]]; then
		BUNDLE_CHROMIUM=0
	else
		BUNDLE_CHROMIUM=1
	fi
fi

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
uv pip install -e "$ROOT_DIR" fastapi uvicorn pywebview httpx beautifulsoup4 pyinstaller playwright

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

if [[ "$BUNDLE_CHROMIUM" == "0" ]]; then
	if [[ -n "$SYSTEM_BROWSER" ]]; then
		echo "==> Found local browser, skipping the Chromium download:"
		echo "    $SYSTEM_BROWSER"
		echo "    The app will use the browser installed on the target Mac."
		echo "    Use BUNDLE_CHROMIUM=1 for a build that works without Chrome."
	else
		echo "==> BUNDLE_CHROMIUM=0: the app will require Chrome on the target Mac" >&2
	fi
fi

if [[ "$BUNDLE_CHROMIUM" != "0" ]]; then
	echo "==> Downloading Chromium for the app bundle"
	echo "    host: $CHROMIUM_HOST"
	rm -rf "$APP_DIR/ms-playwright"
	if ! PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/ms-playwright" \
		PLAYWRIGHT_DOWNLOAD_HOST="$CHROMIUM_HOST" \
		PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=30000 \
		python -m playwright install --no-shell chromium; then
		echo "==> Mirror failed; retrying the official Playwright CDN"
		rm -rf "$APP_DIR/ms-playwright"
		PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/ms-playwright" \
			PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=30000 \
			python -m playwright install --no-shell chromium
	fi
fi

echo "==> Building .app (embedded CPython, no system Python needed)"
rm -rf build "$DIST_DIR"
pyinstaller --noconfirm --clean BrowserBuddy.spec

if [[ "$BUNDLE_CHROMIUM" != "0" ]]; then
	echo "==> Copying Chromium into Contents/Frameworks/ms-playwright"
	# ditto preserves executable bits and the .app symlinks inside Chromium.
	/usr/bin/ditto "$APP_DIR/ms-playwright" "$APP_BUNDLE/Contents/Frameworks/ms-playwright"
	# Playwright downloads from the network; never ship quarantine flags.
	xattr -dr com.apple.quarantine "$APP_BUNDLE/Contents/Frameworks/ms-playwright" 2>/dev/null || true
fi

if ! compgen -G "$APP_BUNDLE/Contents/Frameworks/libpython*.dylib" >/dev/null; then
	echo "ERROR: the bundle does not contain an embedded Python runtime." >&2
	exit 1
fi

xattr -cr "$APP_BUNDLE" 2>/dev/null || true

SIGN_IDENTITY="${APPLE_SIGN_IDENTITY:--}"
echo "==> Signing the app ($SIGN_IDENTITY)"
if [[ "$SIGN_IDENTITY" == "-" ]]; then
	codesign --force --deep --sign - "$APP_BUNDLE"
else
	codesign --force --deep --options runtime \
		--entitlements "$APP_DIR/entitlements.plist" \
		--sign "$SIGN_IDENTITY" "$APP_BUNDLE"
fi

if [[ "$SKIP_SMOKE_TEST" != "1" ]]; then
	echo "==> Smoke-testing the packaged app"
	SMOKE_DATA="$(mktemp -d "${TMPDIR:-/tmp}/browserbuddy-smoke.XXXXXX")"
	SMOKE_PORT="$(
		"$APP_DIR/.venv/bin/python" - <<'PY'
import socket
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
print(sock.getsockname()[1])
sock.close()
PY
	)"
	BROWSER_BUDDY_SERVER_ONLY=1 \
		BROWSER_BUDDY_PORT="$SMOKE_PORT" \
		BROWSER_BUDDY_DATA_DIR="$SMOKE_DATA" \
		"$APP_BUNDLE/Contents/MacOS/$APP_NAME" &
	SMOKE_PID=$!

	SMOKE_OK=0
	for _ in $(seq 1 60); do
		if curl -fsS "http://127.0.0.1:$SMOKE_PORT/api/health" >/dev/null 2>&1; then
			SMOKE_OK=1
			break
		fi
		if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
			break
		fi
		sleep 0.5
	done

	kill "$SMOKE_PID" 2>/dev/null || true
	wait "$SMOKE_PID" 2>/dev/null || true

	if [[ "$SMOKE_OK" != "1" ]]; then
		echo "Smoke test failed. Log:" >&2
		cat "$SMOKE_DATA/logs/studio.log" 2>/dev/null >&2 || true
		rm -rf "$SMOKE_DATA"
		exit 1
	fi
	rm -rf "$SMOKE_DATA"
	echo "    OK: the frozen app served /api/health with no system Python"
fi

echo "==> Creating DMG with drag-to-Applications layout"
STAGING="$APP_DIR/build/dmg"
rm -rf "$STAGING"
mkdir -p "$STAGING"
/usr/bin/ditto "$APP_BUNDLE" "$STAGING/$APP_NAME.app"
ln -s /Applications "$STAGING/Applications"

for stale in /Volumes/$APP_NAME /Volumes/$APP_NAME\ [0-9]*; do
	if [[ -d "$stale" ]]; then
		hdiutil detach "$stale" -force >/dev/null 2>&1 || true
	fi
done

RW_DMG="$DIST_DIR/$APP_NAME-rw.dmg"
rm -f "$RW_DMG" "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDRW -fs HFS+ "$RW_DMG" >/dev/null

MOUNT_OUT="$(hdiutil attach "$RW_DMG" -nobrowse -readwrite)"
MOUNT_POINT="$(printf '%s\n' "$MOUNT_OUT" | awk -F'\t' '/\/Volumes\// {print $NF; exit}')"
if [[ -z "$MOUNT_POINT" ]]; then
	echo "ERROR: could not mount $RW_DMG" >&2
	exit 1
fi

# Cosmetic Finder layout. It is safe to skip when Finder automation is denied.
osascript >/dev/null 2>&1 <<EOF || echo "    (Finder layout skipped; dragging to Applications still works)"
tell application "Finder"
	tell disk "$APP_NAME"
		open
		set current view of container window to icon view
		set toolbar visible of container window to false
		set statusbar visible of container window to false
		set the bounds of container window to {120, 120, 720, 460}
		set viewOptions to the icon view options of container window
		set arrangement of viewOptions to not arranged
		set icon size of viewOptions to 128
		set position of item "$APP_NAME.app" of container window to {190, 190}
		set position of item "Applications" of container window to {510, 190}
		close
		open
		update without registering applications
		delay 1
		close
	end tell
end tell
EOF

sync
hdiutil detach "$MOUNT_POINT" -quiet || hdiutil detach "$MOUNT_POINT" -force >/dev/null
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_PATH" -ov >/dev/null
rm -f "$RW_DMG"
rm -rf "$STAGING"

if [[ -n "${APPLE_SIGN_IDENTITY:-}" && -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_PASSWORD:-}" ]]; then
	echo "==> Notarizing"
	xcrun notarytool submit "$DMG_PATH" \
		--apple-id "$APPLE_ID" \
		--team-id "$APPLE_TEAM_ID" \
		--password "$APPLE_APP_PASSWORD" \
		--wait
	xcrun stapler staple "$APP_BUNDLE"
	xcrun stapler staple "$DMG_PATH"
fi

echo
echo "Done:"
echo "  App: $APP_BUNDLE"
echo "  DMG: $DMG_PATH"
echo
if [[ "$SIGN_IDENTITY" == "-" ]]; then
	echo "The build is ad-hoc signed. On another Mac, first launch:"
	echo "  right-click BrowserBuddy → Open → Open."
	echo "For a clean install, set APPLE_SIGN_IDENTITY (Developer ID Application) and"
	echo "the APPLE_ID / APPLE_TEAM_ID / APPLE_APP_PASSWORD variables to notarize."
else
	echo "Signed with $SIGN_IDENTITY. Drag the app into Applications from the DMG."
fi
