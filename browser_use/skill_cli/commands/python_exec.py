"""Python execution command handler."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from browser_use.skill_cli.sessions import SessionInfo

logger = logging.getLogger(__name__)


async def handle(session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle python command.

	Supports:
	- python "<code>" - Execute Python code
	- python --file script.py - Execute Python file
	- python --reset - Reset namespace
	- python --vars - Show defined variables
	"""
	python_session = session.python_session
	browser_session = session.browser_session

	# Handle --reset
	if params.get('reset'):
		python_session.reset()
		return {'reset': True, 'message': 'Python namespace cleared'}

	# Handle --vars
	if params.get('vars'):
		variables = python_session.get_variables()
		return {'variables': variables, 'count': len(variables)}

	# Get code to execute
	code = params.get('code')

	# Handle --file
	if params.get('file'):
		file_path = Path(params['file'])
		if not file_path.exists():
			return {'success': False, 'error': f'File not found: {file_path}'}
		if file_path.is_dir():
			return {'success': False, 'error': f'Path is a directory, not a file: {file_path}'}
		code = file_path.read_text()

	if not code:
		return {'success': False, 'error': 'No code provided. Use: python "<code>" or --file script.py'}

	# Execute code in a thread pool so browser operations can schedule back to the event loop
	loop = asyncio.get_running_loop()
	result = await loop.run_in_executor(None, python_session.execute, code, browser_session, loop)

	if result.success:
		# Return raw text output for clean display
		return {'_raw_text': result.output} if result.output else {}
	else:
		return {'error': result.error or 'Unknown error'}
