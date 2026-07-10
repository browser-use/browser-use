import json
from pathlib import Path
from typing import Any

import pytest

from browser_use.experiments.daily_task_eval import models as daily_task_models
from browser_use.experiments.daily_task_eval.executor import (
	VOLCES_ARK_API_KEY_ENV,
	VOLCES_ARK_CN_OPENAI_COMPAT_BASE_URL,
	ExecutorConfig,
	build_executor_llm,
	default_max_actions_per_step_for_executor,
	resolve_openai_compatible_credentials,
)
from browser_use.experiments.daily_task_eval.experiment_presets import (
	DailyExperimentId,
	PAPER_CONDITION_ADAPTIVE,
	PAPER_EXPERIMENT_CA,
	build_configs_from_args,
	experiment_preset,
	experiment_run_flags_from_args,
	paper_experiment_preset,
)
from browser_use.experiments.daily_task_eval.models import (
	TaskCard,
	academic_efficiency_from_agent_run,
	compute_execution_velocity,
	compute_navigator_overhead_ratio,
	compute_token_efficiency_score,
	write_json,
)
from browser_use.experiments.daily_task_eval.navigator import NavigatorConfig, build_navigator_chat_model
from browser_use.experiments.daily_task_eval.prompts import build_agent_task_prompt, build_navigator_prompt
from browser_use.experiments.daily_task_eval.runner import (
	adjudicate_agent_summary,
	build_experiment_resource_report,
	build_huggingface_executor_subgoal_from_url,
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
from browser_use.experiments.daily_task_eval.human_reference import audit_human_run_record, validate_reference_eligibility
from browser_use.experiments.daily_task_eval.task_registry import (
	get_archived_tasks,
	get_main_tasks,
	get_stress_tasks,
	get_tasks_for_aggregate_metrics,
)
from browser_use.llm.openai.chat import ChatOpenAI


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


def test_fixtures_task_cards_prioritize_amazon_and_baidu_map_domains():
	from pathlib import Path

	fixtures = Path(__file__).resolve().parents[2] / 'examples' / 'evaluation' / 'fixtures' / 'task_cards.json'
	cards = daily_task_models.load_json_model_list(fixtures, daily_task_models.TaskCard)
	by_id = {card.id: card for card in cards}

	shopping = by_id['shopping_price_compare']
	nearby_hospital = by_id['nearby_hospital_phone_lookup']
	daily_service = by_id['daily_service_hours_lookup']

	assert 'amazon.com' in shopping.task_prompt.lower()
	assert shopping.frozen_task_parameters.get('product_query') == '无线鼠标'
	assert shopping.expected_primary_domain == 'amazon.com'
	assert any('amazon.com' in rule.lower() for rule in shopping.agent_recovery_rules)
	assert 'map.baidu.com' in nearby_hospital.task_prompt.lower()
	assert any('distinct' in criterion.lower() for criterion in nearby_hospital.success_criteria)
	assert nearby_hospital.primary_site_flow == 'baidu_maps'
	assert any('map.baidu.com' in rule.lower() for rule in nearby_hospital.agent_recovery_rules)
	hf = by_id['huggingface_model_constrained_selection']
	assert any('verified not visible' in criterion.lower() for criterion in hf.success_criteria)
	assert any('language=zh' in criterion.lower() or 'language=zho' in criterion.lower() for criterion in hf.success_criteria)
	assert any('do not keep re-clicking chinese' in rule.lower() for rule in hf.agent_recovery_rules)
	assert hf.required_fields
	assert 'map.baidu.com' in daily_service.task_prompt.lower()
	assert any('map.baidu.com' in rule.lower() for rule in daily_service.agent_recovery_rules)


def test_init_experiment_writes_task_and_human_baseline_templates(tmp_path):
	paths = init_experiment(tmp_path)

	task_cards = daily_task_models.load_json_model_list(paths['task_cards'], daily_task_models.TaskCard)
	human_runs = daily_task_models.load_json_model_list(paths['human_runs'], daily_task_models.HumanRunRecord)

	assert {card.id for card in task_cards} == set(get_main_tasks())
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


def test_task_tier_registry_is_stable():
	assert set(get_main_tasks()) == {
		'shopping_price_compare',
		'nearby_hospital_phone_lookup',
		'github_clean_issue_audit',
		'huggingface_model_constrained_selection',
	}
	assert get_stress_tasks() == ['complex_travel_package_booking']
	assert set(get_archived_tasks()) == {
		'shopping_cart_review',
		'paper_link_collection',
		'paper_bibtex_export',
		'daily_service_hours_lookup',
	}
	assert set(get_tasks_for_aggregate_metrics()) == set(get_main_tasks())


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
	assert 'shopping: amazon.com first' in prompt
	assert 'map lookups: map.baidu.com first' in prompt


def test_build_agent_task_prompt_includes_early_finish_rule():
	"""Early-finish should require evidence completeness before done, while still
	discouraging over-verification loops on screenshot-heavy pages.
	"""

	task = default_task_cards()[0]

	prompt = build_agent_task_prompt(task)

	assert 'Early-finish rule' in prompt
	assert 'extract_structured_data' in prompt
	assert 'map.baidu.com' in prompt
	assert 'Only call `done` after you have captured evidence for every hard Success criterion' in prompt
	assert 'State-changing action verification rule' in prompt
	assert 'If the post-condition cannot be verified after one re-location and one retry' in prompt
	assert 'The moment you have collected enough information' not in prompt


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
		'<current_step_focus>\nNavigate to map.baidu.com in a new tab.\n</current_step_focus>\n\n## Assumptions\nNetwork is CN.'
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
	assert 'EFFICIENCY RULES' in prompt
	assert 'extract_structured_data' in prompt
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
	assert (
		compute_navigator_overhead_ratio(
			navigator_enabled=False,
			executor_tokens=1000,
			navigator_cycle_tokens=200,
			navigator_initial_tokens=100,
		)
		== 0.0
	)
	assert (
		compute_navigator_overhead_ratio(
			navigator_enabled=True,
			executor_tokens=0,
			navigator_cycle_tokens=100,
			navigator_initial_tokens=50,
		)
		== 0.0
	)
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
	assert ex.temperature == 0.0
	assert ex.use_vision is False
	assert not nav.enabled


def test_experiment_preset_d_combines_deepseek_nav_and_doubao_executor():
	ex, nav = experiment_preset(DailyExperimentId.D)

	assert ex.backend == 'openai_compatible'
	assert ex.model == 'doubao-seed-2-0-pro-260215'
	assert ex.api_key_env == VOLCES_ARK_API_KEY_ENV
	assert ex.temperature == 0.0
	assert ex.use_vision is False
	assert nav.enabled and nav.backend == 'deepseek'
	assert nav.temperature == 0.0


def test_paper_experiment_ca_uses_deepseek_navigator_and_doubao_executor():
	ex, nav = paper_experiment_preset(PAPER_EXPERIMENT_CA)

	assert ex.model == 'doubao-seed-2-0-pro-260215'
	assert nav.enabled
	assert nav.backend == 'deepseek'
	assert nav.model == 'deepseek-chat'
	assert nav.temperature == 0.0


def test_experiment_run_flags_ca_enables_event_triggered_adaptive():
	import argparse

	args = argparse.Namespace(
		experiment=PAPER_EXPERIMENT_CA,
		continuous_navigation=False,
		navigator_replan_interval=None,
	)
	flags = experiment_run_flags_from_args(args)

	assert flags.continuous_navigation is True
	assert flags.replan_policy == 'event_triggered'
	assert flags.adaptive_replan_settings is not None
	assert flags.adaptive_replan_settings.replan_policy == 'event_triggered'
	assert flags.paper_condition == PAPER_CONDITION_ADAPTIVE


def test_build_configs_from_args_experiment_ca():
	import argparse

	args = argparse.Namespace(
		experiment=PAPER_EXPERIMENT_CA,
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

	assert exp_id == PAPER_EXPERIMENT_CA
	assert ex.model == 'doubao-seed-2-0-pro-260215'
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
		human_runs_path: [daily_task_models.HumanRunRecord(task_id=task.id, success_status='success').model_dump(mode='json')],
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
	from browser_use.experiments.daily_task_eval.run_csv import trajectory_lcs_similarity
	from browser_use.experiments.daily_task_eval.trajectory_metrics import (
		FILTERED_OUT_TOOLS,
		get_filtered_trajectory,
		trajectory_lcs_navigation,
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
		task_card_hash='hash-1',
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
		task_card_hash='hash-1',
		scenario_id='normal',
		run_status='completed',
		outcome_label='success',
		steps=human_steps,
		final_evidence=['ok'],
		criteria_checks=[{'criterion': 'ok', 'met': True}],
		trajectory_comparable='high',
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


def test_init_placeholder_human_record_is_not_started(tmp_path):
	paths = init_experiment(tmp_path)
	human_runs = daily_task_models.load_json_model_list(paths['human_runs'], daily_task_models.HumanRunRecord)
	assert human_runs
	for run in human_runs:
		assert run.task_card_hash
		assert run.run_status == 'not_started'
		assert run.outcome_label is None
		assert run.reference_eligible is False
		assert run.steps == []


def test_placeholder_human_record_not_reference_eligible():
	from browser_use.experiments.daily_task_eval.human_reference import is_human_reference_eligible

	run = daily_task_models.HumanRunRecord(
		task_id='paper_link_collection',
		run_status='not_started',
		outcome_label=None,
		reference_eligible=False,
		steps=[],
	)
	assert not is_human_reference_eligible(run)


def test_partial_success_human_run_not_reference_eligible():
	from browser_use.experiments.daily_task_eval.human_reference import is_human_reference_eligible

	run = daily_task_models.HumanRunRecord(
		task_id='shopping_price_compare',
		run_status='completed',
		outcome_label='partial_success',
		reference_eligible=False,
		steps=['search', 'click', 'done'],
		final_evidence=['商品1: Logitech 罗技 M185 无线鼠标 | JPY2,162'],
	)
	assert not is_human_reference_eligible(run)


def test_strict_validator_requires_all_criteria_met_for_reference_eligibility():
	run = daily_task_models.HumanRunRecord(
		task_id='nearby_hospital_phone_lookup',
		scenario_id='normal',
		run_status='completed',
		outcome_label='success',
		reference_eligible=True,
		final_evidence=['Hospital A phone: 555-0100'],
		trajectory_comparable='high',
		criteria_checks=[
			{'criterion': 'has_phone', 'met': True, 'evidence': '555-0100'},
			{'criterion': 'has_address', 'met': False, 'evidence': 'missing'},
		],
	)
	result = validate_reference_eligibility(run)
	assert result.eligible is False
	assert any(reason.startswith('criterion_failed:') for reason in result.reasons)


def test_reference_eligible_true_but_strict_false_emits_audit_warning():
	run = daily_task_models.HumanRunRecord(
		task_id='nearby_hospital_phone_lookup',
		scenario_id='normal',
		run_status='completed',
		outcome_label='success',
		reference_eligible=True,
		final_evidence=['Hospital A phone: 555-0100'],
		trajectory_comparable='high',
		criteria_checks=[{'criterion': 'has_phone', 'met': False, 'evidence': 'missing'}],
	)
	warnings = audit_human_run_record(run)
	assert any(w.code == 'reference_eligible_mismatch' for w in warnings)


def _fixture_task_card(task_id: str) -> TaskCard:
	fixtures = Path(__file__).resolve().parents[2] / 'examples' / 'evaluation' / 'fixtures' / 'task_cards.json'
	cards = daily_task_models.load_json_model_list(fixtures, TaskCard)
	return next(card for card in cards if card.id == task_id)


def test_huggingface_executor_subgoal_from_url_blocks_reclick_when_language_zh():
	url = 'https://huggingface.co/models?pipeline_tag=text-generation&library=pytorch&language=zh&sort=trending'
	subgoal = build_huggingface_executor_subgoal_from_url(url)
	assert subgoal is not None
	assert 'ACTIVE' in subgoal
	assert 'Do NOT click Chinese again' in subgoal
	assert 'set sort to Most Downloads' in subgoal


def test_huggingface_executor_subgoal_from_url_when_sort_downloads_ready():
	url = 'https://huggingface.co/models?pipeline_tag=text-generation&library=pytorch&language=zh&sort=downloads'
	subgoal = build_huggingface_executor_subgoal_from_url(url)
	assert subgoal is not None
	assert 'Do NOT click Chinese again' in subgoal
	assert 'Open the first model' in subgoal


def test_huggingface_adjudication_detects_language_zh_from_urls():
	task = _fixture_task_card('huggingface_model_constrained_selection')
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		duration_seconds=60.0,
		number_of_steps=3,
		is_done=True,
		success=True,
		final_result='Base model: not visible after checking Model Card and README.',
		urls=[
			'https://huggingface.co/models?pipeline_tag=text-generation&library=pytorch&language=zh&sort=downloads',
		],
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
	)
	adjudicated = adjudicate_agent_summary(task, summary)
	filter_check = next(c for c in adjudicated.criteria_checks if 'Chinese filters active' in c['criterion'])
	chinese_url_check = next(c for c in adjudicated.criteria_checks if 'URL language=zh/zho' in c['criterion'])
	sort_check = next(c for c in adjudicated.criteria_checks if 'Most Downloads' in c['criterion'])
	assert filter_check['met'] is True
	assert chinese_url_check['met'] is True
	assert 'chinese_url_active=True' in chinese_url_check['evidence']
	assert sort_check['met'] is True
	assert 'chinese:True' in filter_check['evidence']


def test_huggingface_adjudication_url_language_zh_counts_even_when_text_denies_chinese():
	task = _fixture_task_card('huggingface_model_constrained_selection')
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		duration_seconds=60.0,
		number_of_steps=8,
		is_done=False,
		success=False,
		final_result='Chinese filter remains inactive because results still show English models.',
		urls=[
			'https://huggingface.co/models?pipeline_tag=text-generation&library=pytorch&language=zh&sort=trending',
		],
		action_names=['navigate', 'click', 'click'],
		history_path='h.json',
		conversation_path='c.json',
	)
	adjudicated = adjudicate_agent_summary(task, summary)
	chinese_check = next(c for c in adjudicated.criteria_checks if 'URL language=zh/zho' in c['criterion'])
	assert chinese_check['met'] is True
	assert 'chinese_url_active=True' in chinese_check['evidence']
	assert 'chinese:True' in chinese_check['evidence']


def test_huggingface_adjudication_chinese_from_language_zho_url():
	task = _fixture_task_card('huggingface_model_constrained_selection')
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		duration_seconds=60.0,
		number_of_steps=2,
		is_done=False,
		success=False,
		final_result='',
		urls=['https://huggingface.co/models?pipeline_tag=text-generation&library=pytorch&language=zho&sort=trending'],
		action_names=['navigate', 'click'],
		history_path='h.json',
		conversation_path='c.json',
	)
	adjudicated = adjudicate_agent_summary(task, summary)
	filter_check = next(c for c in adjudicated.criteria_checks if 'Chinese filters active' in c['criterion'])
	chinese_url_check = next(c for c in adjudicated.criteria_checks if 'URL language=zh/zho' in c['criterion'])
	assert filter_check['met'] is True
	assert chinese_url_check['met'] is True
	assert 'chinese_url_active=True' in chinese_url_check['evidence']
	assert 'chinese:True' in filter_check['evidence']


