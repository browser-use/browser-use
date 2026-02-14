#!/usr/bin/env bash
# Browser-Use Bootstrap Installer
#
# Usage:
#   # Interactive install (shows mode selection TUI)
#   curl -fsSL https://browser-use.com/cli/install.sh | bash
#
#   # Non-interactive install with flags
#   curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full
#   curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only
#   curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --local-only
#
#   # With API key
#   curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only --api-key bu_xxx
#
# For development testing:
#   curl -fsSL <raw-url> | BROWSER_USE_BRANCH=<branch-name> bash
#
# =============================================================================
# WINDOWS INSTALLATION NOTES
# =============================================================================
#
# Windows requires Git Bash to run this script. Install Git for Windows first:
#   winget install Git.Git
#
# Then run from PowerShell:
#   & "C:\Program Files\Git\bin\bash.exe" -c 'curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full'
#
# KNOWN ISSUES AND SOLUTIONS:
#
# 1. Python 3.14+ not yet tested
#    - If you encounter asyncio/runtime issues on 3.14, use Python 3.11, 3.12, or 3.13
#    - You can install 3.13 alongside an existing 3.14:
#      winget install Python.Python.3.13
#
# 2. ARM64 Windows (Surface Pro X, Snapdragon laptops)
#    - Many Python packages don't have pre-built ARM64 wheels
#    - Solution: Install x64 Python (runs via emulation):
#      winget install Python.Python.3.13 --architecture x64
#
# 3. Multiple Python versions installed
#    - Windows uses the 'py' launcher, not 'python3.x' commands
#    - The script may pick the wrong version if multiple are installed
#    - Solution: Uninstall unwanted Python versions, or set PY_PYTHON=3.13
#
# 4. Stale virtual environment
#    - If you reinstall with a different Python version, delete the old venv
#    - First kill any Python processes holding it open:
#      taskkill /IM python.exe /F
#    - Then delete:
#      Remove-Item -Recurse -Force "$env:USERPROFILE\.browser-use-env"
#
# 5. PATH not working in PowerShell after install
#    - The script modifies your Windows user PATH directly (no execution policy needed)
#    - You must restart PowerShell for changes to take effect
#    - If it still doesn't work, check your PATH:
#      echo $env:PATH
#    - Or run commands through Git Bash:
#      & "C:\Program Files\Git\bin\bash.exe" -c 'browser-use open https://example.com'
#
# 6. "Failed to start session server" error
#    This generic error usually means a zombie server process is holding the port.
#
#    Step 1: Find the process using the port
#      netstat -ano | findstr 49698
#      # Output shows PID in last column, e.g.: TCP 127.0.0.1:49698 ... LISTENING 1234
#
#    Step 2: Kill the zombie process
#      taskkill /PID 1234 /F
#
#    Step 3: Try again
#      bu open https://example.com
#
#    If it keeps happening after bu close:
#    - The server cleanup may be hanging during browser shutdown
#    - Always kill stale processes before retrying
#    - Or kill all Python: taskkill /IM python.exe /F
#
# 7. Debugging server issues
#    To see actual error messages instead of "Failed to start session server":
#      & "$env:USERPROFILE\.browser-use-env\Scripts\python.exe" -m browser_use.skill_cli.server --session default --browser chromium
#    This runs the server in foreground and shows all errors.
#
# =============================================================================

set -e

# =============================================================================
# Configuration
# =============================================================================

# Mode flags (set by parse_args or TUI)
INSTALL_LOCAL=false
INSTALL_REMOTE=false
SKIP_INTERACTIVE=false
API_KEY=""

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
	echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
	echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
	echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
	echo -e "${RED}✗${NC} $1"
}

# =============================================================================
# Argument parsing
# =============================================================================

