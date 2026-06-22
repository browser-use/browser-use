import json
from pathlib import Path
from typing import Any

import pytest

from browser_use.experiments.daily_task_eval import models as daily_task_models
from browser_use.experiments.daily_task_eval.executor import (
	ExecutorConfig,
	VOLCES_ARK_API_KEY_ENV,
	VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL,
	build_executor_llm,
	default_max_actions_per_step_for_executor,
	resolve_openai_compatible_credentials,
)
from browser_use.experiments.daily_task_eval.experiment_presets import (
	DailyExperimentId,
	build_configs_from_args,
	experiment_preset,
)
from browser_use.experiments.daily_task_eval.models import TaskCard, write_json
from browser_use.experiments.daily_task_eval.navigator import NavigatorConfig, build_navigator_chat_model
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.experiments.daily_task_eval.prompts import build_agent_task_prompt, build_navigator_prompt
from browser_use.experiments.daily_task_eval.models import (
	academic_efficiency_from_agent_run,
	compute_execution_velocity,
	compute_navigator_overhead_ratio,
	compute_token_efficiency_score,
)
from browser_use.experiments.daily_task_eval.runner import (
	build_experiment_resource_report,
	compare_all,
	compare_runs,
	default_task_cards,
	export_agent_runs_to_csv,
	export_experiment_resource_report_to_csv,
	format_academic_efficiency_frontier_analysis,
	init_experiment,
	resource_snapshot_from_agent,
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


def test_fixtures_task_cards_include_mind2web_style_benchmarks():
	from pathlib import Path

	fixtures = Path(__file__).resolve().parents[2] / 'examples' / 'evaluation' / 'fixtures' / 'task_cards.json'
	cards = daily_task_models.load_json_model_list(fixtures, daily_task_models.TaskCard)
	ids = {c.id for c in cards}
	assert {
		'complex_travel_package_booking',
		'github_clean_issue_audit',
		'huggingface_model_constrained_selection',
	}.issubset(ids)
	assert 'multi_step_transaction_query' in {c.category for c in cards}
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
	assert paths['csv_out'].is_dir()


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
		task_category='read_only_query',
	)

	assert summary.success is True
	assert summary.task_category == 'read_only_query'
	assert summary.errors == ['temporary click failure']
	assert summary.urls == ['https://example.test/start', 'https://example.test/done']
	assert summary.screenshot_paths == ['screen-1.png']
	assert summary.number_of_steps == 3
	assert summary.navigator_enabled is True
	assert summary.navigator_model == 'qwen3-max'


def test_resource_snapshot_uses_wall_clock_when_history_duration_non_positive():
	agent = daily_task_models.AgentRunSummary(
		task_id='t1',
		experiment_id='C',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:03:00+00:00',
		success=None,
		is_done=False,
		duration_seconds=0.0,
		number_of_steps=7,
		history_path='h.json',
		conversation_path='c.json',
	)
	snap = resource_snapshot_from_agent(agent)
	assert snap.duration_seconds == pytest.approx(180.0)
	assert snap.duration_used_wall_clock_fallback is True


def test_compute_navigator_overhead_ratio_boundaries():
	assert compute_navigator_overhead_ratio(
		navigator_enabled=False,
		executor_tokens=1000,
		navigator_cycle_tokens=200,
		navigator_initial_tokens=100,
	) == 0.0
	assert compute_navigator_overhead_ratio(
		navigator_enabled=True,
		executor_tokens=0,
		navigator_cycle_tokens=100,
		navigator_initial_tokens=50,
	) == 0.0
	assert compute_navigator_overhead_ratio(
		navigator_enabled=True,
		executor_tokens=1000,
		navigator_cycle_tokens=200,
		navigator_initial_tokens=100,
	) == pytest.approx(0.3)


