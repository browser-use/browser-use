"""Profile management command handlers.

Unified profile management that works with both local Chrome profiles and cloud profiles.
The behavior is determined by the browser mode (-b real or -b remote).
"""

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from browser_use.skill_cli.commands.utils import get_sdk_client

logger = logging.getLogger(__name__)


ProfileMode = Literal['real', 'remote']


class ProfileModeError(Exception):
	"""Raised when profile mode cannot be determined or is invalid."""

	pass


def get_profile_mode(args: argparse.Namespace) -> ProfileMode:
	"""Determine profile mode from -b flag or install config.

	Args:
		args: Parsed command-line arguments with browser attribute

	Returns:
		'real' for local Chrome profiles, 'remote' for cloud profiles

	Raises:
		ProfileModeError: If mode cannot be determined or chromium mode is used
	"""
	from browser_use.skill_cli.install_config import is_mode_available

	browser_mode = getattr(args, 'browser', None)

	# Explicit mode specified
	if browser_mode == 'real':
		return 'real'
	elif browser_mode == 'remote':
		return 'remote'
	elif browser_mode == 'chromium':
		raise ProfileModeError(
			'Profile commands are not supported in chromium mode.\n'
			'Use -b real for local Chrome profiles or -b remote for cloud profiles.'
		)

	# No explicit mode - try to infer from install config
	local_available = is_mode_available('real')
	remote_available = is_mode_available('remote')

	if local_available and not remote_available:
		return 'real'
	elif remote_available and not local_available:
		return 'remote'
	elif local_available and remote_available:
		raise ProfileModeError(
			'Both local and remote modes are available.\n'
			'Specify -b real for local Chrome profiles or -b remote for cloud profiles.'
		)
	else:
		raise ProfileModeError('No profile modes available. Run browser-use setup first.')


def handle_profile_command(args: argparse.Namespace) -> int:
	"""Handle profile subcommands.

	Routes to local or cloud implementation based on browser mode.
	"""
	command = args.profile_command

	# Commands that don't need mode inference
	if command is None:
		_print_usage()
		return 1

	# For sync command, we need special handling (local → cloud)
	if command == 'sync':
		return _handle_sync(args)

	# Get profile mode for all other commands
	try:
		mode = get_profile_mode(args)
	except ProfileModeError as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	# Route to appropriate handler
	if command == 'list':
		return _handle_list(args, mode)
	elif command == 'get':
		return _handle_get(args, mode)
	elif command == 'create':
		return _handle_create(args, mode)
	elif command == 'update':
		return _handle_update(args, mode)
	elif command == 'delete':
		return _handle_delete(args, mode)
	elif command == 'cookies':
		return _handle_cookies(args, mode)
	else:
		_print_usage()
		return 1


def _print_usage() -> None:
	"""Print profile command usage."""
	print('Usage: browser-use [-b real|remote] profile <command>')
	print()
	print('Commands:')
	print('  list              List profiles')
	print('  get <id>          Get profile details')
	print('  create            Create a new profile (remote only)')
	print('  update <id>       Update profile')
	print('  delete <id>       Delete profile')
	print('  cookies <id>      Show cookies by domain (real only)')
	print('  sync              Sync local profile to cloud')
	print()
	print('The -b flag determines which profile system to use:')
	print('  -b real           Local Chrome profiles')
	print('  -b remote         Cloud profiles (requires API key)')


# -----------------------------------------------------------------------------
# List profiles
# -----------------------------------------------------------------------------


def _handle_list(args: argparse.Namespace, mode: ProfileMode) -> int:
	"""Handle 'profile list' command."""
	if mode == 'real':
		return _list_local_profiles(args)
	else:
		return _list_cloud_profiles(args)