parse_args() {
	while [[ $# -gt 0 ]]; do
		case $1 in
			--full|--all)
				INSTALL_LOCAL=true
				INSTALL_REMOTE=true
				SKIP_INTERACTIVE=true
				shift
				;;
			--remote-only)
				INSTALL_REMOTE=true
				SKIP_INTERACTIVE=true
				shift
				;;
			--local-only)
				INSTALL_LOCAL=true
				SKIP_INTERACTIVE=true
				shift
				;;
			--api-key)
				if [ -z "$2" ] || [[ "$2" == --* ]]; then
					log_error "--api-key requires a value"
					exit 1
				fi
				API_KEY="$2"
				shift 2
				;;
			--help|-h)
				echo "Browser-Use Installer"
				echo ""
				echo "Usage: install.sh [OPTIONS]"
				echo ""
				echo "Options:"
				echo "  --full, --all     Install all modes (local + remote)"
				echo "  --remote-only     Install remote mode only (no Chromium)"
				echo "  --local-only      Install local modes only (no cloudflared)"
				echo "  --api-key KEY     Set Browser-Use API key"
				echo "  --help, -h        Show this help"
				echo ""
				echo "Without options, shows interactive mode selection."
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
	local os=$(uname -s | tr '[:upper:]' '[:lower:]')
	local arch=$(uname -m)

	case "$os" in
		linux*)
			PLATFORM="linux"
			;;
		darwin*)
			PLATFORM="macos"
			;;
		msys*|mingw*|cygwin*)
			PLATFORM="windows"
			;;
		*)
			log_error "Unsupported OS: $os"
			exit 1
			;;
	esac

	log_info "Detected platform: $PLATFORM ($arch)"
}

# =============================================================================
# Virtual environment helpers
# =============================================================================

# Get the correct venv bin directory (Scripts on Windows, bin on Unix)
get_venv_bin_dir() {
	if [ "$PLATFORM" = "windows" ]; then
		echo "$HOME/.browser-use-env/Scripts"
	else
		echo "$HOME/.browser-use-env/bin"
	fi
}

# Activate the virtual environment (handles Windows vs Unix paths)
activate_venv() {
	local venv_bin=$(get_venv_bin_dir)
	if [ -f "$venv_bin/activate" ]; then
		source "$venv_bin/activate"
	else
		log_error "Virtual environment not found at $venv_bin"
		exit 1
	fi
}

# =============================================================================
# Python management
# =============================================================================

check_python() {
	log_info "Checking Python installation..."

	# Check versioned python commands first (python3.13, python3.12, python3.11)
	# This handles Ubuntu/Debian where python3 may point to older version
	# Also check common install locations directly in case PATH isn't updated
	local py_candidates="python3.13 python3.12 python3.11 python3 python"
	local py_paths="/usr/bin/python3.11 /usr/local/bin/python3.11"

	for py_cmd in $py_candidates; do
		if command -v "$py_cmd" &> /dev/null; then
			local version=$($py_cmd --version 2>&1 | awk '{print $2}')
			local major=$(echo $version | cut -d. -f1)
			local minor=$(echo $version | cut -d. -f2)

			if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
				PYTHON_CMD="$py_cmd"
				log_success "Python $version found ($py_cmd)"
				return 0
			fi
		fi
	done

	# Also check common paths directly (in case command -v doesn't find them)
	for py_path in $py_paths; do
		if [ -x "$py_path" ]; then
			local version=$($py_path --version 2>&1 | awk '{print $2}')
			local major=$(echo $version | cut -d. -f1)
			local minor=$(echo $version | cut -d. -f2)

			if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
				PYTHON_CMD="$py_path"
				log_success "Python $version found ($py_path)"
				return 0
			fi
		fi
	done

	# No suitable Python found
	if command -v python3 &> /dev/null; then
		local version=$(python3 --version 2>&1 | awk '{print $2}')
		log_warn "Python $version found, but 3.11+ required"
	else
		log_warn "Python not found"
	fi
	return 1
}

install_python() {
	log_info "Installing Python 3.11+..."

	# Use sudo only if not root and sudo is available
	SUDO=""
	if [ "$(id -u)" -ne 0 ] && command -v sudo &> /dev/null; then
		SUDO="sudo"
	fi

	case "$PLATFORM" in
		macos)
			if command -v brew &> /dev/null; then
				brew install python@3.11
			else
				log_error "Homebrew not found. Install from: https://brew.sh"
				exit 1
			fi
			;;
		linux)
			if command -v apt-get &> /dev/null; then
				$SUDO apt-get update
				$SUDO apt-get install -y python3.11 python3.11-venv python3-pip
			elif command -v yum &> /dev/null; then
				$SUDO yum install -y python311 python311-pip
			else
				log_error "Unsupported package manager. Install Python 3.11+ manually."
				exit 1
			fi
			;;
		windows)
			log_error "Please install Python 3.11+ from: https://www.python.org/downloads/"
			exit 1
			;;
	esac

	# Verify installation
	if check_python; then
		log_success "Python installed successfully"
	else
		log_error "Python installation failed"
		exit 1
	fi
}

