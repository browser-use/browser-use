from pathlib import Path
from typing import Any

import pytest

from browser_use.experiments.daily_task_eval import models as daily_task_models
from browser_use.experiments.daily_task_eval.executor import (
	ExecutorConfig,
	default_max_actions_per_step_for_executor,
)
from browser_use.experiments.daily_task_eval.experiment_presets import (
	DailyExperimentId,
	build_configs_from_args,
	experiment_preset,
)
from browser_use.experiments.daily_task_eval.models import TaskCard, write_json
from browser_use.experiments.daily_task_eval.prompts import build_agent_task_prompt, build_navigator_prompt
from browser_use.experiments.daily_task_eval.runner import (
	compare_all,
	compare_runs,
	default_task_cards,
	init_experiment,
	run_agent_task,
	summarize_history,
)

class FakeHistory:
	def errors(self) -> list[str | None]:
		return [None, 'temporary click failure']

	def urls(self) -> list[str | None]:
		return ['https://example.test/start', None, 'https://example.test/done']

	def screenshot_paths(self, return_none_if_not_screenshot: bool = True) -> list[str | None]:
		assert return_none_if_not_screenshot is False
		return ['screen-1.png', None]

	def is_successful(self) -> bool:
		return True

	def is_done(self) -> bool:
		return True

	def total_duration_seconds(self) -> float:
		return 12.5

	def number_of_steps(self) -> int:
		return 3

	def action_names(self) -> list[str]:
		return ['navigate', 'click', 'done']

	def final_result(self) -> str:
		return 'Task completed'


def test_default_task_cards_cover_core_daily_task_shapes():
	cards = default_task_cards()

	assert {card.category for card in cards} == {'read_only_query', 'form_workflow', 'download_export'}
	assert all(card.success_criteria for card in cards)
	assert all(card.forbidden_actions for card in cards)
	assert all(len(card.failure_modes) >= 2 for card in cards)


def test_init_experiment_writes_task_and_human_baseline_templates(tmp_path):
	paths = init_experiment(tmp_path)

	task_cards = daily_task_models.load_json_model_list(paths['task_cards'], daily_task_models.TaskCard)
	human_runs = daily_task_models.load_json_model_list(paths['human_runs'], daily_task_models.HumanRunRecord)

	assert len(task_cards) == 3
	assert [run.task_id for run in human_runs] == [card.id for card in task_cards]
	assert paths['agent_runs'].read_text(encoding='utf-8').strip() == '[]'


def test_init_loads_existing_task_cards_when_present_without_overwrite(tmp_path):
	"""If teammates copy a repo-tracked task_cards.json first, init must align human_runs."""
	card = default_task_cards()[0].model_copy(update={'id': 'team_custom_task_only'})
	write_json(tmp_path / 'task_cards.json', [card.model_dump(mode='json')], overwrite=True)
	paths = init_experiment(tmp_path, overwrite=False)
	task_cards = daily_task_models.load_json_model_list(paths['task_cards'], daily_task_models.TaskCard)
	human_runs = daily_task_models.load_json_model_list(paths['human_runs'], daily_task_models.HumanRunRecord)
	assert len(task_cards) == 1
	assert task_cards[0].id == 'team_custom_task_only'
	assert [run.task_id for run in human_runs] == ['team_custom_task_only']


def test_build_agent_task_prompt_includes_failure_recovery_rules():
	task = default_task_cards()[1]

	prompt = build_agent_task_prompt(task, scenario_id='wrong_password')

	assert 'Password is wrong on first attempt' in prompt
	assert 'Do not retry a wrong password more than twice.' in prompt
	assert 'If blocked, call done with success=False' in prompt


def test_build_agent_task_prompt_includes_cn_network_reachability_rules():
	"""The CN-network section must mention google.com unreachability and the
	abandon-on-timeout rule, otherwise Qwen will keep picking google as a starting
	point and stall the browser via ScreenshotWatchdog timeouts.
	"""

	task = default_task_cards()[0]

	prompt = build_agent_task_prompt(task)

	assert 'Network reachability' in prompt
	assert 'google.com' in prompt
	assert 'net::ERR_NETWORK_CHANGED' in prompt
	assert 'baidu.com' in prompt


def test_build_agent_task_prompt_includes_early_finish_rule():
	"""Once Success criteria are met, the Agent must call done immediately. Without
	this rule Qwen tends to "double-check" on screenshot-heavy SPAs (Baidu Map / Amap)
	and waste 1–2 extra step_timeout cycles on ScreenshotWatchdog timeouts.
	"""

	task = default_task_cards()[0]

	prompt = build_agent_task_prompt(task)

	assert 'Early-finish rule' in prompt
	assert 'extract_structured_data' in prompt
	assert 'map.baidu.com' in prompt


def test_build_agent_task_prompt_can_include_navigator_plan():
	task = default_task_cards()[0]

	prompt = build_agent_task_prompt(
		task,
		scenario_id='page_stuck',
		navigator_plan='1. Check whether the spinner clears.\n2. Refresh once if it stays stuck.',
	)

	assert 'Navigator plan:' in prompt
	assert 'Refresh once if it stays stuck.' in prompt
	assert 'trust the live page state over stale assumptions' in prompt