def test_compute_execution_velocity_and_token_efficiency():
	assert compute_execution_velocity(total_tokens=5000, duration_seconds=50.0) == pytest.approx(100.0)
	assert compute_execution_velocity(total_tokens=100, duration_seconds=0.0) == 0.0
	assert compute_token_efficiency_score(success=True, total_tokens=2000) == pytest.approx(0.5)
	assert compute_token_efficiency_score(success=False, total_tokens=2000) == 0.0
	assert compute_token_efficiency_score(success=True, total_tokens=0) == 0.0


def test_academic_efficiency_from_agent_run_splits_usage():
	agent = daily_task_models.AgentRunSummary(
		task_id='t1',
		experiment_id='D',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		success=True,
		is_done=True,
		duration_seconds=60.0,
		number_of_steps=5,
		navigator_enabled=True,
		history_path='h.json',
		conversation_path='c.json',
		usage_summary={'total_tokens': 3000},
		usage_executor_llm={'total_tokens': 2000},
		usage_navigator_cycle_llm={'total_tokens': 400},
		navigator_initial_plan_usage={'total_tokens': 200},
	)
	oh, vel, eff = academic_efficiency_from_agent_run(agent, duration_seconds=60.0)
	assert oh == pytest.approx(0.3)
	assert vel == pytest.approx(50.0)
	assert eff == pytest.approx(1.0 / 3.0)


def test_resource_snapshot_includes_academic_metrics():
	agent = daily_task_models.AgentRunSummary(
		task_id='t1',
		experiment_id='C',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:02:00+00:00',
		success=True,
		is_done=True,
		duration_seconds=120.0,
		number_of_steps=4,
		navigator_enabled=False,
		history_path='h.json',
		conversation_path='c.json',
		usage_summary={'total_tokens': 1200},
		usage_executor_llm={'total_tokens': 1200},
	)
	snap = resource_snapshot_from_agent(agent)
	assert snap.navigator_overhead_ratio == 0.0
	assert snap.execution_velocity == pytest.approx(10.0)
	assert snap.token_efficiency_score == pytest.approx(1.0 / 1.2)


def test_resource_snapshot_keeps_positive_history_duration():
	agent = daily_task_models.AgentRunSummary(
		task_id='t1',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:10:00+00:00',
		success=True,
		is_done=True,
		duration_seconds=42.5,
		number_of_steps=3,
		history_path='h.json',
		conversation_path='c.json',
	)
	snap = resource_snapshot_from_agent(agent)
	assert snap.duration_seconds == pytest.approx(42.5)
	assert snap.duration_used_wall_clock_fallback is False


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

	assert comparison.task_category == task.category
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


def test_experiment_preset_c_uses_doubao_executor():
	ex, nav = experiment_preset(DailyExperimentId.C)

	assert ex.backend == 'openai_compatible'
	assert ex.model == 'doubao-seed-2-0-pro-260215'
	assert ex.api_key_env == VOLCES_ARK_API_KEY_ENV
	assert ex.base_url == VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL
	assert not nav.enabled


def test_experiment_preset_d_combines_deepseek_nav_and_doubao_executor():
	ex, nav = experiment_preset(DailyExperimentId.D)

	assert ex.backend == 'openai_compatible'
	assert ex.model == 'doubao-seed-2-0-pro-260215'
	assert ex.api_key_env == VOLCES_ARK_API_KEY_ENV
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


def test_resolve_openai_compatible_credentials_doubao_uses_volcengine_ark_defaults():
	key, url = resolve_openai_compatible_credentials('doubao-seed-2-0-pro-260215', None, None)
	assert key == VOLCES_ARK_API_KEY_ENV
	assert url == VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL

	key2, url2 = resolve_openai_compatible_credentials('ep-20250101-fake', None, None)
	assert key2 == VOLCES_ARK_API_KEY_ENV
	assert url2 == VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL


def test_resolve_openai_compatible_credentials_qwen_defaults_to_dashscope():
	key, url = resolve_openai_compatible_credentials('qwen3-max', None, None)
	assert key == 'DASHSCOPE_API_KEY'
	assert 'dashscope.aliyuncs.com' in url


def test_build_configs_experiment_d_defaults_to_doubao_ark_without_extra_cli_flags():
	import argparse

	args = argparse.Namespace(
		experiment='D',
		use_navigator=False,
		executor_backend=None,
		executor_model=None,
		executor_api_key_env=None,
		executor_base_url=None,
		navigator_backend='none',
		navigator_model=None,
		navigator_api_key_env='DASHSCOPE_API_KEY',
		navigator_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
		navigator_deepseek_api_key_env='DEEPSEEK_API_KEY',
		navigator_deepseek_base_url='https://api.deepseek.com/v1',
	)

	ex, nav, exp_id = build_configs_from_args(args)

	assert exp_id == 'D'
	assert ex.model == 'doubao-seed-2-0-pro-260215'
	assert ex.backend == 'openai_compatible'
	assert ex.api_key_env == VOLCES_ARK_API_KEY_ENV
	assert ex.base_url == VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL
	assert nav.enabled and nav.backend == 'deepseek'


def test_build_executor_llm_volcengine_ark_disables_response_format_json_schema(monkeypatch):
	monkeypatch.setenv('ARK_API_KEY', 'test-ark-key-placeholder')
	llm = build_executor_llm(
		ExecutorConfig(
			backend='openai_compatible',
			model='doubao-seed-2-0-pro-260215',
			api_key_env=VOLCES_ARK_API_KEY_ENV,
			base_url=VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL,
		)
	)
	assert isinstance(llm, ChatOpenAI)
	assert llm.dont_force_structured_output is True
	assert llm.add_schema_to_system_prompt is True
	assert llm.temperature == 0.0


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

	comparisons = compare_all(
		task_cards_path,
		human_runs_path,
		report_path,
		agent_runs_path=agent_runs_path,
	)

	assert len(comparisons) == 2
	assert {comparison.navigator_enabled for comparison in comparisons} == {False, True}
	assert report_path.exists()
	resource_path = report_path.with_name('experiment_resource_report.json')
	assert resource_path.exists()
	res_doc = json.loads(resource_path.read_text(encoding='utf-8'))
	assert res_doc['groups']
	assert {g['task_id'] for g in res_doc['groups']} == {task.id}
	assert len(res_doc['groups_index']) == 1
	assert res_doc['groups_index'][0]['task_id'] == task.id
	assert res_doc['groups_index'][0]['snapshot_count'] == 2
	g0 = res_doc['groups'][0]
	assert g0['statistics_by_experiment']
	assert g0['pooled_statistics']['is_pooled'] is True


def test_compare_all_skip_resource_report(tmp_path):
	task = default_task_cards()[0]
	task_cards_path = tmp_path / 'task_cards.json'
	human_runs_path = tmp_path / 'human_runs.json'
	agent_runs_path = tmp_path / 'agent_runs.json'
	report_path = tmp_path / 'report.json'
	daily_task_models.write_json(task_cards_path, [task.model_dump(mode='json')])
	daily_task_models.write_json(human_runs_path, [])
	daily_task_models.write_json(
		agent_runs_path,
		[
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
			).model_dump(mode='json')
		],
	)
	compare_all(
		task_cards_path,
		human_runs_path,
		report_path,
		agent_runs_path=agent_runs_path,
		skip_resource_report=True,
	)
	assert not (report_path.with_name('experiment_resource_report.json')).exists()