def test_hospital_entry_parser_accepts_facility_name_and_phone_number_labels():
	from browser_use.experiments.daily_task_eval.runner import _collect_hospital_entries

	text = """### 3 Distinct Medical Facilities Near 坂田街道:
1. **Facility Name**: 坂田人民医院
   - **Address**: 广东省深圳市龙岗区坂田街道坂田路552号
   - **Phone Number**: 0755-89504000
2. **Facility Name**: 深圳市龙岗区人民医院(坂田院区)
   - **Address**: 广东省深圳市龙岗区环城北路
   - **Phone Number**: 0755-25566770
3. **Facility Name**: 深圳肖传国医院
   - **Address**: 龙岗区雪象村4035号
   - **Phone Number**: 0755-89356688 / 0755-89589898
"""
	entries = _collect_hospital_entries(text)
	assert len(entries) == 3
	assert all(e['name'] and e['phone'] and e['address'] for e in entries)
	assert entries[0]['phone'] == '0755-89504000'


def test_hospital_entry_parser_splits_numbered_list_sections():
	from browser_use.experiments.daily_task_eval.runner import _collect_hospital_entries

	text = """1. **名称：坂田人民医院**
   - 地址：坂田路552号
   - 联系电话：0755-89504000
2. **名称：龙岗区人民医院**
   - 地址：环城北路90号
   - 联系电话：0755-25566770
3. **名称：肖传国医院**
   - 地址：雪象村4035号
   - 联系电话：0755-89356688
"""
	entries = _collect_hospital_entries(text)
	assert len(entries) == 3
	assert len({e['name'] for e in entries}) == 3