def _list_local_profiles(args: argparse.Namespace) -> int:
	"""List local Chrome profiles."""
	profiles = list_local_chrome_profiles()

	if getattr(args, 'json', False):
		print(json.dumps({'profiles': profiles}))
	else:
		if profiles:
			print('Local Chrome profiles:')
			for p in profiles:
				print(f'  {p["id"]}: {p["name"]} ({p["email"]})')
		else:
			print('No Chrome profiles found')

	return 0


def _list_cloud_profiles(args: argparse.Namespace) -> int:
	"""List cloud profiles."""
	from browser_use.skill_cli.api_key import APIKeyRequired

	page = getattr(args, 'page', 1)
	page_size = getattr(args, 'page_size', 20)

	try:
		client = get_sdk_client()
		response = client.profiles.list_profiles(page_number=page, page_size=page_size)
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		# Convert to dict for JSON output
		data = {
			'items': [{'id': p.id, 'name': p.name} for p in response.items],
			'totalItems': response.total_items,
			'pageNumber': response.page_number,
			'pageSize': response.page_size,
		}
		print(json.dumps(data))
	else:
		if response.items:
			print(f'Cloud profiles ({len(response.items)}/{response.total_items}):')
			for p in response.items:
				name = p.name or 'Unnamed'
				print(f'  {p.id}: {name}')
		else:
			print('No cloud profiles found')

	return 0


# -----------------------------------------------------------------------------
# Get profile
# -----------------------------------------------------------------------------


def _handle_get(args: argparse.Namespace, mode: ProfileMode) -> int:
	"""Handle 'profile get <id>' command."""
	if mode == 'real':
		return _get_local_profile(args)
	else:
		return _get_cloud_profile(args)


def _get_local_profile(args: argparse.Namespace) -> int:
	"""Get local Chrome profile details."""
	profiles = list_local_chrome_profiles()
	profile_id = args.id

	for p in profiles:
		if p['id'] == profile_id or p['name'] == profile_id:
			if getattr(args, 'json', False):
				print(json.dumps(p))
			else:
				print(f'Profile: {p["id"]}')
				print(f'  Name: {p["name"]}')
				print(f'  Email: {p["email"]}')
			return 0

	print(f'Error: Profile "{profile_id}" not found', file=sys.stderr)
	return 1


def _get_cloud_profile(args: argparse.Namespace) -> int:
	"""Get cloud profile details."""
	from browser_use.skill_cli.api_key import APIKeyRequired

	try:
		client = get_sdk_client()
		profile = client.profiles.get_profile(args.id)
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		data = {
			'id': profile.id,
			'name': profile.name,
			'createdAt': profile.created_at.isoformat() if profile.created_at else None,
			'updatedAt': profile.updated_at.isoformat() if profile.updated_at else None,
		}
		print(json.dumps(data))
	else:
		print(f'Profile: {profile.id}')
		if profile.name:
			print(f'  Name: {profile.name}')
		if profile.created_at:
			print(f'  Created: {profile.created_at.isoformat()}')
		if profile.updated_at:
			print(f'  Updated: {profile.updated_at.isoformat()}')

	return 0


# -----------------------------------------------------------------------------
# Create profile
# -----------------------------------------------------------------------------


def _handle_create(args: argparse.Namespace, mode: ProfileMode) -> int:
	"""Handle 'profile create' command."""
	if mode == 'real':
		print('Error: Cannot create local Chrome profiles via CLI.', file=sys.stderr)
		print('Use Chrome browser to create new profiles.', file=sys.stderr)
		return 1

	return _create_cloud_profile(args)


def _create_cloud_profile(args: argparse.Namespace) -> int:
	"""Create a cloud profile."""
	from browser_use.skill_cli.api_key import APIKeyRequired

	try:
		client = get_sdk_client()
		params = {}
		if args.name:
			params['name'] = args.name
		profile = client.profiles.create_profile(**params)
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps({'id': profile.id, 'name': profile.name}))
	else:
		print(f'Created profile: {profile.id}')

	return 0


