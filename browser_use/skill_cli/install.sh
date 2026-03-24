#!/usr/bin/env bash
# Browser-Use Bootstrap Installer
#
# Usage:
#   curl -fsSL https://browser-use.com/cli/install.sh | bash
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
#   & "C:\Program Files\Git\bin\bash.exe" -c 'curl -fsSL https://browser-use.com/cli/install.sh | bash'
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
# 7. Debugging daemon issues
#    To see actual error messages instead of "Failed to start daemon":
#      & "$env:USERPROFILE\.browser-use-env\Scripts\python.exe" -m browser_use.skill_cli.daemon
#    This runs the daemon in foreground and shows all errors.
#
# =============================================================================

set -e

# =============================================================================
# Configuration
# =============================================================================

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
			--help|-h)
				echo "Browser-Use Installer"
				echo ""
				echo "Usage: install.sh [OPTIONS]"
				echo ""
				echo "Options:"
				echo "  --help, -h        Show this help"
				echo ""
				echo "Installs Python 3.11+ (if needed), uv, browser-use, and Chromium."
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

	# Add common uv install locations to PATH for current session
	# (covers both curl-based and Homebrew installs)
	export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

	if command -v uv &> /dev/null; then
		log_success "uv already installed"
		return 0
	fi

	# Use official uv installer
	curl -LsSf https://astral.sh/uv/install.sh | sh

	if command -v uv &> /dev/null; then
		log_success "uv installed successfully"
	else
		log_error "uv installation failed. Try restarting your shell and run the installer again."
		exit 1
	fi
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

install_profile_use() {
	log_info "Installing profile-use..."

	mkdir -p "$HOME/.browser-use/bin"
	curl -fsSL https://browser-use.com/profile/cli/install.sh | PROFILE_USE_VERSION=v1.0.2 INSTALL_DIR="$HOME/.browser-use/bin" sh

	if [ -x "$HOME/.browser-use/bin/profile-use" ]; then
		log_success "profile-use installed"
	else
		log_warn "profile-use installation failed (will auto-download on first use)"
	fi
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
		# Add to shell config (includes ~/.local/bin for tools)
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

	echo "Next steps:"
	if [ "$PLATFORM" = "windows" ]; then
		echo "  1. Restart PowerShell (PATH is now configured automatically)"
	else
		echo "  1. Restart your shell or run: source ~/$shell_rc"
	fi
	echo "  2. Try: browser-use open https://example.com"

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

	# Step 1: Detect platform
	detect_platform

	# Step 2: Check/install Python
	if ! check_python; then
		# In CI or non-interactive mode (no tty), auto-install Python
		if [ ! -t 0 ]; then
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

	# Step 4: Install browser-use package
	install_browser_use

	# Step 5: Install Chromium
	install_chromium

	# Step 6: Install profile-use
	install_profile_use

	# Step 7: Configure PATH
	configure_path

	# Step 8: Validate
	validate

	# Step 9: Print next steps
	print_next_steps
}

# Run main function with all arguments
main "$@"