def test_hospital_adjudication_strict_passes_for_english_facility_format():
	task = _fixture_task_card('nearby_hospital_phone_lookup')
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		duration_seconds=60.0,
		number_of_steps=5,
		is_done=True,
		success=True,
		final_result="""1. **Facility Name**: 坂田人民医院
   - **Address**: 坂田路552号
   - **Phone Number**: 0755-89504000
2. **Facility Name**: 龙岗区人民医院
   - **Address**: 环城北路90号
   - **Phone Number**: 0755-25566770
3. **Facility Name**: 肖传国医院
   - **Address**: 雪象村4035号
   - **Phone Number**: 0755-89356688
""",
		urls=['https://map.baidu.com/search/hospital'],
		action_names=['navigate', 'done'],
		history_path='h.json',
		conversation_path='c.json',
	)
	adjudicated = adjudicate_agent_summary(task, summary)
	assert adjudicated.strict_success is True
	assert adjudicated.adjudicated_outcome_label == 'success'


def test_github_adjudication_accepts_comment_activity_thread_without_snippet_keyword():
	task = _fixture_task_card('github_clean_issue_audit')
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		duration_seconds=60.0,
		number_of_steps=8,
		is_done=True,
		success=True,
		final_result=(
			'Oldest open bug issue: #3912, title: browser-use Windows Issue. '
			'The start of the comment/activity thread is displayed, with the first entries showing '
			'the issue author adding the bug label on Jan 22.'
		),
		urls=['https://github.com/browser-use/browser-use/issues/3912'],
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
	)
	adjudicated = adjudicate_agent_summary(task, summary)
	comment_check = next(c for c in adjudicated.criteria_checks if 'first comment' in c['criterion'])
	assert comment_check['met'] is True
	assert adjudicated.strict_success is True


