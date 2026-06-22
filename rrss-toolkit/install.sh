#!/usr/bin/env bash
# RRSS Toolkit installer (POSIX / Git-Bash)
#
# Usage:
#   ./install.sh                       (from a local clone)
#   curl -fsSL <raw>/install.sh | bash (bootstraps from GitHub)
#
# Flags:
#   --skills-only      Install only the Claude Code skills (no pip)
#   --sdk-only         Install only the Python SDK (pip install rrss-arm)
#   --no-backup        Skip backing up existing SKILL.md files (overwrite)
#   --repo <slug>      Override repo for bootstrap (default: dnzengou/browser-use)
#   --branch <name>    Override branch (default: workspace)
#   --help

set -euo pipefail

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'

log()   { printf '%s\n' "${BLUE}>${NC} $*"; }
ok()    { printf '%s\n' "${GREEN}✓${NC} $*"; }
warn()  { printf '%s\n' "${YELLOW}!${NC} $*"; }
err()   { printf '%s\n' "${RED}x${NC} $*" >&2; }

REPO="dnzengou/browser-use"
BRANCH="workspace"
TOOLKIT_SUBDIR="rrss-toolkit"
SKILLS_ONLY=0
SDK_ONLY=0
BACKUP=1

while [[ $# -gt 0 ]]; do
	case $1 in
		--skills-only) SKILLS_ONLY=1; shift ;;
		--sdk-only) SDK_ONLY=1; shift ;;
		--no-backup) BACKUP=0; shift ;;
		--repo) REPO="$2"; shift 2 ;;
		--branch) BRANCH="$2"; shift 2 ;;
		--help|-h)
			grep '^# ' "$0" | sed 's/^# //'
			exit 0 ;;
		*) warn "unknown arg: $1"; shift ;;
	esac
done

# Resolve toolkit root: prefer local clone, fall back to GitHub fetch.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo '')"
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/skills/manifest.json" ]]; then
	TOOLKIT_ROOT="$SCRIPT_DIR"
	log "Installing from local checkout: $TOOLKIT_ROOT"
else
	TMP="$(mktemp -d)"
	trap 'rm -rf "$TMP"' EXIT
	log "Bootstrapping from https://github.com/$REPO@$BRANCH"
	if ! command -v git >/dev/null 2>&1; then
		err "git not found. Install git or run from a local clone."
		exit 1
	fi
	git clone --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$TMP/repo" >/dev/null 2>&1
	TOOLKIT_ROOT="$TMP/repo/$TOOLKIT_SUBDIR"
	if [[ ! -d "$TOOLKIT_ROOT" ]]; then
		err "$TOOLKIT_SUBDIR not found in $REPO@$BRANCH"
		exit 1
	fi
fi

MANIFEST="$TOOLKIT_ROOT/skills/manifest.json"
[[ -f "$MANIFEST" ]] || { err "manifest.json missing at $MANIFEST"; exit 1; }

# Verify sha256s if checksums.txt is present (RRSS Resistant principle).
verify_checksums() {
	local checksums="$TOOLKIT_ROOT/checksums.txt"
	[[ -f "$checksums" ]] || { warn "checksums.txt not present; skipping integrity check"; return 0; }
	if ! command -v sha256sum >/dev/null 2>&1; then
		warn "sha256sum not on PATH; skipping integrity check"
		return 0
	fi
	(cd "$TOOLKIT_ROOT" && sha256sum -c checksums.txt >/dev/null) && ok "checksums verified" \
		|| { err "checksum mismatch"; exit 1; }
}

install_skills() {
	verify_checksums
	# Parse manifest with python (more portable than jq).
	local python_cmd
	for c in python3 python py; do
		if command -v "$c" >/dev/null 2>&1; then python_cmd="$c"; break; fi
	done
	[[ -n "${python_cmd:-}" ]] || { err "python not found; cannot parse manifest"; exit 1; }

	local mappings
	mappings="$("$python_cmd" -c "
import json, sys
with open(r'''$MANIFEST''') as f:
    m = json.load(f)
for s in m['skills']:
    print(s['name'] + '\t' + s['source'] + '\t' + s['dest'])
")"

	local claude_skills="$HOME/.claude/skills"
	mkdir -p "$claude_skills"
	while IFS=$'\t' read -r name src dest; do
		local src_path="$TOOLKIT_ROOT/$src"
		local dest_path="${dest/#~/$HOME}"
		local dest_dir
		dest_dir="$(dirname "$dest_path")"
		mkdir -p "$dest_dir"
		if [[ -f "$dest_path" && $BACKUP -eq 1 ]]; then
			cp -f "$dest_path" "$dest_path.backup.$(date +%Y%m%d-%H%M%S)"
		fi
		cp -f "$src_path" "$dest_path"
		ok "skill installed: $name -> $dest_path"
	done <<< "$mappings"
}

install_sdk() {
	if ! command -v pip >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
		warn "pip not found; skipping Python SDK install. Try: pip install rrss-arm"
		return 0
	fi
	local pip_cmd
	pip_cmd="$(command -v pip3 || command -v pip)"
	log "Installing rrss-arm via $pip_cmd"
	"$pip_cmd" install --upgrade "$TOOLKIT_ROOT/sdk/python" || {
		err "pip install failed; try: pip install rrss-arm"
		return 1
	}
	ok "rrss-arm installed"
}

main() {
	echo "${BOLD}━━━ RRSS Toolkit installer ━━━${NC}"
	if [[ $SDK_ONLY -eq 0 ]]; then
		install_skills
	fi
	if [[ $SKILLS_ONLY -eq 0 ]]; then
		install_sdk
	fi
	echo ""
	ok "Done."
	echo "Skills: ${BOLD}/kafca${NC}, ${BOLD}/kafcade${NC}, ${BOLD}/evo-metaclaw${NC}, ${BOLD}/rrss${NC}"
	echo "SDK:    ${BOLD}python -c 'from rrss_arm import HostCircuitBreaker; print(HostCircuitBreaker.__doc__[:80])'${NC}"
}

main
