"""Event-triggered adaptive navigator replanning for R-A (paper condition).

Opening plan matches condition I; during the run a progress monitor may trigger at most
one phase-transition replan and one friction-recovery replan (2 total adaptive replans).
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field

from .task_registry import MilestoneDefinition, get_task_milestones

ReplanPolicy = Literal['scheduled', 'event_triggered']

_MEANINGFUL_ACTIONS = frozenset(
	{
		'navigate',
		'search',
		'input',
		'click',
		'submit',
		'extract',
		'extract_structured_data',
		'extract_content',
		'scroll',
		'find_text',
		'search_page',
		'send_keys',
		'select_dropdown',
		'go_back',
		'switch',
		'close',
		'evaluate',
	}
)

_NAVIGATION_ACTIONS = frozenset({'navigate', 'search', 'go_back', 'switch', 'close'})
_POST_NAV_SETTLE_ACTIONS = frozenset({'navigate', 'search', 'click', 'submit', 'input', 'select_dropdown'})

_TRANSIENT_ENV_MARKERS = (
	'timeout',
	'timed out',
	'network',
	'connection',
	'net::',
	'err_',
	'navigation',
	'page load',
	'loading',
	'spinner',
	'not loaded',
	'disconnected',
	'refused',
	'econnreset',
	'etimedout',
)

_LOADING_TITLE_MARKERS = ('loading', 'about:blank', 'untitled')
_MIN_DOM_CHARS_FOR_STABLE = 80

_SEMANTIC_QUERY_KEYS: dict[str, frozenset[str]] = {
	'github.com': frozenset({'label', 'state', 'sort', 'q', 'is', 'type', 'assignee', 'author'}),
	'huggingface.co': frozenset({'language', 'library', 'pipeline_tag', 'sort', 'search', 'filter', 'p', 'task'}),
	'amazon.com': frozenset({'k', 'keywords', 'q', 'field-keywords', 'rh', 'i'}),
	'map.baidu.com': frozenset({'query', 'wd', 'qt', 'c', 'sn'}),
}

# Milestone that completes the "collection/filter" phase; phase replan fires once it is newly achieved.
_PHASE_GATE_MILESTONE: dict[str, str] = {
	'shopping_price_compare': 'M3_results_page',
	'nearby_hospital_phone_lookup': 'M3_results_appear',
	'github_clean_issue_audit': 'M4_open_oldest_sort',
	'huggingface_model_constrained_selection': 'M5_sort_downloads',
}

_PHASE_FOCUS_HINT: dict[str, str] = {
	'shopping_price_compare': (
		'Candidate products are visible. Do NOT repeat search. Open product detail pages and collect '
		'price, seller, and source URL for at least 3 comparable options.'
	),
	'nearby_hospital_phone_lookup': (
		'Hospital candidates are listed. Do NOT repeat the map search. Open detail pages for distinct '
		'facilities and collect name, phone, address, and source URL; state missing fields explicitly.'
	),
	'github_clean_issue_audit': (
		'Filters label:bug, is:open, and oldest sort are confirmed. Do NOT re-apply filters. Open the '
		'earliest issue and extract issue body plus the first comment.'
	),
	'huggingface_model_constrained_selection': (
		'Text Generation, PyTorch, Chinese filters and downloads sort are confirmed. Do NOT re-apply '
		'filters. Open the top model page and verify the base model field.'
	),
}


class AdaptiveTriggerType(StrEnum):
	PHASE = 'phase'
	NO_PROGRESS = 'no_progress'
	LOOP = 'loop'
	REPEATED_FAILURE = 'repeated_failure'
	STATE_REVISIT = 'state_revisit'


class AdaptiveReplanSettings(BaseModel):
	"""Explicit R-A policy knobs (not a fixed step interval)."""

	model_config = ConfigDict(extra='forbid')

	replan_policy: ReplanPolicy = 'event_triggered'
	scheduled_replan_interval: int | None = None
	no_progress_window: int = 3
	replan_cooldown_steps: int = 5
	max_phase_replans: int = 1
	max_recovery_replans: int = 1
	max_total_adaptive_replans: int = 2


class AdaptiveReplanEvent(BaseModel):
	model_config = ConfigDict(extra='forbid')

	step: int
	trigger_type: AdaptiveTriggerType
	trigger_reason: str


class AdaptiveReplanMetrics(BaseModel):
	model_config = ConfigDict(extra='forbid')

	replan_policy: ReplanPolicy = 'event_triggered'
	total_adaptive_replans: int = 0
	phase_replans: int = 0
	recovery_replans: int = 0
	had_adaptive_replan: bool = False
	trigger_events: list[AdaptiveReplanEvent] = Field(default_factory=list)
	trigger_type_counts: dict[str, int] = Field(default_factory=dict)
	progress_events: list[str] = Field(default_factory=list)
	recovery_latencies: list[int] = Field(default_factory=list)
	meaningful_actions_since_last_replan: int = 0
	environmental_wait_steps: int = Field(
		default=0,
		description='Steps classified as environmental wait (loading/network); excluded from friction counters.',
	)

	@property
	def zero_trigger_rate_component(self) -> bool:
		return self.total_adaptive_replans == 0


def default_adaptive_replan_settings() -> AdaptiveReplanSettings:
	return AdaptiveReplanSettings()


def _semantic_query_string(url: str) -> str:
	parsed = urlparse(url)
	host = (parsed.netloc or '').lower().removeprefix('www.')
	keys: frozenset[str] | None = None
	for domain, domain_keys in _SEMANTIC_QUERY_KEYS.items():
		if domain in host:
			keys = domain_keys
			break
	if not keys:
		keys = frozenset(
			k for k in parse_qs(parsed.query, keep_blank_values=True) if not any(k.startswith(p) for p in _UTM_PREFIXES)
		)
	pairs: list[str] = []
	for key in sorted(keys):
		if key in parse_qs(parsed.query, keep_blank_values=True):
			vals = parse_qs(parsed.query, keep_blank_values=True)[key]
			pairs.append(f'{key}={",".join(vals)}')
	return '&'.join(pairs)


def build_state_fingerprint(
	*,
	url: str | None,
	page_title: str | None,
	dom_snippet: str | None,
) -> str:
	"""Domain + path + semantic query + coarse page identity (not utm-stripped URL-only)."""

	if not url:
		return 'empty'
	parsed = urlparse(url)
	host = (parsed.netloc or '').lower().removeprefix('www.')
	path = parsed.path.rstrip('/') or '/'
	semantic_q = _semantic_query_string(url)
	title = (page_title or '').strip().lower()[:120]
	heading = ''
	if dom_snippet:
		for line in dom_snippet.splitlines()[:40]:
			low = line.lower().strip()
			if low.startswith('h1') or low.startswith('heading') or 'title' in low[:20]:
				heading = low[:120]
				break
	entity = ''
	if dom_snippet:
		m = re.search(r'/issues/(\d+)', url or '')
		if m:
			entity = f'issue:{m.group(1)}'
		elif '/models/' in (url or ''):
			parts = path.split('/')
			if len(parts) >= 3:
				entity = f'model:{parts[-1][:40]}'
	raw = f'{host}|{path}|{semantic_q}|{title}|{heading}|{entity}'
	return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_action_names(model_output: Any) -> list[str]:
	if model_output is None:
		return []
	actions = getattr(model_output, 'action', None)
	if actions is None and isinstance(model_output, dict):
		actions = model_output.get('action', [])
	if not actions:
		return []
	names: list[str] = []
	for act in actions:
		if hasattr(act, 'model_dump'):
			ad = act.model_dump(exclude_unset=True)
		elif isinstance(act, dict):
			ad = act
		else:
			continue
		if ad:
			names.append(next(iter(ad.keys()), '?'))
	return names


def _primary_action_name(names: list[str]) -> str | None:
	for name in names:
		low = name.lower()
		if low in _MEANINGFUL_ACTIONS or low not in {'wait', 'done'}:
			return low
	return names[0] if names else None


def _step_dict_from_history_item(item: Any) -> dict[str, Any]:
	if hasattr(item, 'model_dump'):
		return item.model_dump(mode='python')
	if isinstance(item, dict):
		return item
	return {}


def _extract_error_text(results: list[Any] | None) -> str | None:
	if not results:
		return None
	last = results[-1]
	error = getattr(last, 'error', None) if not isinstance(last, dict) else last.get('error')
	if error and str(error).strip():
		return str(error).strip()
	return None


def _is_transient_environment_error(error: str) -> bool:
	low = error.lower()
	return any(marker in low for marker in _TRANSIENT_ENV_MARKERS)


def _dom_looks_unstable(*, page_title: str | None, dom_snippet: str | None) -> bool:
	title = (page_title or '').strip().lower()
	if not title or title in _LOADING_TITLE_MARKERS:
		return True
	if dom_snippet is None:
		return True
	stripped = dom_snippet.strip()
	if len(stripped) < _MIN_DOM_CHARS_FOR_STABLE:
		return True
	low = stripped.lower()
	if 'loading' in low[:200] and 'interactive' not in low[:400]:
		return True
	return False


def _page_ready_for_replan(
	*,
	pending_network_count: int,
	page_title: str | None,
	dom_snippet: str | None,
) -> bool:
	if pending_network_count > 0:
		return False
	return not _dom_looks_unstable(page_title=page_title, dom_snippet=dom_snippet)


def _classify_environmental_wait(
	*,
	primary_action: str | None,
	error_text: str | None,
	pending_network_count: int,
	page_title: str | None,
	dom_snippet: str | None,
	post_nav_settle: bool,
) -> tuple[bool, str]:
	if primary_action == 'wait':
		return True, 'explicit_wait_action'
	if pending_network_count > 0:
		return True, f'pending_network_requests={pending_network_count}'
	if post_nav_settle and _dom_looks_unstable(page_title=page_title, dom_snippet=dom_snippet):
		return True, 'post_navigation_dom_settle'
	return False, ''


def _failure_signature(action_names: list[str], results: list[Any] | None) -> str | None:
	if not results:
		return None
	last = results[-1]
	error = getattr(last, 'error', None) if not isinstance(last, dict) else last.get('error')
	if not error:
		return None
	act = action_names[0] if action_names else '?'
	return hashlib.sha256(f'{act}:{str(error)[:200]}'.encode()).hexdigest()[:12]


def _extract_evidence_snippet(results: list[Any] | None) -> str | None:
	if not results:
		return None
	last = results[-1]
	content = getattr(last, 'extracted_content', None) if not isinstance(last, dict) else last.get('extracted_content')
	if content and str(content).strip():
		return str(content).strip()[:400]
	return None


def build_adaptive_navigator_prompt(
	*,
	original_task: str,
	initial_plan: str | None,
	current_url: str,
	page_heading: str,
	filter_sort_state: str,
	completed_milestones: list[str],
	recent_actions_block: str,
	trigger_reason: str,
	trigger_type: AdaptiveTriggerType,
	recent_evidence: list[str],
) -> str:
	plan_block = initial_plan.strip() if initial_plan else '(no opening plan recorded)'
	evidence_block = '\n'.join(f'- {e}' for e in recent_evidence[-5:]) or '(none yet)'
	milestones_block = ', '.join(completed_milestones) if completed_milestones else '(none yet)'
	return (
		f'Original task:\n{original_task}\n\n'
		f'Initial opening plan (do not rewrite from scratch):\n{plan_block}\n\n'
		f'Current URL: {current_url}\n'
		f'Page heading / title: {page_heading or "(unknown)"}\n'
		f'Active filters / sort (from URL + page): {filter_sort_state or "(none detected)"}\n'
		f'Completed milestones so far: {milestones_block}\n'
		f'Recent evidence extracted:\n{evidence_block}\n\n'
		f'Recent actions and outcomes (last steps):\n{recent_actions_block}\n\n'
		f'TRIGGER: {trigger_type.value}\n'
		f'Trigger reason: {trigger_reason}\n\n'
		'Instructions:\n'
		'- Do not restart the workflow.\n'
		'- Do not repeat completed subgoals or re-apply filters already confirmed.\n'
		'- Identify the immediate bottleneck.\n'
		'- Begin with <current_step_focus>...</current_step_focus> (1–3 short lines).\n'
		'- Then one concise recovery instruction (bullets ok, ~80 words total after the focus block).\n'
		'- Do not emit browser action JSON.\n'
	)


@dataclass
class _StepRecord:
	step: int
	action_names: list[str]
	primary_action: str | None
	is_meaningful: bool
	had_progress: bool
	progress_labels: list[str]
	url: str | None
	fingerprint: str
	failure_signature: str | None
	evidence_snippet: str | None
	environmental_wait: bool = False
	page_ready: bool = True


@dataclass
class AdaptiveReplanController:
	"""Online progress monitor + event-triggered replan gate for R-A."""

	task_id: str
	initial_plan: str | None
	settings: AdaptiveReplanSettings = field(default_factory=default_adaptive_replan_settings)
	metrics: AdaptiveReplanMetrics = field(default_factory=AdaptiveReplanMetrics)

	_phase_replans: int = 0
	_recovery_replans: int = 0
	_last_replan_step: int = 0
	_meaningful_since_replan: int = 0
	_phase_gate_fired: bool = False
	_achieved_milestones: set[str] = field(default_factory=set)
	_progress_event_labels: list[str] = field(default_factory=list)
	_evidence_hashes: set[str] = field(default_factory=set)
	_fingerprint_history: deque[str] = field(default_factory=lambda: deque(maxlen=12))
	_meaningful_without_progress: int = 0
	_last_failure_signature: str | None = None
	_consecutive_failure_signature_count: int = 0
	_pending_recovery_step: int | None = None
	_step_records: list[_StepRecord] = field(default_factory=list)
	_milestones: list[MilestoneDefinition] = field(default_factory=list)
	_last_page_ready: bool = True
	_post_nav_settle_steps: int = 0
	_transient_error_grace: set[str] = field(default_factory=set)
	_prior_url: str | None = None

	def __post_init__(self) -> None:
		self._milestones = get_task_milestones(self.task_id)
		self.metrics.replan_policy = self.settings.replan_policy

	def observe_completed_step(
		self,
		*,
		step: int,
		model_output: Any,
		results: list[Any] | None,
		url: str | None,
		page_title: str | None,
		dom_snippet: str | None,
		state_message: str | None = None,
		pending_network_count: int = 0,
		browser_errors: list[str] | None = None,
	) -> None:
		action_names = _extract_action_names(model_output)
		primary = _primary_action_name(action_names)
		is_meaningful = primary is not None and primary not in {'wait', 'done'}
		fingerprint = build_state_fingerprint(url=url, page_title=page_title, dom_snippet=dom_snippet)
		error_text = _extract_error_text(results)
		if not error_text and browser_errors:
			error_text = browser_errors[-1]

		post_nav_settle = self._post_nav_settle_steps > 0
		env_wait, env_reason = _classify_environmental_wait(
			primary_action=primary,
			error_text=error_text,
			pending_network_count=pending_network_count,
			page_title=page_title,
			dom_snippet=dom_snippet,
			post_nav_settle=post_nav_settle,
		)
		page_ready = _page_ready_for_replan(
			pending_network_count=pending_network_count,
			page_title=page_title,
			dom_snippet=dom_snippet,
		)
		self._last_page_ready = page_ready

		if primary in _POST_NAV_SETTLE_ACTIONS:
			self._post_nav_settle_steps = 1
		elif self._post_nav_settle_steps > 0:
			self._post_nav_settle_steps -= 1

		fail_sig: str | None = None
		if error_text and not env_wait:
			if _is_transient_environment_error(error_text):
				grace_key = hashlib.sha256(error_text[:200].encode()).hexdigest()[:12]
				if grace_key not in self._transient_error_grace:
					self._transient_error_grace.add(grace_key)
					env_wait = True
					env_reason = 'transient_error_grace_once'
				else:
					fail_sig = _failure_signature(action_names, results)
			else:
				fail_sig = _failure_signature(action_names, results)

		evidence = _extract_evidence_snippet(results)

		step_dict: dict[str, Any] = {
			'model_output': model_output.model_dump() if hasattr(model_output, 'model_dump') else model_output,
			'result': [r.model_dump() if hasattr(r, 'model_dump') else r for r in results] if results else [],
			'state_message': state_message or '',
		}
		progress_labels = self._detect_progress(step_dict, url, primary)
		had_progress = bool(progress_labels)

		if evidence:
			ev_hash = hashlib.sha256(evidence.encode()).hexdigest()[:12]
			if ev_hash not in self._evidence_hashes:
				self._evidence_hashes.add(ev_hash)
				if 'new_evidence' not in progress_labels:
					progress_labels.append('new_evidence')

		if env_wait:
			self.metrics.environmental_wait_steps += 1
			if env_reason:
				self.metrics.progress_events.append(f'step{step}:environmental_wait:{env_reason}')
		else:
			if fail_sig:
				if fail_sig == self._last_failure_signature:
					self._consecutive_failure_signature_count += 1
				else:
					self._last_failure_signature = fail_sig
					self._consecutive_failure_signature_count = 1
			else:
				self._last_failure_signature = None
				self._consecutive_failure_signature_count = 0

			if is_meaningful:
				self._meaningful_since_replan += 1
				if had_progress:
					self._meaningful_without_progress = 0
					if self._pending_recovery_step is not None:
						latency = step - self._pending_recovery_step
						if latency > 0:
							self.metrics.recovery_latencies.append(latency)
						self._pending_recovery_step = None
				else:
					self._meaningful_without_progress += 1

		if not env_wait:
			self._fingerprint_history.append(fingerprint)
		for label in progress_labels:
			self._progress_event_labels.append(f'step{step}:{label}')
			self.metrics.progress_events.append(f'step{step}:{label}')

		rec = _StepRecord(
			step=step,
			action_names=action_names,
			primary_action=primary,
			is_meaningful=is_meaningful and not env_wait,
			had_progress=had_progress,
			progress_labels=progress_labels,
			url=url,
			fingerprint=fingerprint,
			failure_signature=fail_sig,
			evidence_snippet=evidence,
			environmental_wait=env_wait,
			page_ready=page_ready,
		)
		self._step_records.append(rec)
		self.metrics.meaningful_actions_since_last_replan = self._meaningful_since_replan
		self._prior_url = url

	def evaluate_before_step(self, *, current_step: int, agent_done: bool) -> tuple[bool, AdaptiveTriggerType | None, str]:
		if agent_done:
			return False, None, 'agent_done'
		if self.settings.replan_policy != 'event_triggered':
			return False, None, 'not_event_triggered'
		total = self._phase_replans + self._recovery_replans
		if total >= self.settings.max_total_adaptive_replans:
			return False, None, 'max_total_replans'
		if self._last_replan_step > 0 and self._meaningful_since_replan < self.settings.replan_cooldown_steps:
			return False, None, 'cooldown'

		phase_reason = self._check_phase_transition()
		if phase_reason and self._phase_replans < self.settings.max_phase_replans:
			if not self._last_page_ready:
				return False, None, 'page_not_ready'
			return True, AdaptiveTriggerType.PHASE, phase_reason

		if not self._last_page_ready:
			return False, None, 'page_not_ready'

		recovery = self._check_recovery_triggers()
		if recovery and self._recovery_replans < self.settings.max_recovery_replans:
			return True, recovery[0], recovery[1]

		return False, None, 'no_trigger'

	def record_replan(self, *, step: int, trigger_type: AdaptiveTriggerType, trigger_reason: str) -> None:
		if trigger_type == AdaptiveTriggerType.PHASE:
			self._phase_replans += 1
			self._phase_gate_fired = True
		else:
			self._recovery_replans += 1
			self._pending_recovery_step = step

		self._last_replan_step = step
		self._meaningful_since_replan = 0
		self._meaningful_without_progress = 0
		self.metrics.total_adaptive_replans += 1
		self.metrics.had_adaptive_replan = True
		if trigger_type == AdaptiveTriggerType.PHASE:
			self.metrics.phase_replans += 1
		else:
			self.metrics.recovery_replans += 1
		event = AdaptiveReplanEvent(step=step, trigger_type=trigger_type, trigger_reason=trigger_reason)
		self.metrics.trigger_events.append(event)
		key = trigger_type.value
		self.metrics.trigger_type_counts[key] = self.metrics.trigger_type_counts.get(key, 0) + 1

	def completed_milestones(self) -> list[str]:
		return sorted(self._achieved_milestones)

	def recent_evidence(self) -> list[str]:
		out: list[str] = []
		for rec in reversed(self._step_records):
			if rec.evidence_snippet:
				out.append(rec.evidence_snippet[:180])
			if len(out) >= 5:
				break
		return list(reversed(out))

	def filter_sort_state(self, url: str | None, dom_snippet: str | None) -> str:
		parts: list[str] = []
		if url:
			sq = _semantic_query_string(url)
			if sq:
				parts.append(f'url_params={sq}')
		if dom_snippet:
			for token in ('label:bug', 'is:open', 'oldest', 'text generation', 'pytorch', 'chinese', 'download'):
				if token in dom_snippet.lower():
					parts.append(token)
		return '; '.join(parts)

	def _detect_progress(self, step: dict[str, Any], url: str | None, action_name: str | None) -> list[str]:
		labels: list[str] = []
		for milestone in self._milestones:
			if milestone.milestone_id in self._achieved_milestones:
				continue
			try:
				if milestone.check(step, url, action_name):
					self._achieved_milestones.add(milestone.milestone_id)
					labels.append(milestone.milestone_id)
			except Exception:
				continue
		return labels

	def _check_phase_transition(self) -> str | None:
		gate = _PHASE_GATE_MILESTONE.get(self.task_id)
		if not gate or self._phase_gate_fired:
			return None
		if gate not in self._achieved_milestones:
			return None
		hint = _PHASE_FOCUS_HINT.get(self.task_id, 'Advance to the next subgoal without repeating completed work.')
		return f'Phase gate {gate} completed. {hint}'

	def _check_recovery_triggers(self) -> tuple[AdaptiveTriggerType, str] | None:
		if self._consecutive_failure_signature_count >= 2 and self._last_failure_signature:
			return (
				AdaptiveTriggerType.REPEATED_FAILURE,
				f'Same failure signature repeated {self._consecutive_failure_signature_count} times.',
			)
		if self._meaningful_without_progress >= self.settings.no_progress_window:
			return (
				AdaptiveTriggerType.NO_PROGRESS,
				f'{self._meaningful_without_progress} meaningful actions without new progress.',
			)
		if self._detect_aba_loop():
			return AdaptiveTriggerType.LOOP, 'Detected A→B→A state loop without intervening progress.'
		if self._detect_unproductive_revisit():
			return (
				AdaptiveTriggerType.STATE_REVISIT,
				'Revisited same semantic state without new fields or evidence.',
			)
		return None

	def _detect_aba_loop(self) -> bool:
		if len(self._fingerprint_history) < 3:
			return False
		fp_list = list(self._fingerprint_history)
		a, b, c = fp_list[-3], fp_list[-2], fp_list[-1]
		if a != c or a == b:
			return False
		for rec in self._step_records[-2:]:
			if rec.had_progress or rec.environmental_wait:
				return False
		return True

	def _detect_unproductive_revisit(self) -> bool:
		if len(self._fingerprint_history) < 2:
			return False
		current = self._fingerprint_history[-1]
		prior_idx = None
		for i in range(len(self._fingerprint_history) - 2, -1, -1):
			if self._fingerprint_history[i] == current:
				prior_idx = i
				break
		if prior_idx is None:
			return False
		steps_between = len(self._fingerprint_history) - 1 - prior_idx
		if steps_between < 2:
			return False
		for rec in self._step_records[-steps_between:]:
			if rec.had_progress or rec.environmental_wait:
				return False
		return True

	def build_trigger_observation(
		self,
		*,
		original_task: str,
		current_url: str,
		page_heading: str,
		dom_snippet: str,
		recent_actions_block: str,
		trigger_type: AdaptiveTriggerType,
		trigger_reason: str,
	) -> str:
		return build_adaptive_navigator_prompt(
			original_task=original_task,
			initial_plan=self.initial_plan,
			current_url=current_url,
			page_heading=page_heading,
			filter_sort_state=self.filter_sort_state(current_url, dom_snippet),
			completed_milestones=self.completed_milestones(),
			recent_actions_block=recent_actions_block,
			trigger_reason=trigger_reason,
			trigger_type=trigger_type,
			recent_evidence=self.recent_evidence(),
		)

	def finalize_metrics(self) -> AdaptiveReplanMetrics:
		return self.metrics.model_copy(deep=True)