def test_build_experiment_resource_report_includes_academic_statistics():
	task = default_task_cards()[0]
	agents = [
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='C',
			started_at='2026-01-01T00:00:00+00:00',
			finished_at='2026-01-01T00:01:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=100.0,
			number_of_steps=5,
			navigator_enabled=False,
			history_path='h1.json',
			conversation_path='c1.json',
			usage_summary={'total_tokens': 1000},
			usage_executor_llm={'total_tokens': 1000},
		),
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='D',
			started_at='2026-01-02T00:00:00+00:00',
			finished_at='2026-01-02T00:02:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=200.0,
			number_of_steps=8,
			navigator_enabled=True,
			history_path='h2.json',
			conversation_path='c2.json',
			usage_summary={'total_tokens': 3000},
			usage_executor_llm={'total_tokens': 2000},
			usage_navigator_cycle_llm={'total_tokens': 500},
			navigator_initial_plan_usage={'total_tokens': 500},
		),
	]
	report = build_experiment_resource_report(agents, [task])
	row_c = next(r for r in report.groups[0].statistics_by_experiment if r.experiment_id == 'C')
	row_d = next(r for r in report.groups[0].statistics_by_experiment if r.experiment_id == 'D')
	assert row_c.navigator_overhead_ratio is not None
	assert row_c.navigator_overhead_ratio.mean == 0.0
	assert row_c.token_efficiency_score is not None and row_c.token_efficiency_score.mean == pytest.approx(1.0)
	assert row_d.navigator_overhead_ratio is not None
	assert row_d.navigator_overhead_ratio.mean == pytest.approx(0.5)
	assert row_d.execution_velocity is not None and row_d.execution_velocity.mean == pytest.approx(15.0)
	pooled = report.groups[0].pooled_statistics
	assert pooled is not None
	assert pooled.execution_velocity is not None and pooled.execution_velocity.n == 2


def test_format_academic_efficiency_frontier_analysis_lists_c_vs_d():
	task = default_task_cards()[0]
	agents = [
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='C',
			started_at='2026-01-01T00:00:00+00:00',
			finished_at='2026-01-01T00:01:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=10.0,
			number_of_steps=1,
			history_path='h1.json',
			conversation_path='c1.json',
			usage_summary={'total_tokens': 1000},
			usage_executor_llm={'total_tokens': 1000},
		),
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='D',
			started_at='2026-01-02T00:00:00+00:00',
			finished_at='2026-01-02T00:02:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=20.0,
			number_of_steps=2,
			navigator_enabled=True,
			history_path='h2.json',
			conversation_path='c2.json',
			usage_summary={'total_tokens': 2000},
			usage_executor_llm={'total_tokens': 1000},
			navigator_initial_plan_usage={'total_tokens': 500},
		),
	]
	report = build_experiment_resource_report(agents, [task])
	text = format_academic_efficiency_frontier_analysis(report)
	assert 'Academic Efficiency Frontier Analysis' in text
	assert 'navigator_overhead_ratio' in text
	assert 'token_efficiency_score' in text
	assert task.id in text


def test_build_experiment_resource_report_hints_cost_spread():
	task = default_task_cards()[0]
	agents = [
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='A',
			started_at='2026-01-01T00:00:00+00:00',
			finished_at='2026-01-01T00:01:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=100.0,
			number_of_steps=10,
			history_path='h1.json',
			conversation_path='c1.json',
			task_category=task.category,
			usage_summary={
				'total_tokens': 1000,
				'total_cost': 0.01,
				'total_prompt_tokens': 800,
				'total_completion_tokens': 200,
				'entry_count': 5,
			},
		),
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='B',
			started_at='2026-01-02T00:00:00+00:00',
			finished_at='2026-01-02T00:02:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=200.0,
			number_of_steps=5,
			history_path='h2.json',
			conversation_path='c2.json',
			task_category=task.category,
			usage_summary={
				'total_tokens': 2000,
				'total_cost': 0.05,
				'total_prompt_tokens': 1500,
				'total_completion_tokens': 500,
				'entry_count': 4,
			},
		),
	]
	report = build_experiment_resource_report(agents, [task])
	assert len(report.groups) == 1
	assert len(report.groups[0].snapshots) == 2
	hints = ' '.join(report.groups[0].analysis_hints)
	assert 'Lowest total_cost' in hints
	assert 'experiment_id=' in hints

	by_exp = report.groups[0].statistics_by_experiment
	assert len(by_exp) == 2
	row_a = next(r for r in by_exp if r.experiment_id == 'A')
	row_b = next(r for r in by_exp if r.experiment_id == 'B')
	assert row_a.is_pooled is False and row_b.is_pooled is False
	assert row_a.run_count == 1 and row_b.run_count == 1
	assert row_a.duration_seconds.mean == pytest.approx(100.0)
	assert row_b.total_tokens is not None and row_b.total_tokens.mean == pytest.approx(2000.0)
	assert row_b.total_tokens.std is None

	pooled = report.groups[0].pooled_statistics
	assert pooled is not None
	assert pooled.is_pooled is True
	assert pooled.run_count == 2
	assert pooled.duration_seconds.n == 2
	assert pooled.duration_seconds.mean == pytest.approx(150.0)
	assert pooled.duration_seconds.std is not None
	assert pooled.total_tokens is not None and pooled.total_tokens.mean == pytest.approx(1500.0)