def test_build_agent_task_prompt_strips_current_step_focus_from_navigator_plan_body():
	"""Executor-facing task text should not duplicate the XML focus block inside Navigator plan."""
	task = default_task_cards()[0]
	plan = (
		'<current_step_focus>\n'
		'Navigate to map.baidu.com in a new tab.\n'
		'</current_step_focus>\n\n'
		'## Assumptions\n'
		'Network is CN.'
	)
	prompt = build_agent_task_prompt(task, navigator_plan=plan)

	assert 'Navigator plan:' in prompt
	assert '## Assumptions' in prompt
	assert 'Network is CN.' in prompt
	assert '<current_step_focus>' not in prompt
	assert 'Navigate to map.baidu.com in a new tab.' not in prompt


def test_extract_navigator_step_focus_parses_inner_text():
	from browser_use.agent.message_manager.utils import extract_navigator_step_focus

	raw = 'intro\n<current_step_focus>\nOne\nTwo\n</current_step_focus>\ntail'
	focus, cleaned = extract_navigator_step_focus(raw)
	assert focus == 'One\nTwo'
	assert 'intro' in cleaned
	assert 'tail' in cleaned
	assert '<current_step_focus>' not in cleaned


def test_build_navigator_prompt_is_planning_only():
	task = default_task_cards()[0]

	prompt = build_navigator_prompt(task, scenario_id='page_stuck')

	assert 'You are the navigator, not the executor.' in prompt
	assert 'Failure scenario under test: Page loading spinner does not disappear' in prompt
	assert 'Stop conditions' in prompt
	assert '<current_step_focus>' in prompt


def test_summarize_history_extracts_comparable_agent_fields(tmp_path):
	summary = summarize_history(
		history=FakeHistory(),
		task_id='readonly_lookup',
		scenario_id='normal',
		navigator_enabled=True,
		navigator_model='qwen3-max',
		navigator_plan_path=tmp_path / 'navigator_plan.md',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:12+00:00',
		history_path=tmp_path / 'history.json',
		conversation_path=tmp_path / 'conversation.json',
	)

	assert summary.success is True
	assert summary.errors == ['temporary click failure']
	assert summary.urls == ['https://example.test/start', 'https://example.test/done']
	assert summary.screenshot_paths == ['screen-1.png']
	assert summary.number_of_steps == 3
	assert summary.navigator_enabled is True
	assert summary.navigator_model == 'qwen3-max'


def test_compare_runs_recommends_iteration_for_agent_failures():
	task = default_task_cards()[0]
	human = daily_task_models.HumanRunRecord(
		task_id=task.id,
		success_status='success',
		duration_seconds=20,
		stuck_points=['Spinner kept showing.'],
		recovery_actions=['Refreshed once.'],
	)
	agent = daily_task_models.AgentRunSummary(
		task_id=task.id,
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		success=False,
		is_done=True,
		duration_seconds=60,
		number_of_steps=8,
		action_names=['click', 'click', 'click', 'click', 'click'],
		errors=['Element not clickable'],
		history_path='history.json',
		conversation_path='conversation.json',
	)

	comparison = compare_runs(task, human, agent)

	assert 'agent_errors' in comparison.risk_flags
	assert 'possible_repeated_action_loop' in comparison.risk_flags
	assert any('Human succeeded but Agent did not' in difference for difference in comparison.differences)
	assert comparison.duration_delta_seconds == 40
	assert comparison.navigator_enabled is False


def test_experiment_preset_a_is_browser_use_without_navigator():
	ex, nav = experiment_preset(DailyExperimentId.A)

	assert ex.backend == 'chat_browser_use'
	assert not nav.enabled


def test_experiment_preset_b_enables_deepseek_navigator():
	_, nav = experiment_preset(DailyExperimentId.B)

	assert nav.enabled
	assert nav.backend == 'deepseek'
	assert nav.api_key_env == 'DEEPSEEK_API_KEY'


def test_experiment_preset_c_uses_qwen_executor():
	ex, nav = experiment_preset(DailyExperimentId.C)

	assert ex.backend == 'openai_compatible'
	assert ex.api_key_env == 'DASHSCOPE_API_KEY'
	assert not nav.enabled


def test_experiment_preset_d_combines_deepseek_nav_and_qwen_executor():
	ex, nav = experiment_preset(DailyExperimentId.D)

	assert ex.backend == 'openai_compatible'
	assert nav.enabled and nav.backend == 'deepseek'


def test_build_configs_from_args_experiment_conflicts_with_use_navigator():
	import argparse

	args = argparse.Namespace(
		experiment='A',
		use_navigator=True,
		executor_backend='chat_browser_use',
		executor_model=None,
		executor_api_key_env='DASHSCOPE_API_KEY',
		executor_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
		navigator_backend='none',
		navigator_model=None,
		navigator_api_key_env='DASHSCOPE_API_KEY',
		navigator_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
		navigator_deepseek_api_key_env='DEEPSEEK_API_KEY',
		navigator_deepseek_base_url='https://api.deepseek.com/v1',
	)

	try:
		build_configs_from_args(args)
	except ValueError as exc:
		assert 'use-navigator' in str(exc).lower()
	else:
		raise AssertionError('expected ValueError')