def test_github_adjudication_accepts_comments_activity_section_with_label_addition():
	task = _fixture_task_card('github_clean_issue_audit')
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:01:00+00:00',
		duration_seconds=60.0,
		number_of_steps=8,
		is_done=True,
		success=True,
		final_result=(
			'Oldest open bug issue: #3912, titled browser-use Windows Issue, created by ZanderRuss on Jan 22. '
			'The issue detail page displays the full issue body and the start of the comments/activity section, '
			'including the initial label addition event and related commits referencing this issue.'
		),
		urls=['https://github.com/browser-use/browser-use/issues/3912'],
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
	)
	adjudicated = adjudicate_agent_summary(task, summary)
	assert adjudicated.strict_success is True


def test_huggingface_agent_prompt_warns_against_reclicking_chinese_when_language_zh():
	task = _fixture_task_card('huggingface_model_constrained_selection')
	prompt = build_agent_task_prompt(task)
	assert 'language=zh' in prompt
	assert 'do NOT click Chinese again' in prompt


def test_huggingface_verified_not_visible_can_pass_strict_eligibility():
	run = daily_task_models.HumanRunRecord(
		task_id='huggingface_model_constrained_selection',
		scenario_id='normal',
		run_status='completed',
		outcome_label='success',
		reference_eligible=False,
		final_evidence=[
			'Base model: not visible after checking Model Card metadata and README visible region.',
		],
		trajectory_comparable='high',
		criteria_checks=[
			{
				'criterion': 'Model Card shows Base model name',
				'met': False,
				'field_visibility': 'verified_not_visible',
				'evidence': 'Model Card metadata and README checked; field not visible',
			}
		],
	)
	result = validate_reference_eligibility(run)
	assert result.eligible is True