def test_build_experiment_resource_report_groups_index_follows_task_cards_order():
	"""groups / groups_index order follows task_cards list, not alphabetical task_id."""
	task_b = TaskCard(id='bbb_lookup', name='b', category='read_only_query', task_prompt='do b')
	task_a = TaskCard(id='aaa_lookup', name='a', category='read_only_query', task_prompt='do a')
	agents = [
		daily_task_models.AgentRunSummary(
			task_id='aaa_lookup',
			scenario_id='normal',
			experiment_id='C',
			started_at='2026-01-02T00:00:00+00:00',
			finished_at='2026-01-02T00:00:01+00:00',
			success=True,
			is_done=True,
			duration_seconds=1.0,
			number_of_steps=1,
			history_path='h1.json',
			conversation_path='c1.json',
		),
		daily_task_models.AgentRunSummary(
			task_id='bbb_lookup',
			scenario_id='normal',
			experiment_id='D',
			started_at='2026-01-01T00:00:00+00:00',
			finished_at='2026-01-01T00:00:01+00:00',
			success=True,
			is_done=True,
			duration_seconds=1.0,
			number_of_steps=1,
			history_path='h2.json',
			conversation_path='c2.json',
		),
	]
	report = build_experiment_resource_report(agents, [task_b, task_a])
	assert [g.task_id for g in report.groups] == ['bbb_lookup', 'aaa_lookup']
	assert [row.task_id for row in report.groups_index] == ['bbb_lookup', 'aaa_lookup']
	assert report.groups_index[0].experiment_ids == ['D']
	assert report.groups_index[1].experiment_ids == ['C']


def test_export_experiment_resource_report_to_csv(tmp_path):
	task = default_task_cards()[0]
	agents = [
		daily_task_models.AgentRunSummary(
			task_id=task.id,
			scenario_id='normal',
			experiment_id='A',
			started_at='2026-01-01T00:00:00+00:00',
			finished_at='2026-01-01T00:01:00+00:00',
			success=True,
			is_done=True,
			duration_seconds=10.0,
			number_of_steps=2,
			history_path='h.json',
			conversation_path='c.json',
			task_category=task.category,
			usage_summary={'total_tokens': 100, 'total_cost': 0.0, 'entry_count': 2},
		),
	]
	report = build_experiment_resource_report(agents, [task])
	report_path = tmp_path / 'experiment_resource_report.json'
	daily_task_models.write_json(report_path, report.model_dump(mode='json'))
	runs_csv = tmp_path / 'out_runs.csv'
	stats_csv = tmp_path / 'out_stats.csv'
	export_experiment_resource_report_to_csv(report_path, runs_csv, stats_csv)
	lines = runs_csv.read_text(encoding='utf-8').strip().splitlines()
	assert len(lines) == 2
	assert lines[0].startswith('task_id,')
	assert task.id in lines[1]
	stat_lines = stats_csv.read_text(encoding='utf-8').strip().splitlines()
	assert len(stat_lines) >= 3
	assert 'stats_is_pooled' in stat_lines[0]
	assert any('(pooled)' in line for line in stat_lines[1:])


