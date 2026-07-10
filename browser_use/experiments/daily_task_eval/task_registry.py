"""Central task-tier metadata and task-selection helpers for daily task eval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

TaskTier = Literal['main', 'stress', 'archived']


class TaskTierMetadata(BaseModel):
	"""Single source-of-truth metadata for benchmark tiering and reporting filters."""

	model_config = ConfigDict(extra='forbid')

	tier: TaskTier
	include_in_default_runs: bool
	include_in_aggregate_metrics: bool
	include_in_reference_lcs: bool
	benchmark_note: str = ''


TASK_TIER_REGISTRY: dict[str, TaskTierMetadata] = {
	'shopping_price_compare': TaskTierMetadata(
		tier='main',
		include_in_default_runs=True,
		include_in_aggregate_metrics=True,
		include_in_reference_lcs=True,
	),
	'nearby_hospital_phone_lookup': TaskTierMetadata(
		tier='main',
		include_in_default_runs=True,
		include_in_aggregate_metrics=True,
		include_in_reference_lcs=True,
	),
	'github_clean_issue_audit': TaskTierMetadata(
		tier='main',
		include_in_default_runs=True,
		include_in_aggregate_metrics=True,
		include_in_reference_lcs=True,
	),
	'huggingface_model_constrained_selection': TaskTierMetadata(
		tier='main',
		include_in_default_runs=True,
		include_in_aggregate_metrics=True,
		include_in_reference_lcs=True,
	),
	'complex_travel_package_booking': TaskTierMetadata(
		tier='stress',
		include_in_default_runs=False,
		include_in_aggregate_metrics=False,
		include_in_reference_lcs=True,
		benchmark_note='High-volatility transactional stress case',
	),
	'shopping_cart_review': TaskTierMetadata(
		tier='archived',
		include_in_default_runs=False,
		include_in_aggregate_metrics=False,
		include_in_reference_lcs=False,
		benchmark_note='Archived: excluded from benchmark aggregates',
	),
	'paper_link_collection': TaskTierMetadata(
		tier='archived',
		include_in_default_runs=False,
		include_in_aggregate_metrics=False,
		include_in_reference_lcs=False,
		benchmark_note='Archived: excluded from benchmark aggregates',
	),
	'paper_bibtex_export': TaskTierMetadata(
		tier='archived',
		include_in_default_runs=False,
		include_in_aggregate_metrics=False,
		include_in_reference_lcs=False,
		benchmark_note='Archived: excluded from benchmark aggregates',
	),
	'daily_service_hours_lookup': TaskTierMetadata(
		tier='archived',
		include_in_default_runs=False,
		include_in_aggregate_metrics=False,
		include_in_reference_lcs=False,
		benchmark_note='Archived: excluded from benchmark aggregates',
	),
}


def task_metadata_for(task_id: str) -> TaskTierMetadata:
	"""Return tier metadata; unknown tasks default to archived/non-aggregate."""

	return TASK_TIER_REGISTRY.get(
		task_id,
		TaskTierMetadata(
			tier='archived',
			include_in_default_runs=False,
			include_in_aggregate_metrics=False,
			include_in_reference_lcs=True,
			benchmark_note='Unregistered task: treated as archived for safety',
		),
	)


def get_main_tasks() -> list[str]:
	"""Task ids used by default benchmark runs and aggregates."""

	return [task_id for task_id, meta in TASK_TIER_REGISTRY.items() if meta.tier == 'main']


def get_stress_tasks() -> list[str]:
	"""Task ids marked as stress cases."""

	return [task_id for task_id, meta in TASK_TIER_REGISTRY.items() if meta.tier == 'stress']


def get_archived_tasks() -> list[str]:
	"""Task ids kept only for historical compatibility."""

	return [task_id for task_id, meta in TASK_TIER_REGISTRY.items() if meta.tier == 'archived']


def get_tasks_for_aggregate_metrics() -> list[str]:
	"""Task ids allowed in default aggregate metrics/rankings/charts."""

	return [task_id for task_id, meta in TASK_TIER_REGISTRY.items() if meta.include_in_aggregate_metrics]


# ============================================================================
# Milestone Definitions for Process-Level Evaluation (Step 3)
# ============================================================================


from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class MilestoneDefinition:
	"""A milestone represents a critical progress checkpoint in a task."""

	milestone_id: str
	description: str
	check: Callable[[dict, str | None, str | None], bool]


# Shopping Price Compare Milestones (M1–M5)


def _shopping_m1_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M1: Navigate to shopping site (amazon.com or fallback)."""
	if not url:
		return False
	url_lower = url.lower()
	return any(
		domain in url_lower
		for domain in ['amazon.com', 'jd.com', 'taobao.com', 'tmall.com', 'walmart.com']
	)


