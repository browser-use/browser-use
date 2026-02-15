"""Session management command handlers."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from browser_use.skill_cli.sessions import SessionRegistry

logger = logging.getLogger(__name__)

COMMANDS = {'sessions', 'close'}


async def handle(action: str, session_name: str, registry: 'SessionRegistry', params: dict[str, Any]) -> Any:
	"""Handle session management command."""
	if action == 'sessions':
		sessions = registry.list_sessions()
		return {
			'sessions': sessions,
			'count': len(sessions),
		}

	elif action == 'close':
		if params.get('all'):
			# Close all sessions and signal shutdown
			sessions = registry.list_sessions()
			await registry.close_all()
			return {
				'closed': [s['name'] for s in sessions],
				'count': len(sessions),
				'_shutdown': True,  # Signal to stop server
			}
		else:
			# Close this server's session and shutdown
			await registry.close_session(session_name)
			return {'closed': session_name, '_shutdown': True}

	raise ValueError(f'Unknown session action: {action}')