def test_export_agent_runs_to_csv(tmp_path):
	task = default_task_cards()[0]
	agent = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:05+00:00',
		success=False,
		is_done=True,
		duration_seconds=5.0,
		number_of_steps=1,
		action_names=['done'],
		errors=['x'],
		history_path='h.json',
		conversation_path='c.json',
	)
	path = tmp_path / 'agent_runs.json'
	daily_task_models.write_json(path, [agent.model_dump(mode='json')])
	out = tmp_path / 'flat.csv'
	export_agent_runs_to_csv(path, out)
	rows = out.read_text(encoding='utf-8').strip().splitlines()
	assert len(rows) == 2
	assert 'usage_total_tokens' in rows[0]
	assert 'done' in rows[1] and 'x' in rows[1]


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


def test_trajectory_lcs_similarity():
	from browser_use.experiments.daily_task_eval.run_csv import trajectory_lcs_similarity

	assert trajectory_lcs_similarity(['navigate', 'click', 'done'], ['navigate', 'click', 'done']) == 1.0
	assert trajectory_lcs_similarity(['navigate', 'click'], ['navigate', 'wait', 'click']) == pytest.approx(2 / 3)
	assert trajectory_lcs_similarity([], ['navigate']) == 0.0
	# Hospital-style run: agent skips extract; LCS still uses raw action sequences.
	agent = ['navigate', 'input', 'click', 'click', 'done']
	human = [
		'navigate',
		'input',
		'click',
		'wait',
		'click',
		'extract',
		'scroll',
		'click',
		'extract',
		'scroll',
		'extract',
		'done',
	]
	assert trajectory_lcs_similarity(agent, human) == pytest.approx(5 / 12)


def test_get_filtered_trajectory_and_navigation_lcs():
	from browser_use.experiments.daily_task_eval.run_csv import (
		FILTERED_OUT_TOOLS,
		get_filtered_trajectory,
		trajectory_lcs_navigation,
		trajectory_lcs_similarity,
	)

	assert 'extract' in FILTERED_OUT_TOOLS
	assert 'click' not in FILTERED_OUT_TOOLS

	human = [
		'navigate',
		'input',
		'click',
		'click',
		'extract',
		'click',
		'extract',
		'click',
		'extract',
		'done',
	]
	agent = ['navigate', 'input', 'click', 'click', 'done']
	assert get_filtered_trajectory(human) == [
		'navigate',
		'input',
		'click',
		'click',
		'click',
		'click',
		'done',
	]
	assert get_filtered_trajectory(agent) == agent
	assert trajectory_lcs_similarity(agent, human) == pytest.approx(5 / 10)
	assert trajectory_lcs_navigation(agent, human) == pytest.approx(5 / 7)
	assert trajectory_lcs_navigation(['navigate', 'wait', 'click'], ['navigate', 'click']) == 1.0
	assert trajectory_lcs_navigation(['extract'], ['extract']) is None
	assert trajectory_lcs_navigation(['extract'], ['navigate']) == 0.0