def _shopping_m2_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M2: Perform search action for product query."""
	if action_name not in ('input', 'search', 'submit'):
		return False
	model_output = step.get('model_output', {})
	actions = model_output.get('action', [])
	for action in actions:
		if isinstance(action, dict):
			for key, val in action.items():
				if key in ('input', 'search', 'input_text') and isinstance(val, dict):
					text = val.get('text', '').lower()
					if '无线鼠标' in text or 'wireless mouse' in text:
						return True
	return False


def _shopping_m3_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M3: Land on search results page (URL contains search/s/ or see results summary)."""
	if not url:
		return False
	url_lower = url.lower()
	if any(kw in url_lower for kw in ['/s/', '/search', 'keyword=', 'q=']):
		return True
	state_message = step.get('state_message', '')
	if 'results' in state_message.lower() and (
		'product' in state_message.lower() or 'item' in state_message.lower()
	):
		return True
	return False


def _shopping_m4_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M4: Open first product detail page."""
	if not url:
		return False
	url_lower = url.lower()
	return any(
		pattern in url_lower
		for pattern in ['/dp/', '/gp/product/', '/item.html', '/product/', '/item/', 'product_id=']
	)


def _shopping_m5_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M5: Extract structured data or done with evidence."""
	if action_name == 'done':
		return True
	if action_name in ('extract', 'extract_structured_data', 'extract_content'):
		return True
	return False


SHOPPING_MILESTONES = [
	MilestoneDefinition('M1_navigate_site', 'Navigate to shopping site', _shopping_m1_check),
	MilestoneDefinition('M2_search_query', 'Perform product search', _shopping_m2_check),
	MilestoneDefinition('M3_results_page', 'Land on search results', _shopping_m3_check),
	MilestoneDefinition('M4_product_detail', 'Open product detail page', _shopping_m4_check),
	MilestoneDefinition('M5_extract_done', 'Extract data or complete', _shopping_m5_check),
]


# Hospital Phone Lookup Milestones (M1–M6)


def _hospital_m1_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M1: Navigate to map site (map.baidu.com, amap.com, google maps)."""
	if not url:
		return False
	url_lower = url.lower()
	return any(
		domain in url_lower
		for domain in ['map.baidu.com', 'amap.com', 'ditu.amap.com', 'maps.google', 'gaode.com']
	)


def _hospital_m2_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M2: Input search query for hospital."""
	if action_name not in ('input', 'search', 'input_text'):
		return False
	model_output = step.get('model_output', {})
	actions = model_output.get('action', [])
	for action in actions:
		if isinstance(action, dict):
			for key, val in action.items():
				if key in ('input', 'search', 'input_text') and isinstance(val, dict):
					text = val.get('text', '').lower()
					if '医院' in text or 'hospital' in text:
						return True
	return False


def _hospital_m3_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M3: Search results appear (URL contains search params or page shows POI list)."""
	if not url:
		return False
	url_lower = url.lower()
	if any(kw in url_lower for kw in ['query=', 'wd=', 'keywords=', 'search?']):
		return True
	state_message = step.get('state_message', '')
	return '医院' in state_message or 'hospital' in state_message.lower()


def _hospital_m4_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M4: Select specific hospital POI (click on marker or list item)."""
	if action_name != 'click':
		return False
	result = step.get('result', [])
	for r in result:
		if isinstance(r, dict):
			content = str(r.get('extracted_content', '')).lower()
			if any(kw in content for kw in ['clicked', '医院', 'hospital', 'detail']):
				return True
	return False


