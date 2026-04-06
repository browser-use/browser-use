"""Cloud API command — generic REST passthrough to Browser-Use Cloud.

Stdlib only. No async, no SDK, no heavy imports.

Usage:
  browser-use cloud login <api-key>
  browser-use cloud logout
  browser-use cloud v2 GET /browsers
  browser-use cloud v2 POST /tasks '{"task":"...","url":"https://..."}'
  browser-use cloud v2 poll <task-id>
  browser-use cloud v2 --help
"""

import json
import os
import sys
import time
import typing
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = 'https://api.browser-use.com'
_AUTH_HEADER = 'X-Browser-Use-API-Key'


def _get_base() -> str:
	"""Get the API host URL. All paths are appended by callers."""
	return os.environ.get('BROWSER_USE_CLOUD_BASE_URL', _DEFAULT_BASE_URL).rstrip('/')


def _base_url(version: str) -> str:
	"""Get versioned API URL: {base}/api/{version}"""
	per_version = os.environ.get(f'BROWSER_USE_CLOUD_BASE_URL_{version.upper()}')
	if per_version:
		return per_version
	return f'{_get_base()}/api/{version}'


def _spec_url(version: str) -> str:
	per_version = os.environ.get(f'BROWSER_USE_OPENAPI_SPEC_URL_{version.upper()}')
	if per_version:
		return per_version
	return f'{_get_base()}/api/{version}/openapi.json'


# ---------------------------------------------------------------------------
# API key persistence
# ---------------------------------------------------------------------------


def _get_config_path() -> Path:
	from browser_use.skill_cli.utils import get_config_path

	return get_config_path()


def _read_config() -> dict:
	from browser_use.skill_cli.config import read_config

	return read_config()


def _write_config(data: dict) -> None:
	from browser_use.skill_cli.config import write_config

	write_config(data)


def _get_api_key_or_none() -> str | None:
	"""Return API key from CLI config file, or None if not found."""
	from browser_use.skill_cli.config import get_config_value

	val = get_config_value('api_key')
	return str(val) if val is not None else None


def _get_api_key() -> str:
	"""Return API key from config file. Exits with error if missing."""
	key = _get_api_key_or_none()
	if key:
		return key

	print('Error: No API key found.', file=sys.stderr)
	if os.environ.get('BROWSER_USE_API_KEY'):
		print('  Note: BROWSER_USE_API_KEY env var is set but not used by the CLI.', file=sys.stderr)
		print('  Run: browser-use config set api_key "$BROWSER_USE_API_KEY"', file=sys.stderr)
	else:
		print('Already have an account? Get a key at: https://cloud.browser-use.com/settings?tab=api-keys&new=1', file=sys.stderr)
		print('  Then run: browser-use cloud login <key>', file=sys.stderr)
		print('No account? Run: browser-use cloud signup', file=sys.stderr)
		print('  This creates an agent account you can claim later with: browser-use cloud signup --claim', file=sys.stderr)
	sys.exit(1)


def _create_cloud_profile_inner(api_key: str) -> str:
	"""Create a new cloud profile and save to config. Returns profile ID.

	Raises RuntimeError on failure — safe to call from daemon context.
	"""
	body = json.dumps({'name': 'Browser Use CLI'}).encode()
	status, resp = _http_request('POST', f'{_base_url("v2")}/profiles', body, api_key)
	if status >= 400:
		raise RuntimeError(f'Error creating cloud profile: HTTP {status} — {resp}')

	try:
		data = json.loads(resp)
		new_id = data['id']
	except (json.JSONDecodeError, KeyError, TypeError):
		raise RuntimeError(f'Unexpected response from cloud API: {resp}')

	config = _read_config()
	config['cloud_connect_profile_id'] = new_id
	_write_config(config)
	return new_id


def _create_cloud_profile() -> str:
	"""Create a new cloud profile and save to config. Returns profile ID.

	CLI entry point — exits on error.
	"""
	api_key = _get_api_key()
	try:
		return _create_cloud_profile_inner(api_key)
	except RuntimeError as e:
		print(str(e), file=sys.stderr)
		sys.exit(1)


