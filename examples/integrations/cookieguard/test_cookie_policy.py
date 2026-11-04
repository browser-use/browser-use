"""Opt-in real-browser checks; requires the external package and Node.js 24+."""

import asyncio

import pytest

pytest.importorskip('cookieguard_browser_use')

from cookie_policy import create_local_browser, main, run_login
from cookieguard_browser_use import CookiePolicyError  # pyright: ignore[reportMissingImports]

from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog


def test_demo_navigation_rejects_loopback_lookalikes():
	"""Check the demo's actual profile without launching a browser or contacting any URL."""
	session = create_local_browser()
	watchdog = SecurityWatchdog(browser_session=session, event_bus=session.event_bus)
	assert watchdog._is_url_allowed('http://127.0.0.1:12345/login')
	assert watchdog._is_url_allowed('http://127.0.0.1:54321/account')
	for url in (
		'http://127.0.0.1.evil.example/',
		'http://127.0.0.1@evil.example/',
		'http://127.0.0.10/',
		'http://www.127.0.0.1/',
		'http://evil.example/?next=http://127.0.0.1/',
	):
		assert not watchdog._is_url_allowed(url), url


@pytest.mark.parametrize('mode', ['insecure', 'secure'])
def test_baseline_logs_in_without_a_security_verdict(mode):
	outcome = asyncio.run(run_login(mode, guarded=False))
	assert outcome.login_succeeded and outcome.agent_succeeded
	assert outcome.result is None


def test_final_audit_enforces_missing_httponly_without_an_agent_tool_call():
	outcome = asyncio.run(run_login('insecure'))
	assert outcome.login_succeeded and outcome.agent_succeeded
	assert outcome.result is not None
	assert outcome.result.status == 'FAIL'
	assert outcome.result.collection['agentChecks'] == 0
	assert {f.rule_id for f in outcome.result.confirmed_findings} == {'CG001'}
	with pytest.raises(CookiePolicyError) as caught:
		outcome.result.assert_policy()
	assert caught.value.exit_code == 1


def test_secure_cookie_passes_and_agent_can_call_the_optional_tool():
	outcome = asyncio.run(run_login('secure', call_tool=True))
	assert outcome.login_succeeded and outcome.agent_succeeded
	assert outcome.result is not None
	assert outcome.result.collection['agentChecks'] == 1
	assert outcome.result.status == 'PASS' and not outcome.result.confirmed_findings
	outcome.result.assert_policy()


@pytest.mark.parametrize(('mode', 'expected'), [('insecure', 1), ('secure', 0)])
def test_command_enforces_policy(mode, expected, capfd):
	assert asyncio.run(main(mode, baseline=False)) == expected
	captured = capfd.readouterr()
	assert 'cg-disposable-password-41f7' not in captured.out + captured.err
