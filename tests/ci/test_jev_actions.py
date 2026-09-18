"""Jev routing boundaries without network access or a running browser."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import create_model

from browser_use.agent.jev_actions import JevActionRouter, JevActionSettings
from browser_use.agent.views import ActionResult, AgentOutput, AgentState
from browser_use.browser.views import BrowserStateSummary, NetworkRequest
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType, SerializedDOMState, SimplifiedNode
from browser_use.tools.registry.views import ActionModel
from browser_use.tools.views import ClickElementActionIndexOnly, DoneAction, InputTextAction, ScrollAction


def node(index=7, *, tag='button', label='Open filters', attrs=None, visible=True, frame='main'):
	return EnhancedDOMTreeNode(
		node_id=index,
		backend_node_id=index + 100,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag.upper(),
		node_value='',
		attributes={'aria-label': label, **(attrs or {})},
		is_scrollable=False,
		is_visible=visible,
		absolute_position=None,
		target_id='tab-1234',
		frame_id=frame,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=None,
	)


def browser_state(nodes=None, **overrides):
	nodes = nodes if nodes is not None else [node()]
	root = SimplifiedNode(
		original_node=node(1000, tag='body', label=''),
		children=[SimplifiedNode(original_node=n, children=[], is_interactive=True, selector_index=n.node_id) for n in nodes],
	)
	return BrowserStateSummary(
		dom_state=SerializedDOMState(_root=root, selector_map={n.node_id: n for n in nodes}),
		url='https://example.com/search',
		title='Search',
		tabs=[],
		**overrides,
	)


def setup_router(choice='click_7', confidence=0.98, *, settings=None):
	action_model = create_model(
		'NativeTestActions',
		__base__=ActionModel,
		click=(ClickElementActionIndexOnly | None, None),
		scroll=(ScrollAction | None, None),
		input=(InputTextAction | None, None),
		done=(DoneAction | None, None),
	)
	output_model = AgentOutput.type_with_custom_actions(action_model)
	parent = output_model(
		memory='Budget is 100 EUR. Need departure time and fare.',
		next_goal='Open the filters and select nonstop flights.',
		action=[action_model.model_validate({'click': {'index': 2}})],
	)
	agent = SimpleNamespace(
		task='Find a nonstop flight for under 100 EUR.',
		state=AgentState(),
		settings=SimpleNamespace(include_attributes=None),
		sensitive_data=None,
		ActionModel=action_model,
		AgentOutput=output_model,
	)
	client = SimpleNamespace(ask=AsyncMock(return_value={'next_action': {'choice': choice, 'confidence': confidence}}))
	router = JevActionRouter(client, settings)
	router.remember_main_output(parent)
	return router, agent, client, parent


async def choose(router, agent, state=None, results=None):
	return await router.try_action(
		agent,
		state or browser_state(),
		previous_results=results if results is not None else [ActionResult(extracted_content='Clicked search')],
	)


async def test_native_index_and_parent_memory_are_preserved():
	router, agent, client, parent = setup_router(choice='click_23')
	output = await choose(router, agent, browser_state([node(7), node(23, frame='iframe-2')]))
	assert output is not None
	assert output.action[0].model_dump(exclude_none=True) == {'click': {'index': 23}}
	assert parent.memory in output.memory
	assert output.plan_update is None
	assert output.current_plan_item is None
	assert output.next_goal == parent.next_goal
	assert 'not verified' in output.evaluation_previous_goal
	request = client.ask.call_args.kwargs
	assert request['state']['task'] == agent.task
	assert request['state']['parent_memory'] == parent.memory
	assert request['purpose'] == 'native_fast_action'
	criteria = request['questions']['next_action']['criteria']
	assert 'frame=iframe-2' in criteria['click_23']
	assert set(criteria) == {'click_7', 'click_23', 'fallback'}


async def test_native_flash_memory_can_supply_continuation_without_next_goal():
	router, agent, client, _ = setup_router()
	agent.AgentOutput = AgentOutput.type_with_custom_actions_flash_mode(agent.ActionModel)
	parent = agent.AgentOutput.model_validate(
		{
			'memory': 'Opened flight results. Still need to open filters and choose nonstop; budget is 100 EUR.',
			'action': [{'click': {'index': 2}}],
		}
	)
	assert parent.next_goal is None
	router.remember_main_output(parent)
	output = await choose(router, agent)
	assert output is not None
	assert output.next_goal is None
	assert parent.memory in output.memory
	assert output.action[0].model_dump(exclude_none=True) == {'click': {'index': 7}}
	assert client.ask.call_args.kwargs['state']['parent_goal_explicit'] is False
	assert client.ask.call_args.kwargs['state']['parent_goal'] is None


def test_menu_excludes_typing_hidden_disabled_and_unknown_targets():
	_, agent, _, _ = setup_router()
	state = browser_state(
		[
			node(7),
			node(8, visible=False),
			node(9, attrs={'disabled': ''}),
			node(10, attrs={'aria-disabled': 'true'}),
			node(11, tag='input'),
			node(12, tag='textarea'),
			node(13, attrs={'contenteditable': ''}),
			node(14, tag='select'),
			node(15, tag='input', attrs={'type': 'checkbox'}),
			node(16, label=''),
			node(0),
		],
		pixels_below=100,
	)
	actions, criteria = JevActionRouter._menu(agent.ActionModel, state)
	assert set(actions) == {'click_7', 'click_15', 'scroll_down'}
	assert set(criteria) == set(actions) | {'fallback'}
	assert all(set(action.model_dump(exclude_none=True)) <= {'click', 'scroll'} for action in actions.values())


@pytest.mark.parametrize(
	'choice,confidence', [('fallback', 1.0), ('click_999', 1.0), ('click_7', 0.84), ('click_7', float('nan'))]
)
async def test_abstention_bad_target_and_low_confidence_fall_back(choice, confidence):
	router, agent, client, _ = setup_router(choice=choice, confidence=confidence)
	assert await choose(router, agent) is None
	assert await choose(router, agent) is None
	assert client.ask.await_count == 1


@pytest.mark.parametrize(
	'results', [[], [ActionResult(error='click failed')], [ActionResult(is_done=True)], [ActionResult(success=False)]]
)
async def test_unconfirmed_or_failed_previous_action_never_calls_jev(results):
	router, agent, client, _ = setup_router()
	assert await choose(router, agent, results=results) is None
	client.ask.assert_not_awaited()


async def test_cold_start_requires_main_model():
	router, agent, client, _ = setup_router()
	router = JevActionRouter(client)
	assert await choose(router, agent) is None
	client.ask.assert_not_awaited()


async def test_no_observed_progress_returns_to_main_model():
	router, agent, client, _ = setup_router()
	assert await choose(router, agent) is not None
	assert await choose(router, agent) is None
	assert router.last_route_reason == 'no_observed_progress'
	assert client.ask.await_count == 1


async def test_maximum_two_fast_steps_then_main_model():
	router, agent, client, parent = setup_router()
	assert await choose(router, agent) is not None
	client.ask.return_value = {'next_action': {'choice': 'scroll_down', 'confidence': 0.98}}
	assert await choose(router, agent, browser_state([node(label='Filters open')], pixels_below=100)) is not None
	assert await choose(router, agent, browser_state([node(label='New page')])) is None
	assert router.last_route_reason == 'burst_limit'
	assert client.ask.await_count == 2
	router.remember_main_output(parent)
	client.ask.return_value = {'next_action': {'choice': 'click_7', 'confidence': 0.98}}
	assert await choose(router, agent) is not None


async def test_repeated_click_is_rejected_even_if_other_content_changed():
	router, agent, client, _ = setup_router()
	assert await choose(router, agent) is not None
	assert await choose(router, agent, browser_state([node(), node(23, label='Clock changed')])) is None
	assert router.last_route_reason == 'repeated_action'
	assert client.ask.await_count == 2


async def test_provider_failure_falls_back_without_logging_payload(caplog):
	router, agent, client, _ = setup_router()
	client.ask.side_effect = RuntimeError('private provider response')
	assert await choose(router, agent) is None
	assert 'private provider response' not in caplog.text
	assert router.last_route_reason == 'error_RuntimeError'


async def test_cancellation_propagates():
	router, agent, client, _ = setup_router()
	client.ask.side_effect = asyncio.CancelledError()
	with pytest.raises(asyncio.CancelledError):
		await choose(router, agent)


@pytest.mark.parametrize('settings', [JevActionSettings(max_dom_chars=100), JevActionSettings(max_choices=2)])
async def test_budgets_fall_back_instead_of_silently_omitting_targets(settings):
	router, agent, client, _ = setup_router(settings=settings)
	assert await choose(router, agent, browser_state([node(7, label='A' * 300), node(23)])) is None
	client.ask.assert_not_awaited()


@pytest.mark.parametrize(
	'state',
	[
		browser_state(state_error='CDP disconnected'),
		browser_state(is_pdf_viewer=True),
		browser_state(pending_network_requests=[NetworkRequest(url='https://example.com/loading')]),
	],
)
async def test_incomplete_browser_state_yields_without_request(state):
	router, agent, client, _ = setup_router()
	assert await choose(router, agent, state) is None
	client.ask.assert_not_awaited()


async def test_sensitive_data_does_not_bypass_native_secret_replacement():
	router, agent, client, _ = setup_router()
	agent.sensitive_data = {'password': 'private value'}
	assert await choose(router, agent) is None
	client.ask.assert_not_awaited()


async def test_output_respects_forced_done_schema():
	router, agent, _, _ = setup_router()
	done_only = create_model('DoneOnly', __base__=ActionModel, done=(DoneAction | None, None))
	agent.AgentOutput = AgentOutput.type_with_custom_actions(done_only)
	assert await choose(router, agent) is None
	assert router.last_route_reason == 'error_ValidationError'


async def test_excluded_native_action_does_not_reappear_in_menu():
	router, agent, client, _ = setup_router()
	agent.ActionModel = create_model('NoClicks', __base__=ActionModel, done=(DoneAction | None, None))
	assert await choose(router, agent) is None
	client.ask.assert_not_awaited()


def test_real_native_registry_union_offers_clicks():
	from browser_use.tools.registry.service import Registry

	registry = Registry()

	@registry.action('Click', param_model=ClickElementActionIndexOnly)
	async def click(params: ClickElementActionIndexOnly):
		pass

	@registry.action('Scroll', param_model=ScrollAction)
	async def scroll(params: ScrollAction):
		pass

	model = registry.create_action_model()
	assert list(model.model_fields) == ['root']
	actions, criteria = JevActionRouter._menu(model, browser_state())
	assert 'click_7' in criteria
	assert actions['click_7'].model_dump(exclude_none=True) == {'click': {'index': 7}}
