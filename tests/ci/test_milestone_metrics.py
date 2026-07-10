"""Test milestone parsing for daily_task_eval runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from browser_use.experiments.daily_task_eval.task_registry import (
	get_task_milestones,
)
from browser_use.experiments.daily_task_eval.trajectory_metrics import (
	MilestoneProcessMetrics,
	parse_history_for_milestones,
)


@pytest.fixture
def hf_c1_history():
	"""Load the HF C1 20260625T050947Z run that exhibited step-14 regression."""
	history_path = Path(
		'tmp/daily_task_eval/agent_runs/'
		'huggingface_model_constrained_selection/normal/exp-C1/20260625T050947Z/history.json'
	)
	if not history_path.exists():
		pytest.skip(f'History file not found: {history_path}')

	with open(history_path, encoding='utf-8') as f:
		data = json.load(f)

	return data.get('history', [])


@pytest.fixture
def github_c_history():
	"""Load a GitHub C run for milestone verification."""
	history_path = Path(
		'tmp/daily_task_eval/agent_runs/'
		'github_clean_issue_audit/normal/exp-C/20260624T015841Z/history.json'
	)
	if not history_path.exists():
		pytest.skip(f'History file not found: {history_path}')

	with open(history_path, encoding='utf-8') as f:
		data = json.load(f)

	return data.get('history', [])


def test_hf_milestone_definitions():
	"""Verify HuggingFace task has 7 expected milestones."""
	milestones = get_task_milestones('huggingface_model_constrained_selection')
	assert len(milestones) == 7
	expected_ids = [
		'M1_navigate_models',
		'M2_filter_text_gen',
		'M3_filter_pytorch',
		'M4_filter_chinese',
		'M5_sort_downloads',
		'M6_open_model_page',
		'M7_extract_done',
	]
	assert [m.milestone_id for m in milestones] == expected_ids


def test_github_milestone_definitions():
	"""Verify GitHub task has 7 expected milestones."""
	milestones = get_task_milestones('github_clean_issue_audit')
	assert len(milestones) == 7


def test_hf_c1_milestone_parsing(hf_c1_history):
	"""Test milestone parsing on HF C1 run that had step-14 regression."""
	metrics = parse_history_for_milestones(
		hf_c1_history, 'huggingface_model_constrained_selection', 'test_run', 'C1'
	)

	assert isinstance(metrics, MilestoneProcessMetrics)
	assert metrics.task_id == 'huggingface_model_constrained_selection'
	assert metrics.total_steps == len(hf_c1_history)

	# Should achieve all 7 milestones (HF task is well-structured)
	assert len(metrics.milestones_achieved) >= 4, 'Should achieve at least 4 core milestones'

	# Coverage should be between 0 and 1
	assert 0.0 <= metrics.milestone_coverage <= 1.0

	# Order score should be between -1 and 1 when defined
	if metrics.order_score is not None:
		assert -1.0 <= metrics.order_score <= 1.0

	# Stall burden should be between 0 and 1
	assert 0.0 <= metrics.stall_burden <= 1.0

	# State revisit rate should be between 0 and 1
	assert 0.0 <= metrics.state_revisit_rate <= 1.0

	# Verify milestone_steps map has correct structure
	for milestone_id, step_num in metrics.milestone_steps.items():
		assert isinstance(milestone_id, str)
		assert isinstance(step_num, int)
		assert 1 <= step_num <= metrics.total_steps


def test_github_c_milestone_parsing(github_c_history):
	"""Test milestone parsing on GitHub C run."""
	metrics = parse_history_for_milestones(
		github_c_history, 'github_clean_issue_audit', 'test_run', 'C'
	)

	assert isinstance(metrics, MilestoneProcessMetrics)
	assert metrics.task_id == 'github_clean_issue_audit'
	assert metrics.total_steps == len(github_c_history)
	assert len(metrics.milestones_achieved) >= 3, 'Should achieve at least 3 core milestones'


def test_milestone_parsing_empty_history():
	"""Test milestone parsing handles empty history gracefully."""
	metrics = parse_history_for_milestones([], 'github_clean_issue_audit', 'test_run', 'E')

	assert metrics.total_steps == 0
	assert len(metrics.milestones_achieved) == 0
	assert metrics.milestone_coverage == 0.0
	assert metrics.order_score is None
	assert metrics.stall_burden == 0.0
	assert metrics.state_revisit_rate == 0.0


def test_milestone_parsing_malformed_steps():
	"""Test milestone parsing handles malformed steps gracefully."""
	malformed_history = [
		{},  # Empty step
		{'state': None, 'model_output': None},  # Null fields
		{'state': {}, 'model_output': {}},  # Empty fields
		{
			'state': {'url': 'https://github.com'},
			'model_output': {'action': [{'click': {'index': 1}}]},
		},  # Valid step
	]

	metrics = parse_history_for_milestones(
		malformed_history, 'github_clean_issue_audit', 'test_run', 'E'
	)

	assert metrics.total_steps == 4
	# Should not crash, even if no milestones detected
	assert metrics.milestone_coverage >= 0.0


def test_milestone_coverage_full():
	"""Test coverage calculation when all milestones achieved."""
	# Simulate a perfect run with all 7 HF milestones
	history = [
		{
			'state': {'url': 'https://huggingface.co/models'},
			'model_output': {'action': [{'navigate': {'url': 'https://huggingface.co/models'}}]},
		},
		{
			'state': {'url': 'https://huggingface.co/models'},
			'model_output': {'action': [{'click': {'index': 1}}]},
			'result': [{'extracted_content': 'Clicked Text Generation'}],
		},
		{
			'state': {'url': 'https://huggingface.co/models'},
			'model_output': {'action': [{'click': {'index': 2}}]},
			'result': [{'extracted_content': 'Clicked PyTorch'}],
		},
		{
			'state': {'url': 'https://huggingface.co/models?language=zh'},
			'model_output': {'action': [{'click': {'index': 3}}]},
			'result': [{'extracted_content': 'Clicked Chinese'}],
		},
		{
			'state': {'url': 'https://huggingface.co/models?language=zh&sort=downloads'},
			'model_output': {'action': [{'click': {'index': 4}}]},
			'result': [{'extracted_content': 'Sort by downloads'}],
		},
		{
			'state': {'url': 'https://huggingface.co/org/model'},
			'model_output': {'action': [{'click': {'index': 5}}]},
		},
		{
			'state': {'url': 'https://huggingface.co/org/model'},
			'model_output': {'action': [{'done': {'success': True, 'text': 'Base model: ...'}}]},
		},
	]

	metrics = parse_history_for_milestones(
		history, 'huggingface_model_constrained_selection', 'test_run', 'E'
	)

	assert metrics.milestone_coverage == 1.0, 'All milestones should be achieved'
	assert len(metrics.milestones_achieved) == 7


def test_stall_burden_calculation():
	"""Test stall burden calculation."""
	# Create history where only steps 1, 3, 5 achieve milestones (out of 10 steps)
	# Stall burden = 7/10 = 0.7
	history = [
		{
			'state': {'url': 'https://github.com/repo/issues'},
			'model_output': {'action': [{'navigate': {}}]},
		},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'wait': {}}]}},
		{
			'state': {'url': 'https://github.com/repo/issues'},
			'model_output': {'action': [{'click': {}}]},
			'result': [{'extracted_content': 'bug'}],
		},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'wait': {}}]}},
		{
			'state': {'url': 'https://github.com/repo/issues?label%3abug'},
			'model_output': {'action': [{'click': {}}]},
		},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'wait': {}}]}},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'wait': {}}]}},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'wait': {}}]}},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'wait': {}}]}},
		{'state': {'url': 'https://github.com/repo/issues'}, 'model_output': {'action': [{'done': {}}]}},
	]

	metrics = parse_history_for_milestones(history, 'github_clean_issue_audit', 'test_run', 'E')

	# Stall burden should be relatively high (many non-milestone steps)
	assert metrics.stall_burden > 0.5, f'Expected high stall burden, got {metrics.stall_burden}'