def test_completed_success_with_evidence_and_high_comparability_is_reference():
	from browser_use.experiments.daily_task_eval.human_reference import is_human_reference_eligible
	from browser_use.experiments.daily_task_eval.reference_comparison import get_reference_human_runs

	eligible = daily_task_models.HumanRunRecord(
		task_id='nearby_hospital_phone_lookup',
		scenario_id='normal',
		run_status='completed',
		outcome_label='success',
		reference_eligible=True,
		steps=['navigate', 'click', 'extract', 'done'],
		final_evidence=['Hospital A phone: 555-0100'],
		criteria_checks=[{'criterion': 'Hospital phone number extracted', 'met': True}],
		trajectory_comparable='high',
	)
	assert is_human_reference_eligible(eligible)
	assert get_reference_human_runs([eligible], task_id=eligible.task_id, scenario_id=eligible.scenario_id) == [eligible]

	ineligible = eligible.model_copy(update={'trajectory_comparable': 'low'})
	assert not is_human_reference_eligible(ineligible)
	assert get_reference_human_runs([eligible, ineligible], task_id=eligible.task_id, scenario_id=eligible.scenario_id) == [
		eligible
	]


def test_human_reference_csv_fields_present_without_breaking_lcs_row(tmp_path):
	from browser_use.experiments.daily_task_eval.run_csv import (
		AGENT_RUN_CSV_HEADERS,
		append_agent_run_csv_row,
		build_agent_run_csv_row,
	)

	task = default_task_cards()[0]
	summary = daily_task_models.AgentRunSummary(
		task_id=task.id,
		scenario_id='normal',
		task_category=task.category,
		experiment_id='C',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:10+00:00',
		success=True,
		is_done=True,
		duration_seconds=10,
		number_of_steps=3,
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
	)
	human = daily_task_models.HumanRunRecord(
		task_id=task.id,
		scenario_id='normal',
		run_status='completed',
		outcome_label='partial_success',
		steps=['navigate', 'extract', 'done'],
		final_evidence=['（待补充）'],
		milestone_outcomes=[{'milestone': 'open_site', 'reached': True}, {'milestone': 'submit', 'reached': False}],
	)
	row = build_agent_run_csv_row(method='C', task=task, summary=summary, human=human)
	assert row['trajectory_lcs_similarity'] is None
	assert row['human_reference_eligible'] is False
	assert row['human_outcome_label'] == 'partial_success'
	assert row['human_milestone_coverage'] == pytest.approx(0.5)

	for col in (
		'human_reference_eligible',
		'human_outcome_label',
		'human_trajectory_comparable',
		'human_route_relation',
		'human_final_domain',
		'human_cross_site_fallback',
		'human_milestone_coverage',
	):
		assert col in AGENT_RUN_CSV_HEADERS

	csv_dir = tmp_path / 'csv_out'
	path = append_agent_run_csv_row(csv_dir, method='C', task=task, summary=summary, human=human)
	header = path.read_text(encoding='utf-8').splitlines()[0].split(',')
	for col in (
		'human_reference_eligible',
		'human_outcome_label',
		'human_milestone_coverage',
		'trajectory_lcs_similarity',
		'raw_lcs_mean',
		'canonical_lcs_mean',
		'navigation_lcs_mean',
		'comparison_status',
	):
		assert col in header