# =============================================================================
# uv package manager
# =============================================================================

install_uv() {
	log_info "Installing uv package manager..."

	if command -v uv &> /dev/null; then
		log_success "uv already installed"
		return 0
	fi

	# Use official uv installer
	curl -LsSf https://astral.sh/uv/install.sh | sh

	# Add common uv install locations to PATH for current session
	export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

	if command -v uv &> /dev/null; then
		log_success "uv installed successfully"
	else
		log_error "uv installation failed. Try restarting your shell and run the installer again."
		exit 1
	fi
}

# =============================================================================
# Gum TUI installation
# =============================================================================

install_gum() {
	# Install gum for beautiful TUI - silent and fast
	if command -v gum &> /dev/null; then
		return 0
	fi

	local arch=$(uname -m)
	local gum_version="0.14.5"
	local gum_dir=""

	mkdir -p "$HOME/.local/bin"
	export PATH="$HOME/.local/bin:$PATH"

	case "$PLATFORM" in
		macos)
			if [ "$arch" = "arm64" ]; then
				gum_dir="gum_${gum_version}_Darwin_arm64"
				curl -sL "https://github.com/charmbracelet/gum/releases/download/v${gum_version}/gum_${gum_version}_Darwin_arm64.tar.gz" | tar -xz -C /tmp
			else
				gum_dir="gum_${gum_version}_Darwin_x86_64"
				curl -sL "https://github.com/charmbracelet/gum/releases/download/v${gum_version}/gum_${gum_version}_Darwin_x86_64.tar.gz" | tar -xz -C /tmp
			fi
			mv "/tmp/${gum_dir}/gum" "$HOME/.local/bin/" 2>/dev/null || return 1
			rm -rf "/tmp/${gum_dir}" 2>/dev/null
			;;
		linux)
			if [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then
				gum_dir="gum_${gum_version}_Linux_arm64"
				curl -sL "https://github.com/charmbracelet/gum/releases/download/v${gum_version}/gum_${gum_version}_Linux_arm64.tar.gz" | tar -xz -C /tmp
			else
				gum_dir="gum_${gum_version}_Linux_x86_64"
				curl -sL "https://github.com/charmbracelet/gum/releases/download/v${gum_version}/gum_${gum_version}_Linux_x86_64.tar.gz" | tar -xz -C /tmp
			fi
			mv "/tmp/${gum_dir}/gum" "$HOME/.local/bin/" 2>/dev/null || return 1
			rm -rf "/tmp/${gum_dir}" 2>/dev/null
			;;
		windows)
			# Download and extract Windows binary
			curl -sL "https://github.com/charmbracelet/gum/releases/download/v${gum_version}/gum_${gum_version}_Windows_x86_64.zip" -o /tmp/gum.zip
			unzip -q /tmp/gum.zip -d /tmp/gum_windows 2>/dev/null || return 1
			# Binary is inside a subdirectory: gum_x.x.x_Windows_x86_64/gum.exe
			mv "/tmp/gum_windows/gum_${gum_version}_Windows_x86_64/gum.exe" "$HOME/.local/bin/" 2>/dev/null || return 1
			rm -rf /tmp/gum.zip /tmp/gum_windows 2>/dev/null
			;;
		*)
			return 1
			;;
	esac

	command -v gum &> /dev/null
}

# =============================================================================
# Interactive mode selection TUI
# =============================================================================

show_mode_menu() {
	# Try to install gum for nice TUI
	if install_gum; then
		show_gum_menu
	else
		show_bash_menu
	fi
}

show_gum_menu() {
	echo ""

	# Styled header
	gum style --foreground 212 --bold "Select browser modes to install"
	gum style --foreground 240 "Use arrow keys to navigate, space to select, enter to confirm"
	echo ""

	# Checkbox selection with gum choose
	set +e
	SELECTED=$(gum choose --no-limit --height 10 \
		--cursor-prefix "[ ] " --selected-prefix "[✓] " --unselected-prefix "[ ] " \
		--header "" \
		--cursor.foreground 212 \
		--selected.foreground 212 \
		"Local browser   (chromium/real - requires Chromium)" \
		"Remote browser  (cloud - requires API key)" < /dev/tty)
	set -e

	# Parse selections
	if [[ "$SELECTED" == *"Local"* ]]; then INSTALL_LOCAL=true; fi
	if [[ "$SELECTED" == *"Remote"* ]]; then INSTALL_REMOTE=true; fi
}

