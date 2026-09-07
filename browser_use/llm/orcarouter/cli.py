"""CLI commands for OrcaRouter authentication."""

from __future__ import annotations

import argparse
import asyncio
import sys

from browser_use.llm.orcarouter.auth import OrcaRouterAuthError, OrcaRouterCredentialStore, OrcaRouterPKCEClient


def _parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog='browser-use orcarouter',
		description='Connect Browser Use to OrcaRouter with an existing API key or PKCE login.',
	)
	subparsers = parser.add_subparsers(dest='command', required=True)

	login = subparsers.add_parser('login', help='Connect an OrcaRouter account with PKCE')
	login.add_argument('--no-open', action='store_true', help='Print the authorization URL without opening a browser')
	login.add_argument('--timeout', type=float, default=300, help='Seconds to wait for browser authorization (default: 300)')
	login.add_argument('--auth-base-url', help=argparse.SUPPRESS)

	subparsers.add_parser('status', help='Show PKCE connection status without printing the key')
	subparsers.add_parser('logout', help='Remove the stored PKCE credential')
	return parser


async def _login(args: argparse.Namespace) -> int:
	if args.timeout <= 0:
		print('browser-use orcarouter: --timeout must be greater than zero', file=sys.stderr)
		return 2

	client = OrcaRouterPKCEClient(auth_base_url=args.auth_base_url)

	def show_authorization_url(url: str) -> None:
		print('Authorize Browser Use with OrcaRouter:')
		print(url, flush=True)
		if args.no_open:
			print('Waiting for authorization in that browser tab...', flush=True)

	try:
		credential = await client.login(
			open_browser=not args.no_open,
			on_authorization_url=show_authorization_url,
			timeout=args.timeout,
		)
	except OrcaRouterAuthError as exc:
		print(f'OrcaRouter login failed: {exc}', file=sys.stderr)
		return 1

	print(f'OrcaRouter connected (scope: {credential.scope}).')
	return 0


def _status() -> int:
	try:
		credential = OrcaRouterCredentialStore().load()
	except OrcaRouterAuthError as exc:
		print(f'OrcaRouter status unavailable: {exc}', file=sys.stderr)
		return 1
	if credential is None:
		print('OrcaRouter PKCE is not connected. Run `browser-use orcarouter login`.')
		return 1
	if credential.needs_reauth:
		print('OrcaRouter PKCE needs reauthorization. Run `browser-use orcarouter login`.')
		return 1
	print(f'OrcaRouter PKCE is connected (scope: {credential.scope}).')
	return 0


def _logout() -> int:
	try:
		removed = OrcaRouterCredentialStore().clear()
	except OrcaRouterAuthError as exc:
		print(f'OrcaRouter logout failed: {exc}', file=sys.stderr)
		return 1
	if removed:
		print('Removed the stored OrcaRouter PKCE credential.')
	else:
		print('No stored OrcaRouter PKCE credential was found.')
	return 0


def handle(argv: list[str]) -> int:
	args = _parser().parse_args(argv)
	if args.command == 'login':
		try:
			return asyncio.run(_login(args))
		except KeyboardInterrupt:
			print('\nOrcaRouter login cancelled.', file=sys.stderr)
			return 130
	if args.command == 'status':
		return _status()
	if args.command == 'logout':
		return _logout()
	return 2