def test_task_config_summary_excludes_stress_and_archived_by_default(tmp_path):
	from browser_use.experiments.daily_task_eval.run_csv import AGENT_RUN_CSV_HEADERS, export_task_config_summary_csv

	csv_dir = tmp_path / 'csv_out'
	csv_dir.mkdir(parents=True, exist_ok=True)
	path = csv_dir / 'exp-C_runs.csv'
	with path.open('w', encoding='utf-8', newline='') as f:
		import csv

		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS)
		writer.writeheader()
		base = {
			'method': 'C',
			'scenario_id': 'normal',
			'task_category': 'read_only_query',
			'success': 'true',
			'number_of_steps': '5',
			'duration_seconds': '10',
			'tokens_executor': '100',
			'comparison_status': 'comparable',
			'raw_lcs_mean': '0.9',
			'canonical_lcs_mean': '0.9',
			'navigation_lcs_mean': '0.9',
		}
		writer.writerow({**base, 'task_id': 'shopping_price_compare'})
		writer.writerow({**base, 'task_id': 'complex_travel_package_booking'})
		writer.writerow({**base, 'task_id': 'shopping_cart_review'})

	out = export_task_config_summary_csv(csv_dir, csv_dir / 'task_config_summary.csv')
	text = out.read_text(encoding='utf-8')
	assert 'shopping_price_compare' in text
	assert 'complex_travel_package_booking' not in text
	assert 'shopping_cart_review' not in text


def test_aggregate_method_metrics_writes_stress_exclusion_note(tmp_path):
	from browser_use.experiments.daily_task_eval.run_csv import AGENT_RUN_CSV_HEADERS, aggregate_method_metrics

	csv_dir = tmp_path / 'csv_out'
	csv_dir.mkdir(parents=True, exist_ok=True)
	path = csv_dir / 'exp-C_runs.csv'
	with path.open('w', encoding='utf-8', newline='') as f:
		import csv

		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS)
		writer.writeheader()
		writer.writerow({'method': 'C', 'task_id': 'shopping_price_compare', 'scenario_id': 'normal', 'duration_seconds': '10'})
		writer.writerow(
			{
				'method': 'C',
				'task_id': 'complex_travel_package_booking',
				'scenario_id': 'normal',
				'duration_seconds': '999',
			}
		)
	_, out_path = aggregate_method_metrics(csv_dir, csv_dir)
	assert out_path.exists()
	note = (csv_dir / 'stress_case_note.txt').read_text(encoding='utf-8')
	assert 'Stress-case results: excluded from main aggregate metrics' in note


def test_aggregate_method_metrics_raises_when_main_tier_missing(tmp_path):
	from browser_use.experiments.daily_task_eval.run_csv import AGENT_RUN_CSV_HEADERS, aggregate_method_metrics

	csv_dir = tmp_path / 'csv_out'
	csv_dir.mkdir(parents=True, exist_ok=True)
	path = csv_dir / 'exp-C_runs.csv'
	with path.open('w', encoding='utf-8', newline='') as f:
		import csv

		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS)
		writer.writeheader()
		writer.writerow({'method': 'C', 'task_id': 'complex_travel_package_booking', 'scenario_id': 'normal'})
	with pytest.raises(ValueError, match='No main-tier task data found'):
		aggregate_method_metrics(csv_dir, csv_dir)


# --- Trajectory metrics (J1–J7) ---


def test_action_normalization_aliases_and_unknown_tokens():
	from browser_use.experiments.daily_task_eval.trajectory_metrics import normalize_action_token

	assert normalize_action_token('go_to_url') == 'navigate'
	assert normalize_action_token('navigate') == 'navigate'
	assert normalize_action_token('input_text') == 'input'
	assert normalize_action_token('send_keys') == 'input'
	assert normalize_action_token('extract_structured_data') == 'extract'
	assert normalize_action_token('custom_action_a') == 'unknown:custom_action_a'
	assert normalize_action_token('custom_action_b') == 'unknown:custom_action_b'
	assert normalize_action_token('custom_action_a') != normalize_action_token('custom_action_b')


