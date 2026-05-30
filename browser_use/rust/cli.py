"""
`bu-terminal` console script — the new-user default.

Goal: someone who just `pip install browser-use`d should be able to type
`bu-terminal` and land in a working browser-using agent in seconds, with no
keys to configure (the TUI handles auth onboarding itself).

This script is intentionally thin: it locates the `but` binary, forwards
argv, and execs. Anything that needs to be smart belongs inside `but`.
"""

from __future__ import annotations

import sys

from browser_use.rust.runner import ButNotInstalledError, launch_terminal_ui


def main() -> None:
	"""Entry point for the `bu-terminal` console script."""
	# argv[0] is the script name; everything else is forwarded to `but`.
	extra_args = sys.argv[1:]
	try:
		code = launch_terminal_ui(extra_args=extra_args)
	except ButNotInstalledError as err:
		sys.stderr.write(f'{err}\n')
		sys.exit(127)
	sys.exit(code)


if __name__ == '__main__':
	main()
