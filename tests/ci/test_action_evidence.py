import json

from browser_use.agent.views import (
	ACTION_EVIDENCE_METADATA_KEY,
	ActionEvidence,
	ActionResult,
	PageFingerprint,
	PageFingerprintDelta,
	with_action_evidence_metadata,
)


def test_page_fingerprint_delta_detects_bounded_changes():
	"""Fingerprint deltas expose URL, text, and element-count changes."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'hello world', 50)
	after = PageFingerprint.from_browser_state('https://example.com/next', 'goodbye world', 53)

	delta = PageFingerprintDelta.between(before, after)

	assert delta.is_complete is True
	assert delta.has_changes is True
	assert delta.url_changed is True
	assert delta.text_changed is True
	assert delta.element_count_delta == 3
	assert delta.observed_delta == ['url_changed', 'text_changed', 'element_count_delta:+3']
	assert delta.missing_fingerprints == []


def test_page_fingerprint_delta_detects_no_change():
	"""Identical fingerprints produce a complete empty delta."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)
	after = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)

	delta = PageFingerprintDelta.between(before, after)

	assert delta.is_complete is True
	assert delta.has_changes is False
	assert delta.url_changed is False
	assert delta.text_changed is False
	assert delta.element_count_delta == 0
	assert delta.observed_delta == []
	assert delta.missing_fingerprints == []


def test_page_fingerprint_delta_reports_missing_fingerprints():
	"""Missing before/after fingerprints are explicit instead of silently treated as no-op."""
	delta = PageFingerprintDelta.between(None, None)

	assert delta.is_complete is False
	assert delta.has_changes is False
	assert delta.missing_fingerprints == ['missing_before_fingerprint', 'missing_after_fingerprint']


def test_action_evidence_from_page_delta_marks_navigation():
	"""URL changes are classified separately from in-page changes."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'hello world', 50)
	after = PageFingerprint.from_browser_state('https://example.com/next', 'hello world', 50)

	evidence = ActionEvidence.from_page_delta(
		action_id='action-1',
		action_name='click',
		target_summary='button: Next',
		before_fingerprint=before,
		after_fingerprint=after,
	)

	assert evidence.action_id == 'action-1'
	assert evidence.action_name == 'click'
	assert evidence.target_summary == 'button: Next'
	assert evidence.dispatched is True
	assert evidence.settled is True
	assert evidence.outcome == 'navigation'
	assert evidence.observed_delta == ['url_changed']
	assert evidence.blocking_signals == []
	assert evidence.recovery_hint is None


def test_action_evidence_from_page_delta_marks_changed():
	"""Text or element-count deltas are regular changed outcomes."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'old content', 50)
	after = PageFingerprint.from_browser_state('https://example.com/start', 'new content', 51)

	evidence = ActionEvidence.from_page_delta(
		action_id='action-2',
		action_name='scroll',
		before_fingerprint=before,
		after_fingerprint=after,
	)

	assert evidence.outcome == 'changed'
	assert evidence.observed_delta == ['text_changed', 'element_count_delta:+1']
	assert evidence.recovery_hint is None


def test_action_evidence_from_page_delta_marks_no_change_with_recovery_hint():
	"""A dispatched, settled action with no page delta gets no-op recovery metadata."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)
	after = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)

	evidence = ActionEvidence.from_page_delta(
		action_id='action-3',
		action_name='click',
		target_summary='button: Submit',
		before_fingerprint=before,
		after_fingerprint=after,
	)

	assert evidence.outcome == 'no_change'
	assert evidence.observed_delta == []
	assert evidence.blocking_signals == []
	assert evidence.recovery_hint is not None
	assert 'page fingerprint did not change' in evidence.recovery_hint
	assert 'keyboard navigation' in evidence.recovery_hint


def test_action_evidence_from_page_delta_marks_unsettled_action_attention():
	"""Unsettled actions are attention outcomes even when fingerprints are available."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)
	after = PageFingerprint.from_browser_state('https://example.com/start', 'updated content', 50)

	evidence = ActionEvidence.from_page_delta(
		action_id='action-4',
		action_name='input',
		before_fingerprint=before,
		after_fingerprint=after,
		settled=False,
	)

	assert evidence.outcome == 'attention'
	assert evidence.observed_delta == ['text_changed']
	assert evidence.blocking_signals == ['not_settled']
	assert evidence.recovery_hint is not None
	assert 'settlement evidence is incomplete' in evidence.recovery_hint


def test_action_evidence_from_page_delta_marks_failed_dispatch():
	"""Failed dispatch is distinct from no-change after a successful dispatch."""
	evidence = ActionEvidence.from_page_delta(
		action_id='action-5',
		action_name='click',
		before_fingerprint=None,
		after_fingerprint=None,
		dispatched=False,
		settled=None,
	)

	assert evidence.outcome == 'failed'
	assert evidence.dispatched is False
	assert evidence.settled is None
	assert evidence.blocking_signals == ['missing_before_fingerprint', 'missing_after_fingerprint']
	assert evidence.recovery_hint is not None
	assert 'not dispatched successfully' in evidence.recovery_hint


def test_action_evidence_from_page_delta_marks_unknown_when_fingerprints_missing():
	"""Successful dispatch without complete before/after fingerprints remains unknown."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)

	evidence = ActionEvidence.from_page_delta(
		action_id='action-6',
		action_name='click',
		before_fingerprint=before,
		after_fingerprint=None,
	)

	assert evidence.outcome == 'unknown'
	assert evidence.observed_delta == []
	assert evidence.blocking_signals == ['missing_after_fingerprint']
	assert evidence.recovery_hint is not None
	assert 'evidence is incomplete' in evidence.recovery_hint


def test_action_evidence_metadata_merges_json_serializable_receipt():
	"""Action evidence attaches under one stable metadata key without dropping existing metadata."""
	before = PageFingerprint.from_browser_state('https://example.com/start', 'same content', 50)
	after = PageFingerprint.from_browser_state('https://example.com/next', 'same content', 50)
	evidence = ActionEvidence.from_page_delta(
		action_id='action-7',
		action_name='click',
		before_fingerprint=before,
		after_fingerprint=after,
	)

	metadata = with_action_evidence_metadata({'click_x': 10, 'click_y': 20}, evidence)
	result = ActionResult(extracted_content='Clicked element 7', metadata=metadata)

	assert result.metadata is not None
	assert result.metadata['click_x'] == 10
	assert result.metadata['click_y'] == 20
	action_evidence = result.metadata[ACTION_EVIDENCE_METADATA_KEY]
	assert action_evidence['action_id'] == 'action-7'
	assert action_evidence['outcome'] == 'navigation'
	assert action_evidence['before_fingerprint'] == before.model_dump(mode='json')
	assert action_evidence['after_fingerprint'] == after.model_dump(mode='json')
	json.dumps(result.metadata)
