"""Cloud session SDK wrappers and CLI handlers.

This module provides:
- SDK wrapper functions for the Browser-Use Cloud Session API
- CLI command handlers for `browser-use session <command>`
"""

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from browser_use_sdk.types.session_item_view import SessionItemView
from browser_use_sdk.types.session_view import SessionView
from browser_use_sdk.types.share_view import ShareView

from browser_use.skill_cli.commands.utils import format_duration, get_sdk_client

logger = logging.getLogger(__name__)


# ============ SDK Wrappers ============


def create_session(**kwargs: Any) -> SessionItemView:
	"""Create a cloud browser session.

	Args:
		profile_id: Cloud profile ID for persistent auth/cookies
		proxy_country: Proxy country code (us, gb, de, etc.)
		keep_alive: Keep session alive after task completes
		persist_memory: Share memory between tasks in session
		start_url: URL to navigate to when session starts
		screen_width: Browser screen width in pixels
		screen_height: Browser screen height in pixels

	Returns:
		SessionItemView with session details
	"""
	# Map our param names to SDK param names
	param_map = {
		'proxy_country': 'proxy_country_code',
		'screen_width': 'browser_screen_width',
		'screen_height': 'browser_screen_height',
	}
	params = {}
	for k, v in kwargs.items():
		if v is not None:
			params[param_map.get(k, k)] = v

	return get_sdk_client().sessions.create_session(**params)


def list_sessions(limit: int = 10, status: str | None = None) -> list[SessionItemView]:
	"""List cloud browser sessions."""
	client = get_sdk_client()
	response = client.sessions.list_sessions(
		page_size=min(limit, 100),
		filter_by=status,
	)
	return list(response.items) if response.items else []


def get_session(session_id: str) -> SessionView:
	"""Get details of a specific session."""
	return get_sdk_client().sessions.get_session(session_id)


def stop_session(session_id: str) -> SessionView:
	"""Stop a cloud session."""
	return get_sdk_client().sessions.update_session(session_id, action='stop')


def delete_session(session_id: str) -> None:
	"""Delete a cloud session and all its tasks."""
	get_sdk_client().sessions.delete_session(session_id)


def create_public_share(session_id: str) -> ShareView:
	"""Create a public share URL for a session."""
	return get_sdk_client().sessions.create_session_public_share(session_id)


def delete_public_share(session_id: str) -> None:
	"""Delete the public share for a session."""
	get_sdk_client().sessions.delete_session_public_share(session_id)


def stop_sessions_parallel(session_ids: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
	"""Stop multiple cloud sessions in parallel."""
	client = get_sdk_client()
	stopped: list[str] = []
	errors: list[dict[str, Any]] = []

	def stop_one(sid: str) -> tuple[str, str | None]:
		try:
			client.sessions.update_session(sid, action='stop')
			return (sid, None)
		except Exception as e:
			return (sid, str(e))

	with ThreadPoolExecutor(max_workers=10) as executor:
		futures = {executor.submit(stop_one, sid): sid for sid in session_ids}
		for future in as_completed(futures):
			sid, error = future.result()
			if error:
				errors.append({'id': sid, 'error': error})
			else:
				stopped.append(sid)

	return stopped, errors


# ============ CLI Handlers ============


def handle_session_command(args: argparse.Namespace) -> int:
	"""Handle session subcommands.

	Session commands manage cloud sessions and always require the cloud API.

	Args:
		args: Parsed command-line arguments

	Returns:
		Exit code (0 for success, 1 for error)
	"""
	from browser_use.skill_cli.api_key import APIKeyRequired, require_api_key
	from browser_use.skill_cli.install_config import is_mode_available

	# Check if remote mode is available
	if not is_mode_available('remote'):
		print(
			'Error: Session management requires remote mode.\n'
			'Remote mode is not installed. Reinstall to enable:\n'
			'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --remote-only\n'
			'  curl -fsSL https://browser-use.com/cli/install.sh | bash -s -- --full',
			file=sys.stderr,
		)
		return 1

	# Check API key
	try:
		require_api_key('Cloud sessions')
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if args.session_command == 'list':
		return _handle_list(args)
	elif args.session_command == 'get':
		return _handle_get(args)
	elif args.session_command == 'stop':
		return _handle_stop(args)
	elif args.session_command == 'create':
		return _handle_create(args)
	elif args.session_command == 'share':
		return _handle_share(args)
	else:
		print('Usage: browser-use session <command>')
		print('Commands: list, get <id>, stop <id>, create, share <id>')
		return 1


# ============ CLI Helper Functions ============


def _session_to_dict(session: Any) -> dict[str, Any]:
	"""Convert SDK session object to dict for JSON output."""
	return {
		'id': session.id,
		'status': session.status,
		'liveUrl': session.live_url,
		'startedAt': session.started_at.isoformat() if session.started_at else None,
		'finishedAt': session.finished_at.isoformat() if session.finished_at else None,
		'keepAlive': session.keep_alive,
		'persistMemory': getattr(session, 'persist_memory', None),
		'proxyCost': session.proxy_cost,
		'publicShareUrl': getattr(session, 'public_share_url', None),
	}


def _handle_list(args: argparse.Namespace) -> int:
	"""Handle 'session list' command."""
	try:
		status_filter = getattr(args, 'status', None)
		sessions = list_sessions(limit=args.limit, status=status_filter)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps([_session_to_dict(s) for s in sessions]))
	else:
		if not sessions:
			status_msg = f' with status "{status_filter}"' if status_filter else ''
			print(f'No sessions found{status_msg}')
		else:
			header = f'Sessions ({len(sessions)})'
			if status_filter:
				header = f'{status_filter.capitalize()} sessions ({len(sessions)})'
			print(f'{header}:')
			for s in sessions:
				session_id = s.id or 'unknown'
				status = s.status or 'unknown'
				live_url = s.live_url
				started_at = s.started_at
				finished_at = s.finished_at
				keep_alive = '🔄' if s.keep_alive else ''

				# Status emoji
				status_emoji = {
					'active': '🟢',
					'stopped': '⏹️',
				}.get(status, '❓')

				# Truncate ID for display
				short_id = session_id[:8] + '...' if len(session_id) > 8 else session_id

				# Build line with duration
				duration = format_duration(started_at, finished_at)
				line = f'  {status_emoji} {short_id} [{status}]'
				if duration:
					line += f' {duration}'
				if keep_alive:
					line += f' {keep_alive}'
				if live_url and status == 'active':
					line += f'\n      live: {live_url}'
				print(line)

	return 0


