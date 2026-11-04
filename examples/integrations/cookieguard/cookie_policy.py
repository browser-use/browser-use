"""Enforce an optional cookie audit after a local Browser Use agent login.

Uses the external package's synthetic app and scripted model to exercise the
real Agent loop without an API key. The scripted model is not an AI model.
"""

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import cast

os.environ['ANONYMIZED_TELEMETRY'] = 'false'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['BROWSER_USE_DISABLE_EXTENSIONS'] = '1'

# This optional example dependency is deliberately absent from Browser Use's dependencies.
from cookieguard_browser_use import AuditResult, CookieGuardAudit, CookiePolicyError  # pyright: ignore[reportMissingImports]
from cookieguard_browser_use.demo.app import DEMO_PASSWORD, DEMO_USERNAME, DemoApp  # pyright: ignore[reportMissingImports]
from cookieguard_browser_use.demo.scripted import ScriptedLoginModel  # pyright: ignore[reportMissingImports]

from browser_use import Agent, BrowserProfile, BrowserSession, Tools
from browser_use.llm.base import BaseChatModel


@dataclass
class LoginRun:
	login_succeeded: bool
	agent_succeeded: bool
	result: AuditResult | None


def create_local_browser() -> BrowserSession:
	"""Create the disposable browser used by the loopback demo."""
	return BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			keep_alive=True,
			user_data_dir=None,
			enable_default_extensions=False,
			allowed_domains=['127.0.0.1'],  # Exact hostname matching rejects lookalike external hosts.
		)
	)


async def run_login(mode: str, *, guarded: bool = True, call_tool: bool = False) -> LoginRun:
	"""Use a fresh loopback app/browser; retain the final audit for developer enforcement."""
	with DemoApp(mode) as app:
		audit = CookieGuardAudit(allowed_origins=[app.origin], auth_cookies=['session_id']) if guarded else None
		session = create_local_browser()
		tools = Tools()
		if audit:
			audit.register_tools(tools)  # Optional provisional, value-free check for the agent.
		try:
			await session.start()
			if audit:
				await audit.start(session)  # Attach before login so Set-Cookie declarations are observed.
			# The external demo fixture satisfies the exercised runtime methods but
			# does not declare the full BaseChatModel typing/Pydantic protocol.
			model = cast(BaseChatModel, ScriptedLoginModel(app.origin, call_audit_tool=call_tool and guarded))
			agent = Agent(
				task=f'Log in at {app.origin}/login using login_user and login_password. Finish after Login succeeded.',
				llm=model,
				browser_session=session,
				tools=tools,
				sensitive_data={'http://127.0.0.1': {'login_user': DEMO_USERNAME, 'login_password': DEMO_PASSWORD}},
				use_vision=False,
				use_judge=False,
				calculate_cost=False,
			)
			history = await agent.run(max_steps=8)
			result = await audit.finish() if audit else None  # Agent success does not decide cookie policy.
			return LoginRun(app.logins > 0, history.is_successful() is True, result)
		finally:
			try:
				if audit:
					await audit.close()
			finally:
				await session.kill()


async def main(mode: str, baseline: bool) -> int:
	outcome = await run_login(mode, guarded=not baseline)
	print(f'Server login succeeded: {outcome.login_succeeded}; agent succeeded: {outcome.agent_succeeded}')
	if outcome.result is not None:
		print(outcome.result.summary)
		try:
			outcome.result.assert_policy()  # Enforce even when the agent never calls the tool.
		except CookiePolicyError as error:
			return error.exit_code  # FAIL=1; INCOMPLETE=2.
	else:
		print('Cookie policy: NOT_AUDITED')
	return 0 if outcome.login_succeeded and outcome.agent_succeeded else 2


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--mode', choices=('insecure', 'secure'), default='insecure')
	parser.add_argument('--baseline', action='store_true')
	args = parser.parse_args()
	raise SystemExit(asyncio.run(main(args.mode, args.baseline)))
