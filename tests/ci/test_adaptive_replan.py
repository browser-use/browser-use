"""Unit tests for R-A event-triggered adaptive replan controller."""

from browser_use.experiments.daily_task_eval.adaptive_replan import (
	AdaptiveReplanController,
	AdaptiveReplanSettings,
	AdaptiveTriggerType,
	build_state_fingerprint,
	default_adaptive_replan_settings,
)


def test_default_settings_use_event_triggered_policy():
	settings = default_adaptive_replan_settings()
	assert settings.replan_policy == 'event_triggered'
	assert settings.scheduled_replan_interval is None
	assert settings.no_progress_window == 3
	assert settings.replan_cooldown_steps == 5
	assert settings.max_total_adaptive_replans == 2


def test_state_fingerprint_preserves_semantic_github_query_params():
	fp_a = build_state_fingerprint(
		url='https://github.com/org/repo/issues?q=is%3Aopen+label%3Abug&sort=created-asc',
		page_title='Issues',
		dom_snippet=None,
	)
	fp_b = build_state_fingerprint(
		url='https://github.com/org/repo/issues?q=is%3Aopen+label%3Afeature',
		page_title='Issues',
		dom_snippet=None,
	)
	assert fp_a != fp_b


def test_phase_transition_triggers_once_for_github_gate():
	ctrl = AdaptiveReplanController(
		task_id='github_clean_issue_audit',
		initial_plan='opening plan',
		settings=AdaptiveReplanSettings(),
	)
	step = {
		'model_output': {'action': [{'click': {'index': 1}}]},
		'result': [],
		'state_message': 'label:bug is:open sort oldest',
	}
	url = 'https://github.com/foo/bar/issues?q=is%3Aopen+label%3Abug&sort=created-asc'
	stable_dom = 'x' * 120 + ' label:bug is:open sort oldest issues list'
	ctrl.observe_completed_step(
		step=1,
		model_output=step['model_output'],
		results=[],
		url=url,
		page_title='Issues',
		dom_snippet=stable_dom,
		state_message=step['state_message'],
	)
	should, trigger_type, reason = ctrl.evaluate_before_step(current_step=2, agent_done=False)
	assert should is True
	assert trigger_type == AdaptiveTriggerType.PHASE
	assert 'M4_open_oldest_sort' in reason
	ctrl.record_replan(step=2, trigger_type=trigger_type, trigger_reason=reason)
	should2, _, _ = ctrl.evaluate_before_step(current_step=3, agent_done=False)
	assert should2 is False


def test_transient_timeout_does_not_count_as_friction_on_first_occurrence():
	ctrl = AdaptiveReplanController(
		task_id='shopping_price_compare',
		initial_plan='plan',
		settings=AdaptiveReplanSettings(no_progress_window=3),
	)
	stable_dom = 'x' * 120 + ' results products listing'
	ctrl.observe_completed_step(
		step=1,
		model_output={'action': [{'click': {'index': 1}}]},
		results=[{'error': 'Step timed out after 150 seconds'}],
		url='https://amazon.com/s?k=mouse',
		page_title='Results',
		dom_snippet=stable_dom,
		state_message='results',
	)
	assert ctrl._consecutive_failure_signature_count == 0
	assert ctrl._meaningful_without_progress == 0
	assert ctrl.metrics.environmental_wait_steps == 1


def test_pending_network_blocks_recovery_trigger():
	ctrl = AdaptiveReplanController(
		task_id='shopping_price_compare',
		initial_plan='plan',
		settings=AdaptiveReplanSettings(no_progress_window=2, replan_cooldown_steps=0),
	)
	stable_dom = 'x' * 120 + ' results products listing'
	for step in range(1, 4):
		ctrl.observe_completed_step(
			step=step,
			model_output={'action': [{'click': {'index': step}}]},
			results=[],
			url=f'https://amazon.com/s?k=mouse&p={step}',
			page_title='Results',
			dom_snippet=stable_dom,
			state_message='results',
			pending_network_count=2 if step == 3 else 0,
		)
	should, _, reason = ctrl.evaluate_before_step(current_step=4, agent_done=False)
	assert should is False
	assert reason == 'page_not_ready'


def test_wait_action_is_environmental_not_no_progress():
	ctrl = AdaptiveReplanController(
		task_id='shopping_price_compare',
		initial_plan='plan',
		settings=AdaptiveReplanSettings(no_progress_window=2),
	)
	stable_dom = 'x' * 120
	for step in range(1, 4):
		ctrl.observe_completed_step(
			step=step,
			model_output={'action': [{'wait': {'seconds': 2}}]},
			results=[],
			url='https://amazon.com/s?k=mouse',
			page_title='Results',
			dom_snippet=stable_dom,
		)
	assert ctrl._meaningful_without_progress == 0


def test_recovery_no_progress_respects_cooldown():
	ctrl = AdaptiveReplanController(
		task_id='shopping_price_compare',
		initial_plan='plan',
		settings=AdaptiveReplanSettings(no_progress_window=3, replan_cooldown_steps=5),
	)
	stable_dom = 'x' * 120 + ' results products listing'
	for step in range(1, 5):
		ctrl.observe_completed_step(
			step=step,
			model_output={'action': [{'click': {'index': step}}]},
			results=[],
			url=f'https://amazon.com/s?k=mouse&page={step}',
			page_title='Results',
			dom_snippet=stable_dom,
			state_message='results',
		)
	should, trigger_type, _ = ctrl.evaluate_before_step(current_step=5, agent_done=False)
	assert should is True
	assert trigger_type == AdaptiveTriggerType.NO_PROGRESS
	ctrl.record_replan(step=5, trigger_type=trigger_type, trigger_reason='no progress')
	ctrl.observe_completed_step(
		step=6,
		model_output={'action': [{'click': {'index': 6}}]},
		results=[],
		url='https://amazon.com/s?k=mouse&page=6',
		page_title='Results',
		dom_snippet=stable_dom,
		state_message='results',
	)
	should2, _, reason2 = ctrl.evaluate_before_step(current_step=7, agent_done=False)
	assert should2 is False
	assert reason2 == 'cooldown'


def test_max_two_adaptive_replans_per_run():
	ctrl = AdaptiveReplanController(
		task_id='github_clean_issue_audit',
		initial_plan='plan',
		settings=AdaptiveReplanSettings(replan_cooldown_steps=0),
	)
	ctrl._phase_replans = 1
	ctrl._recovery_replans = 1
	ctrl._last_replan_step = 0
	ctrl._meaningful_since_replan = 10
	should, _, reason = ctrl.evaluate_before_step(current_step=20, agent_done=False)
	assert should is False
	assert reason == 'max_total_replans'
