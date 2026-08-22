#!/usr/bin/env bash
# Browser-Use Bootstrap Installer
#
# Usage:
#   curl -fsSL https://browser-use.com/cli/install.sh | bash
#
# For development testing against a specific branch:
#   curl -fsSL <raw-url> | BROWSER_USE_BRANCH=<branch-name> bash
#
# This installer sets up the current browser-use CLI (installed via uv) and
# downloads Chromium, so the `browser-use` command works out of the box.

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

UV_INSTALL_URL="https://astral.sh/uv/install.sh"
UV_BIN_DIR="$HOME/.local/bin"
PACKAGE="browser-use"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# =============================================================================
# Logging functions
# =============================================================================

log_info() {
	echo -e "${BLUE}i${NC} $1"
}

log_success() {
	echo -e "${GREEN}ok${NC} $1"
}

log_warn() {
	echo -e "${YELLOW}!${NC} $1"
}

log_error() {
	echo -e "${RED}x${NC} $1"
}

# =============================================================================
# Argument parsing
# =============================================================================

parse_args() {
	while [ $# -gt 0 ]; do
		case "$1" in
		--help | -h)
			echo "Browser-Use Installer"
			echo ""
			echo "Usage: install.sh [OPTIONS]"
			echo ""
			echo "Options:"
			echo "  --help, -h        Show this help"
			echo ""
			echo "Installs uv (if needed), the browser-use CLI, and Chromium."
			echo ""
			echo "Environment:"
			echo "  BROWSER_USE_BRANCH  Install from a specific git branch instead of PyPI"
			exit 0
			;;
		*)
			log_warn "Unknown argument: $1 (ignored)"
			shift
			;;
		esac
	done
}

# =============================================================================
# Platform detection
# =============================================================================

detect_platform() {
	local os
	os=$(uname -s | tr '[:upper:]' '[:lower:]')

	case "$os" in
	linux*)
		PLATFORM="linux"
		;;
	darwin*)
		PLATFORM="macos"
		;;
	msys* | mingw* | cygwin*)
		PLATFORM="windows"
		;;
	*)
		log_error "Unsupported OS: $os"
		exit 1
		;;
	esac

	log_info "Detected platform: $PLATFORM"
}

# =============================================================================
# uv management
# =============================================================================

ensure_uv() {
	if command -v uv >/dev/null 2>&1; then
		log_success "uv found ($(uv --version))"
		return 0
	fi

	log_info "uv not found. Installing uv..."
	if ! command -v curl >/dev/null 2>&1; then
		log_error "curl is required to install uv. Install curl first and re-run this script."
		exit 1
	fi

	curl -LsSf "$UV_INSTALL_URL" | sh

	if [ -x "$UV_BIN_DIR/uv" ]; then
		export PATH="$UV_BIN_DIR:$PATH"
		log_success "uv installed ($(uv --version))"
	else
		log_error "uv installation failed. Please install it manually: https://docs.astral.sh/uv/"
		exit 1
	fi
}

ensure_uv_tool_bin_on_path() {
	local uv_tool_bin
	uv_tool_bin=$(uv tool dir --bin 2>/dev/null || true)
	if [ -n "$uv_tool_bin" ]; then
		export PATH="$uv_tool_bin:$PATH"
	fi
}

# =============================================================================
# browser-use installation
# =============================================================================

install_browser_use() {
	log_info "Installing $PACKAGE..."

	if [ -n "${BROWSER_USE_BRANCH:-}" ]; then
		log_info "Installing from branch: $BROWSER_USE_BRANCH"
		uv tool install --upgrade --from "git+https://github.com/browser-use/browser-use@${BROWSER_USE_BRANCH}" "$PACKAGE"
	else
		uv tool install --upgrade "$PACKAGE"
	fi

	ensure_uv_tool_bin_on_path

	if command -v browser-use >/dev/null 2>&1; then
		log_success "browser-use installed ($(browser-use --version 2>/dev/null || echo 'version unknown'))"
	else
		log_warn "browser-use installed, but not on PATH. Add the uv tool bin directory to your PATH and re-open your shell."
		export PATH="$UV_BIN_DIR:$PATH"
	fi
}

# =============================================================================
# Chromium installation
# =============================================================================

install_chromium() {
	log_info "Installing Chromium browser and system dependencies..."
	if browser-use install; then
		log_success "Chromium installed."
	else
		log_warn "Chromium installation failed. Run 'browser-use install' manually to retry."
	fi
}

# =============================================================================
# Next steps
# =============================================================================

print_next_steps() {
	echo ""
	echo "================================================================"
	echo "  Browser-Use is ready!"
	echo "================================================================"
	echo ""
	echo "  Health check:   browser-use --doctor"
	echo "  Try it out:"
	echo "      browser-use <<'PY'"
	echo "      new_tab(\"https://news.ycombinator.com\")"
	echo "      print(page_info())"
	echo "      PY"
	echo ""
	echo "  Recommended:    browser-use skill install${BROWSER_USE_BRANCH:+ --no-install}"
	echo "  Docs: https://github.com/browser-use/browser-use"
	echo "  The 'browser-use' command may require a fresh terminal if your"
	echo "  PATH was just updated."
	echo "================================================================"
}

# =============================================================================
# Main
# =============================================================================

main() {
	parse_args "$@"
	detect_platform
	ensure_uv
	install_browser_use
	install_chromium
	print_next_steps
}

main "$@"