def _hospital_m5_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M5: Phone number visible in detail pane or page."""
	state_message = step.get('state_message', '')
	if not isinstance(state_message, str):
		return False
	import re

	phone_pattern = r'(\d{3}[-\.\s]?\d{3,4}[-\.\s]?\d{4}|\d{11}|电话|Phone|Tel)'
	return bool(re.search(phone_pattern, state_message, re.IGNORECASE))


def _hospital_m6_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M6: Extract or done with phone evidence."""
	if action_name == 'done':
		return True
	if action_name in ('extract', 'extract_content', 'extract_structured_data'):
		return True
	return False


HOSPITAL_MILESTONES = [
	MilestoneDefinition('M1_navigate_map', 'Navigate to map site', _hospital_m1_check),
	MilestoneDefinition('M2_search_hospital', 'Input hospital search', _hospital_m2_check),
	MilestoneDefinition('M3_results_appear', 'Search results appear', _hospital_m3_check),
	MilestoneDefinition('M4_select_poi', 'Select specific hospital', _hospital_m4_check),
	MilestoneDefinition('M5_phone_visible', 'Phone number visible', _hospital_m5_check),
	MilestoneDefinition('M6_extract_done', 'Extract or complete', _hospital_m6_check),
]


# GitHub Issue Audit Milestones (M1–M7)


def _github_m1_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M1: Navigate to GitHub repository issues page."""
	if not url:
		return False
	url_lower = url.lower()
	return 'github.com' in url_lower and '/issues' in url_lower


def _github_m2_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M2: Apply 'bug' label filter."""
	if action_name != 'click':
		return False
	result = step.get('result', [])
	for r in result:
		if isinstance(r, dict):
			content = str(r.get('extracted_content', '')).lower()
			if 'bug' in content or 'label' in content:
				return True
	return False


def _github_m3_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M3: Filter confirms 'label:bug' in URL or visible filter chip."""
	if not url:
		return False
	url_lower = url.lower()
	if 'label%3abug' in url_lower or 'label:bug' in url_lower or 'labels=bug' in url_lower:
		return True
	state_message = step.get('state_message', '')
	return 'label:bug' in state_message.lower() or 'label%3abug' in state_message.lower()


def _github_m4_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M4: Apply 'is:open' and sort filters (URL reflects open+oldest sort)."""
	if not url:
		return False
	url_lower = url.lower()
	return (
		'is%3aopen' in url_lower or 'state=open' in url_lower or 'is:open' in url_lower
	) and ('sort=' in url_lower or 'oldest' in url_lower or 'created-asc' in url_lower)


def _github_m5_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M5: Click on oldest issue to open detail page."""
	if action_name != 'click':
		return False
	state = step.get('state', {})
	if not isinstance(state, dict):
		return False
	url_value = state.get('url', '')
	if not isinstance(url_value, str):
		return False
	import re

	return bool(re.search(r'/issues/\d+', url_value))


def _github_m6_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M6: Issue detail page loaded (URL is /issues/<number> and content shows title/body)."""
	if not url:
		return False
	url_lower = url.lower()
	import re

	if not re.search(r'/issues/\d+', url_lower):
		return False
	state_message = step.get('state_message', '')
	return any(kw in state_message.lower() for kw in ['issue', 'opened by', 'comment', 'label'])


def _github_m7_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M7: Extract evidence or done with issue details."""
	if action_name == 'done':
		return True
	if action_name in ('extract', 'extract_content', 'extract_structured_data'):
		return True
	return False


GITHUB_MILESTONES = [
	MilestoneDefinition('M1_navigate_issues', 'Navigate to issues page', _github_m1_check),
	MilestoneDefinition('M2_click_bug_filter', 'Click bug label filter', _github_m2_check),
	MilestoneDefinition('M3_bug_filter_active', 'Bug filter active in URL', _github_m3_check),
	MilestoneDefinition('M4_open_oldest_sort', 'Apply open+oldest sort', _github_m4_check),
	MilestoneDefinition('M5_click_oldest_issue', 'Click oldest issue', _github_m5_check),
	MilestoneDefinition('M6_issue_detail_loaded', 'Issue detail page loaded', _github_m6_check),
	MilestoneDefinition('M7_extract_done', 'Extract or complete', _github_m7_check),
]


# HuggingFace Model Selection Milestones (M1–M7)


def _hf_m1_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M1: Navigate to huggingface.co/models."""
	if not url:
		return False
	url_lower = url.lower()
	return 'huggingface.co/models' in url_lower