def test_three_layer_trajectories():
	from browser_use.experiments.daily_task_eval.trajectory_metrics import (
		canonical_trajectory,
		navigation_trajectory,
		raw_trajectory,
	)

	actions = ['go_to_url', 'input_text', 'scroll', 'extract', 'find_text', 'search', 'done', 'custom_action_a']
	assert raw_trajectory(actions) == [
		'go_to_url',
		'input_text',
		'scroll',
		'extract',
		'find_text',
		'search',
		'done',
		'custom_action_a',
	]
	assert canonical_trajectory(actions) == [
		'navigate',
		'input',
		'scroll',
		'extract',
		'browser_find',
		'search',
		'done',
		'unknown:custom_action_a',
	]
	assert navigation_trajectory(actions) == ['navigate', 'input', 'search', 'done']


def test_lcs_boundary_conditions_and_canonical_boost():
	from browser_use.experiments.daily_task_eval.trajectory_metrics import (
		compare_trajectories,
		normalized_lcs_score,
		trajectory_lcs_similarity,
	)

	assert normalized_lcs_score([], []) is None
	assert normalized_lcs_score(['navigate'], []) == 0.0
	assert trajectory_lcs_similarity(['navigate'], ['navigate']) == 1.0
	pair = compare_trajectories(['go_to_url', 'done'], ['navigate', 'done'])
	assert pair.canonical_lcs == 1.0
	nav = compare_trajectories(
		['navigate', 'wait', 'click', 'done'],
		['navigate', 'click', 'done'],
	)
	assert nav.navigation_lcs == 1.0


def test_success_without_evidence_not_reference():
	from browser_use.experiments.daily_task_eval.human_reference import is_human_reference_eligible

	run = daily_task_models.HumanRunRecord(
		task_id='t',
		run_status='completed',
		outcome_label='success',
		steps=['navigate', 'done'],
		final_evidence=[],
		criteria_checks=[],
		trajectory_comparable='high',
	)
	assert not is_human_reference_eligible(run)


def test_multi_reference_aggregation():
	from browser_use.experiments.daily_task_eval.reference_comparison import compare_agent_to_human_references

	refs = [
		daily_task_models.HumanRunRecord(
			task_id='t',
			scenario_id='normal',
			run_status='completed',
			outcome_label='success',
			steps=['navigate', 'click', 'done'],
			final_evidence=['ok-a'],
			criteria_checks=[{'criterion': 'task complete', 'met': True}],
			trajectory_comparable='high',
		),
		daily_task_models.HumanRunRecord(
			task_id='t',
			scenario_id='normal',
			run_status='completed',
			outcome_label='success',
			steps=['navigate', 'input', 'done'],
			final_evidence=['ok-b'],
			criteria_checks=[{'criterion': 'task complete', 'met': True}],
			trajectory_comparable='high',
		),
		daily_task_models.HumanRunRecord(
			task_id='t',
			scenario_id='normal',
			run_status='not_started',
			steps=[],
		),
	]
	agent = daily_task_models.AgentRunSummary(
		task_id='t',
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:10+00:00',
		success=True,
		is_done=True,
		duration_seconds=10,
		number_of_steps=3,
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
	)
	result = compare_agent_to_human_references(agent, refs)
	assert result.comparison_status == 'comparable'
	assert result.human_reference_count == 2
	assert result.raw_lcs_mean == pytest.approx((1.0 + 2 / 3) / 2)
	assert result.raw_lcs_min == pytest.approx(2 / 3)
	assert result.raw_lcs_max == 1.0

	low_agent = agent.model_copy(update={'trajectory_comparable': 'low'})
	low_result = compare_agent_to_human_references(low_agent, refs)
	assert low_result.comparison_status == 'agent_route_not_comparable'
	assert low_result.raw_lcs_mean is None

	partial_refs = [
		refs[0].model_copy(update={'trajectory_comparable': 'partial'}),
		refs[1],
	]
	partial_result = compare_agent_to_human_references(agent, partial_refs)
	assert partial_result.comparison_status == 'partially_comparable'