show_bash_menu() {
	echo ""
	echo "Select browser modes to install (space-separated numbers):"
	echo ""
	echo "  1) Local browser  (chromium/real - requires Chromium download)"
	echo "  2) Remote browser (cloud - requires API key)"
	echo ""
	echo "Press Enter for default [1]"
	echo ""
	echo -n "> "

	# Read from /dev/tty to work even when script is piped
	# Keep set +e for the whole function to avoid issues with pattern matching
	set +e
	read -r choices < /dev/tty
	choices=${choices:-1}

	if [[ "$choices" == *"1"* ]]; then INSTALL_LOCAL=true; fi
	if [[ "$choices" == *"2"* ]]; then INSTALL_REMOTE=true; fi
	set -e
}

# =============================================================================
# Browser-Use installation
# =============================================================================

install_browser_use() {
	log_info "Installing browser-use..."

	# Create or use existing virtual environment
	if [ ! -d "$HOME/.browser-use-env" ]; then
		# Use discovered Python command (e.g., python3.11) or fall back to version spec
		if [ -n "$PYTHON_CMD" ]; then
			uv venv "$HOME/.browser-use-env" --python "$PYTHON_CMD"
		else
			uv venv "$HOME/.browser-use-env" --python 3.11
		fi
	fi

	# Activate venv and install
	activate_venv

	# Install from GitHub (main branch by default, or custom branch for testing)
	BROWSER_USE_BRANCH="${BROWSER_USE_BRANCH:-main}"
	BROWSER_USE_REPO="${BROWSER_USE_REPO:-browser-use/browser-use}"
	log_info "Installing from GitHub: $BROWSER_USE_REPO@$BROWSER_USE_BRANCH"
	# Clone and install locally to ensure all dependencies are resolved
	local tmp_dir=$(mktemp -d)
	git clone --depth 1 --branch "$BROWSER_USE_BRANCH" "https://github.com/$BROWSER_USE_REPO.git" "$tmp_dir"
	uv pip install "$tmp_dir"
	rm -rf "$tmp_dir"

	log_success "browser-use installed"
}

install_chromium() {
	log_info "Installing Chromium browser..."

	activate_venv

	# Build command - only use --with-deps on Linux (it fails on Windows/macOS)
	local cmd="uvx playwright install chromium"
	if [ "$PLATFORM" = "linux" ]; then
		cmd="$cmd --with-deps"
	fi
	cmd="$cmd --no-shell"

	eval $cmd

	log_success "Chromium installed"
}

install_cloudflared() {
	log_info "Installing cloudflared..."

	if command -v cloudflared &> /dev/null; then
		log_success "cloudflared already installed"
		return 0
	fi

	local arch=$(uname -m)

	case "$PLATFORM" in
		macos)
			if command -v brew &> /dev/null; then
				brew install cloudflared
			else
				# Direct download for macOS without Homebrew
				mkdir -p "$HOME/.local/bin"
				if [ "$arch" = "arm64" ]; then
					curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz -o /tmp/cloudflared.tgz
				else
					curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz -o /tmp/cloudflared.tgz
				fi
				tar -xzf /tmp/cloudflared.tgz -C "$HOME/.local/bin/"
				rm /tmp/cloudflared.tgz
			fi
			;;
		linux)
			mkdir -p "$HOME/.local/bin"
			if [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then
				curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o "$HOME/.local/bin/cloudflared"
			else
				curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o "$HOME/.local/bin/cloudflared"
			fi
			chmod +x "$HOME/.local/bin/cloudflared"
			;;
		windows)
			# Auto-install via winget (comes pre-installed on Windows 10/11)
			if command -v winget.exe &> /dev/null; then
				winget.exe install --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements --silent
			else
				log_warn "winget not found. Install cloudflared manually:"
				log_warn "  Download from: https://github.com/cloudflare/cloudflared/releases"
				return 0
			fi
			;;
	esac

	# Add ~/.local/bin to PATH for current session
	export PATH="$HOME/.local/bin:$PATH"

	if command -v cloudflared &> /dev/null; then
		log_success "cloudflared installed successfully"
	else
		log_warn "cloudflared installation failed. You can install it manually later."
	fi
}

