"""Tests for the Self-Healing Element Recovery Engine."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from browser_use.dom.auto_heal import AutoHealEngine


class TestAutoHealEngine:
	"""Test suite for AutoHealEngine."""

	def test_init(self):
		"""Engine initializes with empty state."""
		engine = AutoHealEngine()
		assert len(engine._fingerprints) == 0
		assert engine._heal_stats['attempts'] == 0

	def test_fingerprint_stores_element(self):
		"""Fingerprint stores element info for later recovery."""
		engine = AutoHealEngine()
		node = MagicMock()
		node.snapshot_node = MagicMock()
		node.ax_node.name = 'Sign In'
		node.ax_node.role = 'button'
		node.tag_name = 'button'
		node.attributes = {'class': 'btn btn-primary', 'data-testid': 'login-btn'}

		engine.fingerprint(1, node)

		assert 1 in engine._fingerprints
		fp = engine._fingerprints[1]
		assert fp.tag == 'button'
		assert fp.text == 'Sign In'
		assert fp.role == 'button'
		assert 'btn' in fp.classes

	def test_fingerprint_evicts_oldest_when_full(self):
		"""Old fingerprints are evicted when max capacity is reached."""
		engine = AutoHealEngine(max_fingerprints=3)

		for i in range(5):
			node = MagicMock()
			node.snapshot_node = MagicMock()
			node.ax_node.name = f'Element {i}'
			node.ax_node.role = ''
			node.tag_name = 'div'
			node.attributes = {}
			engine.fingerprint(i, node)

		assert len(engine._fingerprints) == 3
		# Oldest (0, 1) should be evicted
		assert 0 not in engine._fingerprints
		assert 1 not in engine._fingerprints
		assert 2 in engine._fingerprints

	def test_fingerprint_handles_none_snapshot(self):
		"""Fingerprint handles nodes without ax_node gracefully."""
		engine = AutoHealEngine()
		node = MagicMock()
		node.ax_node = None
		node.tag_name = 'div'
		node.attributes = {}

		# Should not raise
		engine.fingerprint(1, node)
		assert 1 in engine._fingerprints

	@pytest.mark.asyncio
	async def test_try_heal_no_fingerprint(self):
		"""Healing fails gracefully when no fingerprint exists."""
		engine = AutoHealEngine()
		cdp_session = MagicMock()
		cdp_session.session_id = 'test-session'

		result = await engine.try_heal(999, cdp_session)

		assert result.healed is False
		assert 'No fingerprint' in result.details
		assert engine._heal_stats['failures'] == 1

	@pytest.mark.asyncio
	async def test_try_heal_by_text_success(self):
		"""Healing succeeds when element is found by text match."""
		engine = AutoHealEngine()

		# Store a fingerprint
		node = MagicMock()
		node.snapshot_node = MagicMock()
		node.ax_node.name = 'Submit'
		node.ax_node.role = 'button'
		node.tag_name = 'button'
		node.attributes = {}
		engine.fingerprint(1, node)

		# Mock CDP session that finds element by text
		cdp_session = MagicMock()
		cdp_session.session_id = 'test-session'
		cdp_session.cdp_client.send.Runtime.evaluate = AsyncMock(
			return_value={'result': {'value': {'backendNodeId': 42, 'strategy': 'exact_text'}}}
		)

		result = await engine.try_heal(1, cdp_session)

		assert result.healed is True
		assert result.new_backend_node_id == 42
		assert result.strategy == 'text_match'
		assert engine._heal_stats['successes'] == 1

	@pytest.mark.asyncio
	async def test_try_heal_all_strategies_fail(self):
		"""Healing returns failure when all strategies are exhausted."""
		engine = AutoHealEngine()

		node = MagicMock()
		node.snapshot_node = MagicMock()
		node.ax_node.name = 'Submit'
		node.ax_node.role = 'button'
		node.tag_name = 'button'
		node.attributes = {}
		engine.fingerprint(1, node)

		# Mock CDP session that never finds anything
		cdp_session = MagicMock()
		cdp_session.session_id = 'test-session'
		cdp_session.cdp_client.send.Runtime.evaluate = AsyncMock(return_value={'result': {'value': None}})

		result = await engine.try_heal(1, cdp_session)

		assert result.healed is False
		assert 'All recovery' in result.details
		assert engine._heal_stats['failures'] == 1

	def test_get_stats(self):
		"""Stats are returned correctly."""
		engine = AutoHealEngine()
		stats = engine.get_stats()

		assert stats['attempts'] == 0
		assert stats['successes'] == 0
		assert stats['failures'] == 0
		assert stats['success_rate'] == 0.0
		assert stats['fingerprints_stored'] == 0

	def test_clear(self):
		"""Clear removes all fingerprints and resets stats."""
		engine = AutoHealEngine()
		node = MagicMock()
		node.snapshot_node = MagicMock()
		node.ax_node.name = 'Test'
		node.ax_node.role = ''
		node.tag_name = 'div'
		node.attributes = {}
		engine.fingerprint(1, node)

		engine.clear()

		assert len(engine._fingerprints) == 0
		assert engine._heal_stats['attempts'] == 0

	@pytest.mark.asyncio
	async def test_heal_result_confidence(self):
		"""Text match returns higher confidence than other strategies."""
		engine = AutoHealEngine()

		node = MagicMock()
		node.snapshot_node = MagicMock()
		node.ax_node.name = 'Login'
		node.ax_node.role = ''
		node.tag_name = 'a'
		node.attributes = {'aria-label': 'Login page'}
		engine.fingerprint(1, node)

		# Mock CDP session: text match returns None, a11y match succeeds
		cdp_session = MagicMock()
		cdp_session.session_id = 'test-session'

		async def mock_runtime_evaluate(params=None, session_id=None):
			expr = params.get('expression', '') if params else ''
			if 'aria-label' in expr:
				return {'result': {'value': {'backendNodeId': 42, 'strategy': 'a11y_attr'}}}
			return {'result': {'value': None}}

		cdp_session.cdp_client.send.Runtime.evaluate = mock_runtime_evaluate

		result = await engine.try_heal(1, cdp_session)

		assert result.healed is True
		assert result.strategy == 'a11y_match'
		assert result.confidence == 0.6  # Lower than text_match (0.8)
