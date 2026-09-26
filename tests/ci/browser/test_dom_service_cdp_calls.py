"""Regression tests for CDP calls made while building the DOM tree."""

from types import SimpleNamespace
from typing import Any, cast

from browser_use.dom.service import DomService


class RecordingRuntime:
	def __init__(self) -> None:
		self.expressions: list[str] = []

	async def evaluate(self, params: dict[str, Any], session_id: str) -> dict[str, Any]:
		self.expressions.append(params['expression'])
		if 'scrollData' in params['expression']:
			return {'result': {'value': {}}}
		return {'result': {'value': None}}


class StubDOMSnapshot:
	async def captureSnapshot(self, params: dict[str, Any], session_id: str) -> dict[str, Any]:
		return {'documents': []}


class StubDOM:
	async def getDocument(self, params: dict[str, Any], session_id: str) -> dict[str, Any]:
		return {}


async def test_get_all_trees_does_not_probe_unused_document_ready_state(monkeypatch) -> None:
	"""Building the DOM should not make a CDP call whose result is ignored."""
	runtime = RecordingRuntime()
	cdp_session = SimpleNamespace(
		session_id='session-1',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(Runtime=runtime, DOMSnapshot=StubDOMSnapshot(), DOM=StubDOM()),
		),
	)

	async def get_cdp_session(*_args: Any, **_kwargs: Any):
		return cdp_session

	browser_session = cast(
		Any,
		SimpleNamespace(
			logger=SimpleNamespace(debug=lambda *_args: None, warning=lambda *_args: None),
			get_or_create_cdp_session=get_cdp_session,
		),
	)
	service = DomService(browser_session)

	async def get_ax_tree(_target_id: str) -> dict[str, Any]:
		return {'nodes': []}

	async def get_viewport_ratio(_target_id: str) -> float:
		return 1.0

	monkeypatch.setattr(service, '_get_ax_tree_for_all_frames', get_ax_tree)
	monkeypatch.setattr(service, '_get_viewport_ratio', get_viewport_ratio)

	await service._get_all_trees(cast(Any, 'target-1'))

	assert 'document.readyState' not in runtime.expressions