# =============================================================================
# Install dependencies based on selected modes
# =============================================================================

install_dependencies() {
	# Install base package (always needed)
	install_browser_use

	# Install Chromium only if local mode selected
	if [ "$INSTALL_LOCAL" = true ]; then
		install_chromium
	else
		log_info "Skipping Chromium (remote-only mode)"
	fi

	# Install cloudflared only if remote mode selected
	if [ "$INSTALL_REMOTE" = true ]; then
		install_cloudflared
	else
		log_info "Skipping cloudflared (local-only mode)"
	fi
}

# =============================================================================
# Write install configuration
# =============================================================================

write_install_config() {
	# Determine installed modes and default
	local modes=""
	local default_mode=""

	if [ "$INSTALL_LOCAL" = true ] && [ "$INSTALL_REMOTE" = true ]; then
		modes='["chromium", "real", "remote"]'
		default_mode="chromium"
	elif [ "$INSTALL_REMOTE" = true ]; then
		modes='["remote"]'
		default_mode="remote"
	else
		modes='["chromium", "real"]'
		default_mode="chromium"
	fi

	# Write config file
	mkdir -p "$HOME/.browser-use"
	cat > "$HOME/.browser-use/install-config.json" << EOF
{
  "installed_modes": $modes,
  "default_mode": "$default_mode"
}
EOF

	local mode_names=$(echo $modes | tr -d '[]"' | tr ',' ' ')
	log_success "Configured: $mode_names"
}

# =============================================================================
# PATH configuration
# =============================================================================

configure_path() {
	local shell_rc=""
	local bin_path=$(get_venv_bin_dir)
	local local_bin="$HOME/.local/bin"

	# Detect shell
	if [ -n "$BASH_VERSION" ]; then
		shell_rc="$HOME/.bashrc"
	elif [ -n "$ZSH_VERSION" ]; then
		shell_rc="$HOME/.zshrc"
	else
		shell_rc="$HOME/.profile"
	fi

	# Check if already in PATH (browser-use-env matches both /bin and /Scripts)
	if grep -q "browser-use-env" "$shell_rc" 2>/dev/null; then
		log_info "PATH already configured in $shell_rc"
	else
		# Add to shell config (includes ~/.local/bin for cloudflared)
		echo "" >> "$shell_rc"
		echo "# Browser-Use" >> "$shell_rc"
		echo "export PATH=\"$bin_path:$local_bin:\$PATH\"" >> "$shell_rc"
		log_success "Added to PATH in $shell_rc"
	fi

	# On Windows, also configure PowerShell profile
	if [ "$PLATFORM" = "windows" ]; then
		configure_powershell_path
	fi
}

configure_powershell_path() {
	# Use PowerShell to modify user PATH in registry (no execution policy needed)
	# This persists across sessions without requiring profile script execution

	local scripts_path='\\.browser-use-env\\Scripts'
	local local_bin='\\.local\\bin'

	# Check if already in user PATH
	local current_path=$(powershell.exe -Command "[Environment]::GetEnvironmentVariable('Path', 'User')" 2>/dev/null | tr -d '\r')

	if echo "$current_path" | grep -q "browser-use-env"; then
		log_info "PATH already configured"
		return 0
	fi

	# Append to user PATH via registry (safe, no truncation, no execution policy needed)
	powershell.exe -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + \$env:USERPROFILE + '$scripts_path;' + \$env:USERPROFILE + '$local_bin', 'User')" 2>/dev/null

	if [ $? -eq 0 ]; then
		log_success "Added to Windows PATH: %USERPROFILE%\\.browser-use-env\\Scripts"
	else
		log_warn "Could not update PATH automatically. Add manually:"
		log_warn "  \$env:PATH += \";\$env:USERPROFILE\\.browser-use-env\\Scripts\""
	fi
}

# =============================================================================
# Setup wizard
# =============================================================================

run_setup() {
	log_info "Running setup wizard..."

	# Activate venv
	activate_venv

	# Determine profile based on mode selections
	local profile="local"
	if [ "$INSTALL_REMOTE" = true ] && [ "$INSTALL_LOCAL" = true ]; then
		profile="full"
	elif [ "$INSTALL_REMOTE" = true ]; then
		profile="remote"
	fi

	# Run setup with API key if provided
	if [ -n "$API_KEY" ]; then
		browser-use setup --mode "$profile" --api-key "$API_KEY" --yes
	else
		browser-use setup --mode "$profile" --yes
	fi
}