def _hf_m2_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M2: Apply 'Text Generation' task filter."""
	if action_name != 'click':
		return False
	result = step.get('result', [])
	for r in result:
		if isinstance(r, dict):
			content = str(r.get('extracted_content', '')).lower()
			if 'text generation' in content:
				return True
	return False


def _hf_m3_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M3: Apply 'PyTorch' library filter."""
	if action_name != 'click':
		return False
	result = step.get('result', [])
	for r in result:
		if isinstance(r, dict):
			content = str(r.get('extracted_content', '')).lower()
			if 'pytorch' in content:
				return True
	return False


def _hf_m4_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M4: Apply 'Chinese' language filter (URL has language=zh/zho or chip active)."""
	if not url:
		return False
	url_lower = url.lower()
	if 'language=zh' in url_lower or 'language=zho' in url_lower:
		return True
	if action_name == 'click':
		result = step.get('result', [])
		for r in result:
			if isinstance(r, dict):
				content = str(r.get('extracted_content', '')).lower()
				if 'chinese' in content or '中文' in content:
					return True
	return False


def _hf_m5_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M5: Change sort to 'Most Downloads' (URL or action reflects sort change)."""
	if not url:
		return False
	url_lower = url.lower()
	if 'sort=' in url_lower and 'download' in url_lower:
		return True
	if action_name == 'click':
		result = step.get('result', [])
		for r in result:
			if isinstance(r, dict):
				content = str(r.get('extracted_content', '')).lower()
				if 'download' in content and 'sort' in content:
					return True
	return False


def _hf_m6_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M6: Navigate to top model detail page."""
	if not url:
		return False
	url_lower = url.lower()
	if 'huggingface.co/' in url_lower and '/models/' not in url_lower and url_lower.count('/') >= 4:
		return True
	return False


def _hf_m7_check(step: dict, url: str | None, action_name: str | None) -> bool:
	"""M7: Extract Base model field or done."""
	if action_name == 'done':
		return True
	if action_name in ('extract', 'extract_content', 'extract_structured_data'):
		return True
	state_message = step.get('state_message', '')
	if 'base model' in state_message.lower():
		return True
	return False


HF_MILESTONES = [
	MilestoneDefinition('M1_navigate_models', 'Navigate to models page', _hf_m1_check),
	MilestoneDefinition('M2_filter_text_gen', 'Apply Text Generation filter', _hf_m2_check),
	MilestoneDefinition('M3_filter_pytorch', 'Apply PyTorch filter', _hf_m3_check),
	MilestoneDefinition('M4_filter_chinese', 'Apply Chinese language filter', _hf_m4_check),
	MilestoneDefinition('M5_sort_downloads', 'Sort by Most Downloads', _hf_m5_check),
	MilestoneDefinition('M6_open_model_page', 'Open top model page', _hf_m6_check),
	MilestoneDefinition('M7_extract_done', 'Extract Base model or complete', _hf_m7_check),
]


# Milestone Registry


TASK_MILESTONE_REGISTRY: dict[str, list[MilestoneDefinition]] = {
	'shopping_price_compare': SHOPPING_MILESTONES,
	'nearby_hospital_phone_lookup': HOSPITAL_MILESTONES,
	'github_clean_issue_audit': GITHUB_MILESTONES,
	'huggingface_model_constrained_selection': HF_MILESTONES,
}


def get_task_milestones(task_id: str) -> list[MilestoneDefinition]:
	"""Retrieve milestone definitions for a given task_id."""
	return TASK_MILESTONE_REGISTRY.get(task_id, [])


def get_all_milestone_task_ids() -> list[str]:
	"""Return all task IDs that have milestone definitions."""
	return list(TASK_MILESTONE_REGISTRY.keys())