def test_count_action_names_and_human_baseline():
	from browser_use.experiments.daily_task_eval.run_csv import (
		build_agent_run_csv_row,
		count_action_names,
		count_human_steps,
	)

	agent = ['navigate', 'input', 'click', 'click', 'done']
	counts = count_action_names(agent)
	assert counts['micro_action_count'] == 5
	assert counts['click_count'] == 2
	assert counts['extract_count'] == 0
	assert counts['done_count'] == 1

	human_steps = ['navigate', 'input', 'click', 'wait', 'click', 'extract', 'extract', 'extract', 'done']
	human_counts = count_human_steps(human_steps)
	assert human_counts['micro_action_count'] == 9
	assert human_counts['extract_count'] == 3

	task = default_task_cards()[0]
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:10+00:00',
		success=True,
		is_done=True,
		duration_seconds=10,
		number_of_steps=5,
		action_names=agent,
		history_path='h.json',
		conversation_path='c.json',
	)
	human = daily_task_models.HumanRunRecord(
		task_id=task.id,
		scenario_id='normal',
		steps=human_steps,
	)
	row = build_agent_run_csv_row(method='C', task=task, summary=summary, human=human)
	assert row['number_of_steps'] == 5
	assert row['micro_action_count'] == 5
	assert row['extract_count'] == 0
	assert row['human_micro_action_count'] == 9
	assert row['human_extract_count'] == 3
	assert row['trajectory_lcs_similarity'] == pytest.approx(5 / 9)
	assert row['trajectory_lcs_navigation'] == 1.0


def test_evaluate_cup_success_requires_success_and_policy_fields():
	from browser_use.experiments.daily_task_eval.run_csv import evaluate_cup_success

	task = default_task_cards()[0]
	ok = daily_task_models.AgentRunSummary(
		task_id=task.id,
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:10+00:00',
		success=True,
		is_done=True,
		duration_seconds=10,
		number_of_steps=3,
		history_path='h.json',
		conversation_path='c.json',
	)
	assert evaluate_cup_success(task, ok) == 1
	bad = ok.model_copy(update={'success': False})
	assert evaluate_cup_success(task, bad) == 0


def test_append_agent_run_csv_and_compare_from_csv_dir(tmp_path):
	from browser_use.experiments.daily_task_eval.run_csv import append_agent_run_csv_row, load_agent_summaries_from_csv_dir

	task = default_task_cards()[0]
	csv_dir = tmp_path / 'csv_out'
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		task_category=task.category,
		experiment_id='C',
		executor_model='doubao-seed-2-0-pro-260215',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:10+00:00',
		success=True,
		is_done=True,
		duration_seconds=10,
		number_of_steps=3,
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
		usage_executor_llm={'total_tokens': 1000, 'prompt_tokens': 800, 'completion_tokens': 200},
	)
	human = daily_task_models.HumanRunRecord(
		task_id=task.id,
		scenario_id='normal',
		steps=['navigate', 'extract', 'done'],
	)
	path = append_agent_run_csv_row(csv_dir, method='C', task=task, summary=summary, human=human)
	assert path.name == 'exp-C_runs.csv'
	lines = path.read_text(encoding='utf-8').strip().splitlines()
	assert len(lines) == 2
	header = lines[0].split(',')
	assert 'micro_action_count' in header
	assert 'human_extract_count' in header
	assert 'trajectory_lcs_navigation' in header
	row_cells = lines[1].split(',')
	assert row_cells[header.index('micro_action_count')] == '3'
	assert row_cells[header.index('click_count')] == '1'
	assert row_cells[header.index('human_micro_action_count')] == '3'
	assert row_cells[header.index('human_extract_count')] == '1'
	assert 'method' in lines[0] and ',C,' in lines[1] or lines[1].startswith('C,')
	loaded = load_agent_summaries_from_csv_dir(csv_dir)
	assert len(loaded) == 1
	assert loaded[0].task_id == task.id

	task_cards_path = tmp_path / 'task_cards.json'
	human_runs_path = tmp_path / 'human_runs.json'
	report_path = tmp_path / 'report.json'
	daily_task_models.write_json(task_cards_path, [task.model_dump(mode='json')])
	daily_task_models.write_json(human_runs_path, [human.model_dump(mode='json')])
	comparisons = compare_all(task_cards_path, human_runs_path, report_path, csv_dir=csv_dir)
	assert len(comparisons) == 1
	assert report_path.exists()