# -----------------------------------------------------------------------------
# Update profile
# -----------------------------------------------------------------------------


def _handle_update(args: argparse.Namespace, mode: ProfileMode) -> int:
	"""Handle 'profile update <id>' command."""
	if mode == 'real':
		print('Error: Cannot update local Chrome profiles via CLI.', file=sys.stderr)
		print('Use Chrome browser settings to update profiles.', file=sys.stderr)
		return 1

	return _update_cloud_profile(args)


def _update_cloud_profile(args: argparse.Namespace) -> int:
	"""Update a cloud profile."""
	from browser_use.skill_cli.api_key import APIKeyRequired

	try:
		client = get_sdk_client()
		params = {}
		if args.name:
			params['name'] = args.name
		profile = client.profiles.update_profile(args.id, **params)
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps({'id': profile.id, 'name': profile.name}))
	else:
		print(f'Updated profile: {profile.id}')

	return 0


# -----------------------------------------------------------------------------
# Delete profile
# -----------------------------------------------------------------------------


def _handle_delete(args: argparse.Namespace, mode: ProfileMode) -> int:
	"""Handle 'profile delete <id>' command."""
	if mode == 'real':
		print('Error: Cannot delete local Chrome profiles via CLI.', file=sys.stderr)
		print('Use Chrome browser settings to remove profiles.', file=sys.stderr)
		return 1

	return _delete_cloud_profile(args)


def _delete_cloud_profile(args: argparse.Namespace) -> int:
	"""Delete a cloud profile."""
	from browser_use.skill_cli.api_key import APIKeyRequired

	try:
		client = get_sdk_client()
		client.profiles.delete_browser_profile(args.id)
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	if getattr(args, 'json', False):
		print(json.dumps({'deleted': args.id}))
	else:
		print(f'Deleted profile: {args.id}')

	return 0


# -----------------------------------------------------------------------------
# Cookies (local only)
# -----------------------------------------------------------------------------


def _handle_cookies(args: argparse.Namespace, mode: ProfileMode) -> int:
	"""Handle 'profile cookies <id>' command."""
	if mode == 'remote':
		print('Error: Cookie listing is only available for local Chrome profiles.', file=sys.stderr)
		print('Use -b real to access local profile cookies.', file=sys.stderr)
		return 1

	return _list_profile_cookies(args)


def _list_profile_cookies(args: argparse.Namespace) -> int:
	"""List cookies by domain in a local Chrome profile."""
	import asyncio

	from browser_use.skill_cli.sessions import create_browser_session

	# Get local profiles
	local_profiles = list_local_chrome_profiles()
	if not local_profiles:
		print('Error: No local Chrome profiles found', file=sys.stderr)
		return 1

	# Find the matching profile
	profile_arg = args.id
	selected_profile = None
	for p in local_profiles:
		if p['id'] == profile_arg or p['name'] == profile_arg:
			selected_profile = p
			break

	if not selected_profile:
		print(f'Error: Profile "{profile_arg}" not found', file=sys.stderr)
		print('Available profiles:')
		for p in local_profiles:
			print(f'  {p["id"]}: {p["name"]}')
		return 1

	profile_id = selected_profile['id']
	print(f'Loading cookies from: {selected_profile["name"]} ({selected_profile["email"]})')

	async def get_cookies():
		local_session = await create_browser_session('real', headed=False, profile=profile_id)
		await local_session.start()
		try:
			cookies = await local_session._cdp_get_cookies()
			return cookies
		finally:
			await local_session.kill()

	try:
		cookies = asyncio.get_event_loop().run_until_complete(get_cookies())
	except RuntimeError:
		cookies = asyncio.run(get_cookies())

	# Group cookies by domain
	domains: dict[str, int] = {}
	for cookie in cookies:
		domain = cookie.get('domain', 'unknown')
		# Normalize domain (remove leading dot)
		if domain.startswith('.'):
			domain = domain[1:]
		domains[domain] = domains.get(domain, 0) + 1

	# Sort by count descending
	sorted_domains = sorted(domains.items(), key=lambda x: x[1], reverse=True)

	if getattr(args, 'json', False):
		print(json.dumps({'domains': dict(sorted_domains), 'total_cookies': len(cookies)}))
	else:
		print(f'\nCookies by domain ({len(cookies)} total):')
		for domain, count in sorted_domains[:20]:  # Show top 20
			print(f'  {domain}: {count}')
		if len(sorted_domains) > 20:
			print(f'  ... and {len(sorted_domains) - 20} more domains')

		print('\nTo sync cookies to cloud:')
		print(f'  browser-use profile sync --from "{profile_id}" --domain <domain>')

	return 0