def _get_or_create_cloud_profile() -> str:
	"""Return cloud profile ID from config, creating one if missing. No validation HTTP call."""
	config = _read_config()
	profile_id = config.get('cloud_connect_profile_id')
	if profile_id:
		return profile_id
	return _create_cloud_profile()


def _get_cloud_connect_proxy() -> str | None:
	"""Return the cloud connect proxy country code from config."""
	from browser_use.skill_cli.config import get_config_value

	val = get_config_value('cloud_connect_proxy')
	return str(val) if val is not None else None


def _get_cloud_connect_timeout() -> int | None:
	"""Return the cloud connect timeout (minutes) from config."""
	from browser_use.skill_cli.config import get_config_value

	val = get_config_value('cloud_connect_timeout')
	return int(val) if val is not None else None


def _save_api_key(key: str) -> None:
	config = _read_config()
	config['api_key'] = key
	_write_config(config)


def _remove_api_key() -> bool:
	config = _read_config()
	if 'api_key' not in config:
		return False
	del config['api_key']
	path = _get_config_path()
	if config:
		_write_config(config)
	else:
		path.unlink(missing_ok=True)
	return True


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_request(method: str, url: str, body: bytes | None, api_key: str, timeout: float = 30.0) -> tuple[int, bytes]:
	"""Fire an HTTP request. Returns (status_code, response_body)."""
	headers = {_AUTH_HEADER: api_key}
	if body is not None:
		headers['Content-Type'] = 'application/json'

	req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
	try:
		with urllib.request.urlopen(req, timeout=timeout) as resp:
			return resp.status, resp.read()
	except urllib.error.HTTPError as e:
		return e.code, e.read()
	except urllib.error.URLError as e:
		print(f'Error: {e.reason}', file=sys.stderr)
		sys.exit(1)


def _print_json(data: bytes, file: typing.TextIO | None = None) -> None:
	"""Pretty-print JSON, raw fallback."""
	out = file or sys.stdout
	try:
		parsed = json.loads(data)
		print(json.dumps(parsed, indent=2), file=out)
	except (json.JSONDecodeError, ValueError):
		buf = out.buffer if hasattr(out, 'buffer') else sys.stdout.buffer
		buf.write(data)
		buf.write(b'\n')
		buf.flush()


# ---------------------------------------------------------------------------
# OpenAPI help
# ---------------------------------------------------------------------------


def _fetch_spec(version: str) -> bytes | None:
	url = _spec_url(version)
	try:
		req = urllib.request.Request(url)
		with urllib.request.urlopen(req, timeout=5) as resp:
			return resp.read()
	except Exception:
		return None


def _example_value(prop: dict, schemas: dict) -> object:
	"""Generate a placeholder value for an OpenAPI property."""
	if '$ref' in prop:
		ref_name = prop['$ref'].rsplit('/', 1)[-1]
		if ref_name in schemas:
			return _generate_body_example_dict(ref_name, schemas)
		return {}

	t = prop.get('type', 'string')
	fmt = prop.get('format', '')
	enum = prop.get('enum')

	if enum:
		return enum[0]
	if t == 'string':
		if fmt == 'uri' or fmt == 'url':
			return 'https://example.com'
		if fmt == 'date-time':
			return '2025-01-01T00:00:00Z'
		if 'email' in fmt:
			return 'user@example.com'
		return '...'
	if t == 'integer':
		return 0
	if t == 'number':
		return 0.0
	if t == 'boolean':
		return False
	if t == 'array':
		items = prop.get('items', {})
		return [_example_value(items, schemas)]
	if t == 'object':
		props = prop.get('properties', {})
		return {k: _example_value(v, schemas) for k, v in props.items()}
	return '...'


def _generate_body_example_dict(ref_name: str, schemas: dict) -> dict:
	"""Build a compact example dict from a $ref schema."""
	schema = schemas.get(ref_name, {})
	props = schema.get('properties', {})
	required = set(schema.get('required', []))

	result = {}
	# Required fields first, then sorted optional
	for key in sorted(props, key=lambda k: (k not in required, k)):
		result[key] = _example_value(props[key], schemas)
	return result


def _generate_body_example(ref: str, schemas: dict) -> str:
	"""Return compact JSON string for a $ref."""
	ref_name = ref.rsplit('/', 1)[-1]
	obj = _generate_body_example_dict(ref_name, schemas)
	return json.dumps(obj, separators=(',', ':'))