def test_travel_stress_standalone_lcs_allowed_but_excluded_from_aggregate_tables(tmp_path):
	from browser_use.experiments.daily_task_eval.reference_comparison import compare_agent_to_human_references
	from browser_use.experiments.daily_task_eval.run_csv import AGENT_RUN_CSV_HEADERS, export_task_config_summary_csv

	human = daily_task_models.HumanRunRecord(
		task_id='complex_travel_package_booking',
		scenario_id='normal',
		run_status='completed',
		outcome_label='success',
		final_evidence=['checkout page visible'],
		trajectory_comparable='high',
		criteria_checks=[{'criterion': 'travel_complete', 'met': True, 'evidence': 'ok'}],
		steps=['navigate', 'click', 'done'],
	)
	agent = daily_task_models.AgentRunSummary(
		task_id='complex_travel_package_booking',
		scenario_id='normal',
		started_at='2026-01-01T00:00:00+00:00',
		finished_at='2026-01-01T00:00:10+00:00',
		success=True,
		is_done=True,
		duration_seconds=10,
		number_of_steps=3,
		action_names=['navigate', 'click', 'done'],
		history_path='h.json',
		conversation_path='c.json',
		trajectory_comparable='high',
	)
	cmp = compare_agent_to_human_references(agent, [human])
	assert cmp.human_reference_count == 1
	assert cmp.raw_lcs_mean == 1.0

	csv_dir = tmp_path / 'csv_out'
	csv_dir.mkdir(parents=True, exist_ok=True)
	with (csv_dir / 'exp-C_runs.csv').open('w', encoding='utf-8', newline='') as f:
		import csv

		writer = csv.DictWriter(f, fieldnames=AGENT_RUN_CSV_HEADERS)
		writer.writeheader()
		writer.writerow(
			{
				'method': 'C',
				'task_id': 'complex_travel_package_booking',
				'scenario_id': 'normal',
				'success': 'true',
				'comparison_status': 'comparable',
				'raw_lcs_mean': '1.0',
				'canonical_lcs_mean': '1.0',
				'navigation_lcs_mean': '1.0',
			}
		)
	with pytest.raises(ValueError, match='No main-tier task rows found'):
		export_task_config_summary_csv(csv_dir, csv_dir / 'task_config_summary.csv')


def test_human_human_reference_set_stats():
	from browser_use.experiments.daily_task_eval.reference_comparison import compare_human_reference_set

	def ref(steps: list[str]) -> daily_task_models.HumanRunRecord:
		return daily_task_models.HumanRunRecord(
			task_id='t',
			scenario_id='normal',
			run_status='completed',
			outcome_label='success',
			steps=steps,
			final_evidence=['evidence'],
			criteria_checks=[{'criterion': 'task complete', 'met': True}],
			trajectory_comparable='high',
		)

	assert compare_human_reference_set([]).pair_count == 0
	assert compare_human_reference_set([ref(['navigate', 'done'])]).pair_count == 0
	stats = compare_human_reference_set(
		[
			ref(['navigate', 'click', 'done']),
			ref(['navigate', 'input', 'done']),
			ref(['navigate', 'done']),
		]
	)
	assert stats.reference_count == 3
	assert stats.pair_count == 3
	assert stats.raw_lcs_mean is not None


def test_migrate_human_runs_script_summary(tmp_path):
	import subprocess
	import sys

	src = tmp_path / 'human_runs.json'
	src.write_text(
		json.dumps(
			[
				{
					'task_id': 'paper_link_collection',
					'scenario_id': 'normal',
					'steps': ['Replace this with the exact manual steps you took.'],
					'run_status': 'completed',
					'outcome_label': 'success',
				},
				{
					'task_id': 'complex_travel_package_booking',
					'scenario_id': 'normal',
					'steps': ['navigate', 'done'],
					'run_status': 'completed',
					'outcome_label': 'success',
				},
			]
		),
		encoding='utf-8',
	)
	out = tmp_path / 'human_runs.migrated.json'
	script = Path(__file__).resolve().parents[2] / 'scripts' / 'migrate_human_runs.py'
	proc = subprocess.run(
		[sys.executable, str(script), str(src), '--output', str(out)],
		capture_output=True,
		text=True,
		check=True,
	)
	assert 'total_records: 2' in proc.stdout
	migrated = json.loads(out.read_text(encoding='utf-8'))
	assert migrated[0]['run_status'] == 'not_started'
	assert migrated[0]['steps'] == []
	assert migrated[1]['outcome_label'] == 'partial_success'
	assert migrated[1]['trajectory_comparable'] == 'low'


def test_deepseek_extract_usage_maps_openai_compatible_response():
	from types import SimpleNamespace

	from browser_use.llm.deepseek.chat import _extract_usage

	resp = SimpleNamespace(
		usage=SimpleNamespace(
			prompt_tokens=100,
			completion_tokens=50,
			total_tokens=150,
			prompt_tokens_details=SimpleNamespace(cached_tokens=10),
		)
	)
	usage = _extract_usage(resp)
	assert usage is not None
	assert usage.prompt_tokens == 100
	assert usage.completion_tokens == 50
	assert usage.total_tokens == 150
	assert usage.prompt_cached_tokens == 10
	assert _extract_usage(SimpleNamespace(usage=None)) is None
