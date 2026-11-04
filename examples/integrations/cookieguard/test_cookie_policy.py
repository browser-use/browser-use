"""Opt-in real-browser checks; requires the external package and Node.js 24+."""

import asyncio

import pytest

pytest.importorskip('cookieguard_browser_use')

from cookie_policy import main, run_login
from cookieguard_browser_use import CookiePolicyError  # pyright: ignore[reportMissingImports]


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