def _find_body_ref(spec: dict, method: str, path: str) -> str | None:
	"""Find the $ref for request body of a given method+path in spec."""
	paths = spec.get('paths', {})
	path_obj = paths.get(path, {})
	method_obj = path_obj.get(method.lower(), {})
	body = method_obj.get('requestBody', {})
	content = body.get('content', {})
	json_media = content.get('application/json', {})
	schema = json_media.get('schema', {})
	return schema.get('$ref')


def _match_path(spec_path: str, req_path: str) -> bool:
	"""Match an OpenAPI template path against a concrete path.

	E.g. /tasks/{task_id} matches /tasks/abc123
	"""
	spec_parts = spec_path.strip('/').split('/')
	req_parts = req_path.strip('/').split('/')
	if len(spec_parts) != len(req_parts):
		return False
	for sp, rp in zip(spec_parts, req_parts):
		if sp.startswith('{') and sp.endswith('}'):
			continue
		if sp != rp:
			return False
	return True


def _find_body_example(spec: dict, method: str, path: str) -> str | None:
	"""Find a body example for the given method+path, using template matching."""
	schemas = spec.get('components', {}).get('schemas', {})
	paths = spec.get('paths', {})

	for spec_path in paths:
		if _match_path(spec_path, path):
			ref = _find_body_ref(spec, method, spec_path)
			if ref:
				return _generate_body_example(ref, schemas)
	return None


def _format_openapi_help(spec_data: bytes) -> str:
	"""Parse OpenAPI spec and render grouped endpoints."""
	try:
		spec = json.loads(spec_data)
	except (json.JSONDecodeError, ValueError):
		return ''

	paths = spec.get('paths', {})
	schemas = spec.get('components', {}).get('schemas', {})
	info = spec.get('info', {})

	lines: list[str] = []
	title = info.get('title', 'API')
	version = info.get('version', '')
	lines.append(f'{title} {version}'.strip())
	lines.append('')

	# Group by tag
	groups: dict[str, list[str]] = {}
	for path, methods in sorted(paths.items()):
		for method, details in sorted(methods.items()):
			if method in ('parameters', 'summary', 'description'):
				continue
			tags = details.get('tags', ['Other'])
			tag = tags[0] if tags else 'Other'
			summary = details.get('summary', '')

			# Build endpoint line
			parts = [f'  {method.upper():6s} {path}']
			if summary:
				parts.append(f'  # {summary}')

			# Parameters
			params = details.get('parameters', [])
			param_strs = []
			for p in params:
				name = p.get('name', '')
				required = p.get('required', False)
				marker = '*' if required else ''
				param_strs.append(f'{name}{marker}')
			if param_strs:
				parts.append(f'  params: {", ".join(param_strs)}')

			# Body example
			body_ref = _find_body_ref(spec, method, path)
			if body_ref:
				example = _generate_body_example(body_ref, schemas)
				parts.append(f"  body: '{example}'")

			groups.setdefault(tag, []).append('\n'.join(parts) if len(parts) > 1 else parts[0])

	for tag, endpoints in sorted(groups.items()):
		lines.append(f'[{tag}]')
		for ep in endpoints:
			lines.append(ep)
		lines.append('')

	return '\n'.join(lines)


def _static_help(version: str) -> str:
	"""Fallback help when OpenAPI spec is unavailable."""
	return f"""Browser-Use Cloud API {version}

Usage:
  browser-use cloud {version} <METHOD> <path> [body]
  browser-use cloud {version} poll <task-id>

Examples:
  browser-use cloud {version} GET /browsers
  browser-use cloud {version} POST /tasks '{{"task":"Search for AI news","url":"https://google.com"}}'
  browser-use cloud {version} GET /tasks/<task-id>
  browser-use cloud {version} poll <task-id>

(Could not fetch OpenAPI spec for live endpoint listing)
"""


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _cloud_login(argv: list[str]) -> int:
	if not argv:
		print('Usage: browser-use cloud login <api-key>', file=sys.stderr)
		return 1

	key = argv[0]
	_save_api_key(key)
	print('API key saved')
	return 0


