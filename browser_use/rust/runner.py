"""
Locate and launch the `but` Rust binary.

The binary ships from https://github.com/browser-use/terminal. Today users
install it via the standalone installer, which drops a `but` shim at
`~/.local/bin/but` that proxies to a versioned binary under
`~/.browser-use-terminal/packages/standalone/current/bin/but`. We honour that,
plus an explicit override via `$BUT_BINARY`, plus a fallback to whatever's on
`$PATH`.

A long-term goal is to bundle prebuilt platform wheels so `pip install
browser-use` brings `but` along. Until then, missing-binary raises
`ButNotInstalledError` with concrete install instructions.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

BUT_BINARY_ENV = 'BUT_BINARY'
"""Environment variable that overrides binary discovery (absolute path)."""

INSTALL_HINT = """\
The `but` Rust binary (browser-use terminal) is not on $PATH.

Install it with:

    curl -fsSL https://browser-use.com/install.sh | sh

Or set $BUT_BINARY to an absolute path. See
https://github.com/browser-use/terminal for source builds.
"""


class ButNotInstalledError(RuntimeError):
	"""Raised when the `but` binary can't be located."""

	def __init__(self, searched: list[Path]):
		self.searched = searched
		super().__init__(INSTALL_HINT + f'\nSearched: {[str(p) for p in searched]}')


def _candidate_paths() -> list[Path]:
	"""Ordered list of paths to probe for the `but` binary."""
	override = os.environ.get(BUT_BINARY_ENV)
	if override:
		return [Path(override).expanduser()]

	candidates: list[Path] = []
	home = Path.home()
	candidates.append(home / '.local' / 'bin' / 'but')
	candidates.append(home / '.browser-use-terminal' / 'packages' / 'standalone' / 'current' / 'bin' / 'but')

	# Repo-local debug build (for `task dev` / contributors).
	dev_paths = [
		home / '.superset' / 'projects' / 'terminal' / 'target' / 'debug' / 'but',
		Path.cwd() / 'target' / 'debug' / 'but',
	]
	candidates.extend(p for p in dev_paths if p not in candidates)

	on_path = shutil.which('but')
	if on_path:
		candidates.append(Path(on_path))

	return candidates


def find_but_binary() -> Path:
	"""Return the path to a working `but` binary or raise."""
	tried: list[Path] = []
	for candidate in _candidate_paths():
		if candidate in tried:
			continue
		tried.append(candidate)
		if candidate.exists() and os.access(candidate, os.X_OK):
			return candidate
	raise ButNotInstalledError(tried)


def _candidate_cli_paths() -> list[Path]:
	"""Candidate paths for the headless `browser-use-terminal` binary."""
	override = os.environ.get('BROWSER_USE_TERMINAL_BINARY')
	if override:
		return [Path(override).expanduser()]

	home = Path.home()
	candidates: list[Path] = [
		home / '.browser-use-terminal' / 'packages' / 'standalone' / 'current' / 'bin' / 'browser-use-terminal',
		home / '.local' / 'bin' / 'browser-use-terminal',
		home / '.superset' / 'projects' / 'terminal' / 'target' / 'debug' / 'browser-use-terminal',
		Path.cwd() / 'target' / 'debug' / 'browser-use-terminal',
	]
	on_path = shutil.which('browser-use-terminal')
	if on_path:
		candidates.append(Path(on_path))
	return candidates


def find_browser_use_terminal_binary() -> Path:
	"""
	Return the path to `browser-use-terminal` (the *headless* sibling of `but`)
	or raise. This binary exposes subcommands `run-openai`, `run-anthropic`,
	`run-openrouter`, `followup`, `show`, `events`, etc. — i.e. everything
	`Agent.run(interactive=False)` needs.
	"""
	tried: list[Path] = []
	for candidate in _candidate_cli_paths():
		if candidate in tried:
			continue
		tried.append(candidate)
		if candidate.exists() and os.access(candidate, os.X_OK):
			return candidate
	raise ButNotInstalledError(tried)


def launch_terminal_ui(
	*,
	extra_args: list[str] | None = None,
	cwd: str | Path | None = None,
	check: bool = False,
) -> int:
	"""
	Hand the current terminal off to the `but` TUI.

	This is the "first-run magic moment" entrypoint. It replaces the current
	process group's foreground with `but` until the user quits the TUI. The
	return value is `but`'s exit code.

	Args:
		extra_args: Forwarded to `but` (e.g. `["--model", "gpt-5"]`).
		cwd: Working directory for the spawned `but`. Defaults to the caller's.
		check: If True, raise `subprocess.CalledProcessError` on non-zero exit.
	"""
	binary = find_but_binary()
	cmd = [str(binary)]
	if extra_args:
		cmd.extend(extra_args)

	# Inherit stdio so the TUI owns the terminal.
	completed = subprocess.run(
		cmd,
		cwd=str(cwd) if cwd else None,
		stdin=sys.stdin,
		stdout=sys.stdout,
		stderr=sys.stderr,
		check=check,
	)
	return completed.returncode