def _handle_get(args: argparse.Namespace) -> int:
	"""Handle 'session get <session_id>' command."""
	try:
		session = get_session(args.session_id)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps(_session_to_dict(session)))
	else:
		session_id = session.id or args.session_id
		status = session.status or 'unknown'
		live_url = session.live_url
		started_at = session.started_at
		finished_at = session.finished_at
		keep_alive = session.keep_alive
		proxy_cost = session.proxy_cost
		public_share_url = getattr(session, 'public_share_url', None)

		# Status emoji
		status_emoji = {
			'active': '🟢',
			'stopped': '⏹️',
		}.get(status, '❓')

		# Build header with duration
		duration = format_duration(started_at, finished_at)
		header_parts = [f'{status_emoji} {session_id[:8]}... [{status}]']
		if duration:
			header_parts.append(duration)
		if proxy_cost:
			# Format proxy cost to 2 decimal places
			try:
				cost_val = float(proxy_cost)
				header_parts.append(f'${cost_val:.2f}')
			except (ValueError, TypeError):
				header_parts.append(f'${proxy_cost}')
		print(' '.join(header_parts))

		if keep_alive:
			print('  Keep Alive: Yes')
		if live_url:
			print(f'  Live URL: {live_url}')
		if public_share_url:
			print(f'  Public Share: {public_share_url}')

	return 0


def _handle_stop(args: argparse.Namespace) -> int:
	"""Handle 'session stop <session_id>' command."""
	# Handle --all flag
	if getattr(args, 'all', False):
		return _handle_stop_all(args)

	try:
		stop_session(args.session_id)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps({'stopped': args.session_id}))
	else:
		print(f'Stopped session: {args.session_id}')

	return 0


def _handle_stop_all(args: argparse.Namespace) -> int:
	"""Handle 'session stop --all' command."""
	try:
		# Get all active sessions
		sessions = list_sessions(limit=100, status='active')
	except Exception as e:
		print(f'Error listing sessions: {e}', file=sys.stderr)
		return 1

	if not sessions:
		print('No active sessions to stop')
		return 0

	# Extract session IDs
	session_ids = [s.id for s in sessions if s.id]

	if not session_ids:
		print('No active sessions to stop')
		return 0

	# Stop all sessions in parallel
	stopped, errors = stop_sessions_parallel(session_ids)

	if getattr(args, 'json', False):
		print(json.dumps({'stopped': stopped, 'errors': errors}))
	else:
		if stopped:
			print(f'Stopped {len(stopped)} session(s):')
			for sid in stopped:
				print(f'  ✓ {sid[:8]}...')
		if errors:
			print(f'Failed to stop {len(errors)} session(s):')
			for err in errors:
				print(f'  ✗ {err["id"][:8]}...: {err["error"]}')

	return 0 if not errors else 1


def _handle_create(args: argparse.Namespace) -> int:
	"""Handle 'session create' command."""
	# Parse screen size if provided
	screen_width = None
	screen_height = None
	if hasattr(args, 'screen_size') and args.screen_size:
		try:
			w, h = args.screen_size.lower().split('x')
			screen_width = int(w)
			screen_height = int(h)
		except ValueError:
			print('Error: Invalid screen size format. Use WxH (e.g., 1920x1080)', file=sys.stderr)
			return 1

	try:
		session = create_session(
			profile_id=getattr(args, 'profile', None),
			proxy_country=getattr(args, 'proxy_country', None),
			keep_alive=getattr(args, 'keep_alive', None),
			persist_memory=getattr(args, 'persist_memory', None),
			start_url=getattr(args, 'start_url', None),
			screen_width=screen_width,
			screen_height=screen_height,
		)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps(_session_to_dict(session)))
	else:
		print(f'Created session: {session.id}')
		if session.live_url:
			print(f'  Live URL: {session.live_url}')

	return 0


def _handle_share(args: argparse.Namespace) -> int:
	"""Handle 'session share <session_id>' command."""
	session_id = args.session_id

	# Delete share if requested
	if getattr(args, 'delete', False):
		try:
			delete_public_share(session_id)
		except Exception as e:
			print(f'Error: {e}', file=sys.stderr)
			return 1

		if getattr(args, 'json', False):
			print(json.dumps({'deleted': session_id}))
		else:
			print(f'Deleted public share for session: {session_id}')
		return 0

	# Create share
	try:
		share = create_public_share(session_id)
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(
			json.dumps(
				{
					'sessionId': session_id,
					'url': share.share_url,
					'shareToken': share.share_token,
					'viewCount': share.view_count,
				}
			)
		)
	else:
		print(f'Public share created for session: {session_id}')
		if share.share_url:
			print(f'  URL: {share.share_url}')

	return 0