def _cloud_logout() -> int:
	if _remove_api_key():
		print('API key removed')
	else:
		print('No API key to remove')
	return 0


def _cloud_rest(argv: list[str], version: str) -> int:
	"""Generic REST passthrough."""
	if len(argv) < 2:
		print(f'Usage: browser-use cloud {version} <METHOD> <path> [body]', file=sys.stderr)
		return 1

	method = argv[0].upper()
	path = argv[1]
	body_str = argv[2] if len(argv) > 2 else None

	# Normalize path
	if not path.startswith('/'):
		path = '/' + path

	url = f'{_base_url(version)}{path}'
	api_key = _get_api_key()

	body = body_str.encode() if body_str else None
	status, resp_body = _http_request(method, url, body, api_key)

	if 400 <= status < 500:
		print(f'HTTP {status}', file=sys.stderr)
		_print_json(resp_body, file=sys.stderr)

		# Try to suggest correct body from spec
		spec_data = _fetch_spec(version)
		if spec_data:
			try:
				spec = json.loads(spec_data)
				example = _find_body_example(spec, method, path)
				if example:
					print(f"\nExpected body: '{example}'", file=sys.stderr)
			except (json.JSONDecodeError, ValueError):
				pass
		return 2

	if status >= 500:
		print(f'HTTP {status}', file=sys.stderr)
		_print_json(resp_body, file=sys.stderr)
		return 1

	_print_json(resp_body)
	return 0


def _cloud_poll(argv: list[str], version: str) -> int:
	"""Poll GET /tasks/<id> until done."""
	if not argv:
		print(f'Usage: browser-use cloud {version} poll <task-id>', file=sys.stderr)
		return 1

	task_id = argv[0]
	url = f'{_base_url(version)}/tasks/{task_id}'
	api_key = _get_api_key()

	while True:
		status_code, resp_body = _http_request('GET', url, None, api_key)

		if status_code >= 400:
			print(f'\nHTTP {status_code}', file=sys.stderr)
			_print_json(resp_body, file=sys.stderr)
			return 2

		try:
			data = json.loads(resp_body)
		except (json.JSONDecodeError, ValueError):
			print('\nError: invalid JSON response', file=sys.stderr)
			return 1

		task_status = data.get('status', 'unknown')
		cost = data.get('cost', 0)
		print(f'\rstatus: {task_status}  cost: ${cost:.4f}', end='', file=sys.stderr, flush=True)

		if task_status == 'finished':
			print('', file=sys.stderr)  # newline
			_print_json(resp_body)
			return 0

		if task_status == 'failed':
			print('', file=sys.stderr)
			_print_json(resp_body, file=sys.stderr)
			return 2

		time.sleep(2)


def _cloud_help(version: str) -> int:
	"""Show OpenAPI-driven help for a version."""
	spec_data = _fetch_spec(version)
	if spec_data:
		formatted = _format_openapi_help(spec_data)
		if formatted:
			print(formatted)
			return 0

	print(_static_help(version))
	return 0


def _cloud_versioned(argv: list[str], version: str) -> int:
	"""Route versioned subcommands: poll, help, or REST passthrough."""
	if not argv:
		return _cloud_help(version)

	first = argv[0]

	if first in ('--help', 'help', '-h'):
		return _cloud_help(version)

	if first == 'poll':
		return _cloud_poll(argv[1:], version)

	# REST passthrough: METHOD path [body]
	return _cloud_rest(argv, version)


# ---------------------------------------------------------------------------
# Signup (agent self-registration)
# ---------------------------------------------------------------------------


def _signup_challenge() -> int:
	"""Request a signup challenge."""
	if _get_api_key_or_none():
		print('You already have an API key configured.', file=sys.stderr)
		print('Run `browser-use cloud signup --claim` to claim your account.', file=sys.stderr)
		return 1

	body = json.dumps({}).encode()
	status, resp = _http_request('POST', f'{_get_base()}/cloud/signup', body, api_key='')
	if status >= 400:
		print(f'Error: HTTP {status}', file=sys.stderr)
		_print_json(resp, file=sys.stderr)
		return 1

	try:
		data = json.loads(resp)
	except (json.JSONDecodeError, ValueError):
		print('Error: invalid response', file=sys.stderr)
		return 1

	print(f'Challenge ID: {data["challenge_id"]}')
	print(f'Challenge: {data["challenge_text"]}')
	print()
	print('Verify to create your agent account:')
	print('  browser-use cloud signup --verify <challenge-id> <answer>')
	return 0


