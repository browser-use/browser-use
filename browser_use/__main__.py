"""Run the Browser Use CLI with ``python -m browser_use``."""

import sys

from browser_use.cli import main

if __name__ == '__main__':
	result = main()
	if result is not None:
		sys.exit(result)