# =============================================================================
# Validation
# =============================================================================

validate() {
	log_info "Validating installation..."

	activate_venv

	if browser-use doctor; then
		log_success "Installation validated successfully!"
		return 0
	else
		log_warn "Some checks failed. Run 'browser-use doctor' for details."
		return 1
	fi
}

# =============================================================================
# Print completion message
# =============================================================================

print_next_steps() {
	# Detect shell for source command
	local shell_rc=".bashrc"
	if [ -n "$ZSH_VERSION" ]; then
		shell_rc=".zshrc"
	fi

	echo ""
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	echo ""
	log_success "Browser-Use installed successfully!"
	echo ""
	echo "Installed modes:"
	[ "$INSTALL_LOCAL" = true ]  && echo "  ✓ Local (chromium, real)"
	[ "$INSTALL_REMOTE" = true ] && echo "  ✓ Remote (cloud)"
	echo ""

	# Show API key instructions if remote selected but no key provided
	if [ "$INSTALL_REMOTE" = true ] && [ -z "$API_KEY" ]; then
		echo "⚠ API key required for remote mode:"
		if [ "$PLATFORM" = "windows" ]; then
			echo "  \$env:BROWSER_USE_API_KEY=\"<your-api-key>\""
		else
			echo "  export BROWSER_USE_API_KEY=<your-api-key>"
		fi
		echo ""
		echo "  Get your API key at: https://browser-use.com"
		echo ""
	fi

	echo "Next steps:"
	if [ "$PLATFORM" = "windows" ]; then
		echo "  1. Restart PowerShell (PATH is now configured automatically)"
	else
		echo "  1. Restart your shell or run: source ~/$shell_rc"
	fi

	if [ "$INSTALL_REMOTE" = true ] && [ -z "$API_KEY" ]; then
		echo "  2. Set your API key (see above)"
		echo "  3. Try: browser-use open https://example.com"
	else
		echo "  2. Try: browser-use open https://example.com"
	fi

	echo ""
	echo "Documentation: https://docs.browser-use.com"
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	echo ""
}

# =============================================================================
# Main installation flow
# =============================================================================

main() {
	echo ""
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	echo "  Browser-Use Installer"
	echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	echo ""

	# Parse command-line flags
	parse_args "$@"

	# Show install mode if flags provided
	if [ "$SKIP_INTERACTIVE" = true ]; then
		if [ "$INSTALL_LOCAL" = true ] && [ "$INSTALL_REMOTE" = true ]; then
			log_info "Install mode: full (local + remote)"
		elif [ "$INSTALL_REMOTE" = true ]; then
			log_info "Install mode: remote-only"
		else
			log_info "Install mode: local-only"
		fi
		echo ""
	fi

	# Step 1: Detect platform
	detect_platform

	# Step 2: Check/install Python
	if ! check_python; then
		# In CI or non-interactive mode (no tty), auto-install Python
		if [ ! -t 0 ] || [ "$SKIP_INTERACTIVE" = true ]; then
			log_info "Python 3.11+ not found. Installing automatically..."
			install_python
		else
			read -p "Python 3.11+ not found. Install now? [y/N] " -n 1 -r < /dev/tty
			echo
			if [[ $REPLY =~ ^[Yy]$ ]]; then
				install_python
			else
				log_error "Python 3.11+ required. Exiting."
				exit 1
			fi
		fi
	fi

	# Step 3: Install uv
	install_uv

	# Step 4: Show mode selection TUI (unless skipped via flags)
	if [ "$SKIP_INTERACTIVE" = false ]; then
		show_mode_menu
	fi

	# Default to local-only if nothing selected
	if [ "$INSTALL_LOCAL" = false ] && [ "$INSTALL_REMOTE" = false ]; then
		log_warn "No modes selected, defaulting to local"
		INSTALL_LOCAL=true
	fi

	echo ""

	# Step 5: Install dependencies
	install_dependencies

	# Step 6: Write install config
	write_install_config

	# Step 7: Configure PATH
	configure_path

	# Step 8: Run setup wizard
	run_setup

	# Step 9: Validate
	validate

	# Step 10: Show next steps
	print_next_steps
}

# Run main function with all arguments
main "$@"