# -----------------------------------------------------------------------------
# Sync (local → cloud)
# -----------------------------------------------------------------------------


def _handle_sync(args: argparse.Namespace) -> int:
	"""Handle 'profile sync' command - sync local profile to cloud."""
	import asyncio

	from browser_use.skill_cli.api_key import APIKeyRequired
	from browser_use.skill_cli.sessions import create_browser_session

	# Get SDK client (validates API key)
	try:
		client = get_sdk_client()
	except APIKeyRequired as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1
	except Exception as e:
		print(f'Error: {e}', file=sys.stderr)
		return 1

	# Get local profiles
	local_profiles = list_local_chrome_profiles()
	if not local_profiles:
		print('Error: No local Chrome profiles found', file=sys.stderr)
		return 1

	# Determine which profile to sync
	from_profile = args.from_profile
	if not from_profile:
		# Show available profiles and ask user to specify
		print('Available local profiles:')
		for p in local_profiles:
			print(f'  {p["id"]}: {p["name"]} ({p["email"]})')
		print()
		print('Use --from to specify a profile:')
		print('  browser-use profile sync --from "Default"')
		print('  browser-use profile sync --from "Profile 1"')
		return 1

	# Find the matching profile
	selected_profile = None
	for p in local_profiles:
		if p['id'] == from_profile or p['name'] == from_profile:
			selected_profile = p
			break

	if not selected_profile:
		print(f'Error: Profile "{from_profile}" not found', file=sys.stderr)
		print('Available profiles:')
		for p in local_profiles:
			print(f'  {p["id"]}: {p["name"]}')
		return 1

	profile_id = selected_profile['id']
	profile_name = selected_profile['name']
	domain_filter = getattr(args, 'domain', None)

	# Generate cloud profile name
	cloud_name = args.name if args.name else None
	if not cloud_name:
		if domain_filter:
			cloud_name = f'Chrome - {profile_name} ({domain_filter})'
		else:
			cloud_name = f'Chrome - {profile_name}'

	# Use stderr for progress when JSON output is requested
	json_output = getattr(args, 'json', False)
	out = sys.stderr if json_output else sys.stdout

	def log(msg: str) -> None:
		print(msg, file=out)

	if domain_filter:
		log(f'Syncing: {profile_name} → {domain_filter} cookies only')
	else:
		log(f'Syncing: {profile_name} ({selected_profile["email"]})')

	# Step 1: Create cloud profile
	log('  Creating cloud profile...')
	try:
		cloud_profile = client.profiles.create_profile(name=cloud_name)
		cloud_profile_id = cloud_profile.id
	except Exception as e:
		print(f'Error creating cloud profile: {e}', file=sys.stderr)
		return 1

	log(f'  ✓ Created: {cloud_profile_id}')

	def cleanup_cloud_profile() -> None:
		"""Delete the cloud profile on failure."""
		try:
			client.profiles.delete_browser_profile(cloud_profile_id)
		except Exception:
			pass

	# Step 2: Export cookies from local profile
	async def sync_cookies():
		log('  Exporting cookies from local profile...')
		local_session = await create_browser_session('real', headed=False, profile=profile_id)
		await local_session.start()
		try:
			cookies = await local_session._cdp_get_cookies()
			if not cookies:
				return 0, 'No cookies found in local profile'

			# Filter by domain if specified
			if domain_filter:
				cookies = [c for c in cookies if domain_filter in c.get('domain', '')]

			if not cookies:
				return 0, f'No cookies found for domain: {domain_filter}'

			log(f'  ✓ Found {len(cookies)} cookies')

			# Save to temp file - convert Cookie objects to dicts for JSON serialization
			cookies_file = Path(tempfile.gettempdir()) / f'browser-use-sync-{cloud_profile_id}.json'
			cookies_data = [dict(c) if hasattr(c, '__dict__') else c for c in cookies]
			cookies_file.write_text(json.dumps(cookies_data))

			return len(cookies), str(cookies_file)
		finally:
			await local_session.kill()

	try:
		loop = asyncio.get_event_loop()
		if loop.is_running():
			import concurrent.futures

			with concurrent.futures.ThreadPoolExecutor() as executor:
				future = executor.submit(asyncio.run, sync_cookies())
				cookie_count, cookies_file = future.result()
		else:
			cookie_count, cookies_file = loop.run_until_complete(sync_cookies())
	except RuntimeError:
		cookie_count, cookies_file = asyncio.run(sync_cookies())

	if cookie_count == 0:
		log(f'  ⚠ {cookies_file}')  # cookies_file contains error message
		cleanup_cloud_profile()
		return 1

	# Step 3: Import cookies to cloud profile
	async def import_to_cloud():
		log('  Importing cookies to cloud profile...')
		remote_session = await create_browser_session('remote', headed=False, profile=cloud_profile_id)
		await remote_session.start()
		try:
			cookies = json.loads(Path(cookies_file).read_text())
			await remote_session._cdp_set_cookies(cookies)
			return True
		finally:
			await remote_session.kill()

	try:
		loop = asyncio.get_event_loop()
		if loop.is_running():
			import concurrent.futures

			with concurrent.futures.ThreadPoolExecutor() as executor:
				future = executor.submit(asyncio.run, import_to_cloud())
				future.result()
		else:
			loop.run_until_complete(import_to_cloud())
	except RuntimeError:
		asyncio.run(import_to_cloud())
	except Exception as e:
		log(f'  ⚠ Failed to import cookies: {e}')
		cleanup_cloud_profile()
		return 1

	# Cleanup temp file
	try:
		Path(cookies_file).unlink()
	except Exception:
		pass

	log('✓ Profile synced successfully!')
	log(f'  Cloud profile ID: {cloud_profile_id}')
	log('')
	log('To use this profile:')
	log(f'  browser-use -b remote --profile {cloud_profile_id} open <url>')

	if json_output:
		print(
			json.dumps(
				{
					'success': True,
					'profile_id': cloud_profile_id,
					'cookies_synced': cookie_count,
				}
			)
		)

	return 0


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def list_local_chrome_profiles() -> list[dict[str, Any]]:
	"""List local Chrome profiles from the Local State file."""
	import platform

	# Find Chrome Local State file
	system = platform.system()
	if system == 'Darwin':
		local_state = Path.home() / 'Library/Application Support/Google/Chrome/Local State'
	elif system == 'Windows':
		local_state = Path.home() / 'AppData/Local/Google/Chrome/User Data/Local State'
	else:
		local_state = Path.home() / '.config/google-chrome/Local State'

	if not local_state.exists():
		return []

	try:
		data = json.loads(local_state.read_text())
		profiles_info = data.get('profile', {}).get('info_cache', {})

		profiles = []
		for profile_id, info in profiles_info.items():
			profiles.append(
				{
					'id': profile_id,
					'name': info.get('name', profile_id),
					'email': info.get('user_name', ''),
				}
			)
		return profiles
	except Exception:
		return []