def _signup_verify(challenge_id: str, answer: str) -> int:
	"""Verify a signup challenge and save the API key."""
	if _get_api_key_or_none():
		print('You already have an API key configured.', file=sys.stderr)
		print('Run `browser-use cloud signup --claim` to claim your account.', file=sys.stderr)
		return 1

	body = json.dumps({'challenge_id': challenge_id, 'answer': answer}).encode()
	status, resp = _http_request('POST', f'{_get_base()}/cloud/signup/verify', body, api_key='')
	if status >= 400:
		print(f'Error: HTTP {status}', file=sys.stderr)
		_print_json(resp, file=sys.stderr)
		return 1

	try:
		data = json.loads(resp)
	except (json.JSONDecodeError, ValueError):
		print('Error: invalid response', file=sys.stderr)
		return 1

	_save_api_key(data['api_key'])
	print('API key saved')
	return 0


def _signup_claim() -> int:
	"""Generate a claim URL for the current API key."""
	api_key = _get_api_key()
	status, resp = _http_request('POST', f'{_get_base()}/cloud/signup/claim', None, api_key)
	if status >= 400:
		print(f'Error: HTTP {status}', file=sys.stderr)
		_print_json(resp, file=sys.stderr)
		return 1

	try:
		data = json.loads(resp)
	except (json.JSONDecodeError, ValueError):
		print('Error: invalid response', file=sys.stderr)
		return 1

	print(f'Claim URL: {data["claim_url"]}')
	print('Share this URL with a human to claim ownership of this account.')
	return 0


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


def handle_cloud_command(argv: list[str]) -> int:
	"""Main dispatcher for `browser-use cloud ...`."""
	if not argv:
		_print_cloud_usage()
		return 1

	subcmd = argv[0]

	if subcmd == 'login':
		return _cloud_login(argv[1:])

	if subcmd == 'logout':
		return _cloud_logout()

	if subcmd in ('v2', 'v3'):
		return _cloud_versioned(argv[1:], subcmd)

	if subcmd == 'signup':
		if '--verify' in argv:
			idx = argv.index('--verify')
			if idx + 2 >= len(argv):
				print('Usage: browser-use cloud signup --verify <challenge-id> <answer>', file=sys.stderr)
				return 1
			return _signup_verify(argv[idx + 1], argv[idx + 2])
		if '--claim' in argv:
			return _signup_claim()
		return _signup_challenge()

	if subcmd == 'connect':
		# Normally intercepted by main.py before reaching here
		print('Error: cloud connect must be run via the main CLI (browser-use cloud connect)', file=sys.stderr)
		return 1

	if subcmd in ('--help', 'help', '-h'):
		_print_cloud_usage()
		return 0

	print(f'Unknown cloud subcommand: {subcmd}', file=sys.stderr)
	_print_cloud_usage()
	return 1


def _print_cloud_usage() -> None:
	print('Usage: browser-use cloud <command>')
	print()
	print('Commands:')
	print('  connect                           Provision cloud browser and connect')
	print('  signup                            Create an agent account (challenge-response)')
	print('  signup --verify <id> <answer>     Verify challenge and save API key')
	print('  signup --claim                    Generate URL to claim your agent account')
	print('  login <api-key>                   Save API key')
	print('  logout                            Remove API key')
	print('  v2 <METHOD> <path> [body]         REST passthrough (API v2)')
	print('  v3 <METHOD> <path> [body]         REST passthrough (API v3)')
	print('  v2 poll <task-id>                 Poll task until done')
	print('  v2 --help                         Show API v2 endpoints')
	print('  v3 --help                         Show API v3 endpoints')
	print()
	print('Examples:')
	print('  browser-use cloud login sk-abc123...')
	print('  browser-use cloud v2 GET /browsers')
	print('  browser-use cloud v2 POST /tasks \'{"task":"...","url":"https://..."}\'')
	print('  browser-use cloud v2 poll <task-id>')