def test_default_max_actions_per_step_caps_qwen_to_one_to_avoid_malformed_urls():
	"""Qwen / OpenAI-compatible chat models occasionally bleed JSON closers into
	an action's URL field (the `%7D%7D` symptom). Forcing one action per step is
	the canonical safeguard; ChatBrowserUse keeps the upstream default (3).
	"""

	qwen_cfg = ExecutorConfig(backend='openai_compatible')
	bu_cfg = ExecutorConfig(backend='chat_browser_use')

	assert default_max_actions_per_step_for_executor(qwen_cfg) == 1
	assert default_max_actions_per_step_for_executor(bu_cfg) == 3


def test_build_configs_use_navigator_selects_openai_compatible_backend():
	import argparse

	args = argparse.Namespace(
		experiment=None,
		use_navigator=True,
		executor_backend='chat_browser_use',
		executor_model=None,
		executor_api_key_env='DASHSCOPE_API_KEY',
		executor_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
		navigator_backend='none',
		navigator_model='qwen-test',
		navigator_api_key_env='DASHSCOPE_API_KEY',
		navigator_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
		navigator_deepseek_api_key_env='DEEPSEEK_API_KEY',
		navigator_deepseek_base_url='https://api.deepseek.com/v1',
	)

	ex, nav, exp_id = build_configs_from_args(args)

	assert exp_id is None
	assert ex.backend == 'chat_browser_use'
	assert nav.enabled and nav.backend == 'openai_compatible'
	assert nav.model == 'qwen-test'


def test_compare_all_writes_report_for_multiple_agent_variants(tmp_path):
	task = default_task_cards()[0]
	task_cards_path = tmp_path / 'task_cards.json'
	human_runs_path = tmp_path / 'human_runs.json'
	agent_runs_path = tmp_path / 'agent_runs.json'
	report_path = tmp_path / 'report.json'
	payloads: dict[Path, list[dict[str, Any]]] = {
		task_cards_path: [task.model_dump(mode='json')],
		human_runs_path: [
			daily_task_models.HumanRunRecord(task_id=task.id, success_status='success').model_dump(mode='json')
		],
		agent_runs_path: [
			daily_task_models.AgentRunSummary(
				task_id=task.id,
				started_at='2026-01-01T00:00:00+00:00',
				finished_at='2026-01-01T00:00:10+00:00',
				success=True,
				is_done=True,
				duration_seconds=10,
				number_of_steps=3,
				history_path='history.json',
				conversation_path='conversation.json',
			).model_dump(mode='json'),
			daily_task_models.AgentRunSummary(
				task_id=task.id,
				navigator_enabled=True,
				navigator_model='qwen3-max',
				navigator_plan_path='navigator_plan.md',
				started_at='2026-01-01T00:01:00+00:00',
				finished_at='2026-01-01T00:01:12+00:00',
				success=True,
				is_done=True,
				duration_seconds=12,
				number_of_steps=2,
				history_path='history-with-navigator.json',
				conversation_path='conversation-with-navigator.json',
			).model_dump(mode='json'),
		],
	}
	for path, payload in payloads.items():
		daily_task_models.write_json(path, payload)

	comparisons = compare_all(task_cards_path, human_runs_path, agent_runs_path, report_path)

	assert len(comparisons) == 2
	assert {comparison.navigator_enabled for comparison in comparisons} == {False, True}
	assert report_path.exists()


def test_build_navigator_chat_model_requires_enabled():
	with pytest.raises(ValueError, match='enabled=True'):
		build_navigator_chat_model(NavigatorConfig(enabled=False))


def test_build_navigator_chat_model_openai_compatible(monkeypatch):
	monkeypatch.setenv('DASHSCOPE_API_KEY', 'dummy')
	cfg = NavigatorConfig(enabled=True, model='qwen-test-nav', backend='openai_compatible')
	llm = build_navigator_chat_model(cfg)
	assert llm.model == 'qwen-test-nav'


def test_build_navigator_chat_model_deepseek(monkeypatch):
	monkeypatch.setenv('DEEPSEEK_API_KEY', 'dummy')
	cfg = NavigatorConfig(
		enabled=True,
		model='deepseek-reasoner',
		backend='deepseek',
		api_key_env='DEEPSEEK_API_KEY',
		base_url='https://api.deepseek.com/v1',
	)
	llm = build_navigator_chat_model(cfg)
	assert llm.model == 'deepseek-reasoner'


async def test_continuous_navigation_requires_navigator(tmp_path):
	task = TaskCard(
		id='t1',
		name='test',
		category='read_only_query',
		task_prompt='open example',
	)
	with pytest.raises(ValueError, match='continuous_navigation requires'):
		await run_agent_task(
			task=task,
			output_dir=tmp_path,
			scenario_id='normal',
			max_steps=1,
			headless=True,
			navigator_config=NavigatorConfig(enabled=False),
			continuous_navigation=True,
		)
