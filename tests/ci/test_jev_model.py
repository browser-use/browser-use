"""Model routing and static ablation preserve the full native request."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from browser_use.agent.jev_model import JevModelRouter
from browser_use.agent.views import ActionResult, AgentState
from browser_use.llm.messages import (
	AssistantMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	Function,
	ImageURL,
	SystemMessage,
	ToolCall,
	UserMessage,
)


def messages(history='Clicked search. Need to open filters.'):
	return [
		SystemMessage(content='Native system prompt with action descriptions.'),
		UserMessage(
			content=[
				ContentPartTextParam(
					text=(
						'<user_request>\nFind nonstop flights under 100 EUR.\n</user_request>\n'
						f'<agent_history>\n<step>\n{history}\n</agent_history>\n'
						'<agent_state>\n<todo_contents>Preserve budget 100 EUR</todo_contents>\n</agent_state>\n'
						'<browser_state>\nTab abcd https://example.com/search\n'
						'[7]<button /> Filters\n</browser_state>\n'
					)
				),
				ContentPartTextParam(text='Current screenshot:'),
				ContentPartImageParam(image_url=ImageURL(url='data:image/png;base64,PRIVATE_IMAGE_BYTES')),
			],
		),
		AssistantMessage(
			content='Keep original memory.',
			tool_calls=[ToolCall(id='a', function=Function(name='click', arguments='{"index":7}'))],
		),
	]


def setup(answer=None, *, step=2):
	agent = SimpleNamespace(
		state=AgentState(n_steps=step),
		llm=SimpleNamespace(provider='browser-use', model='bu-2-0'),
		AgentOutput=object(),
		DoneAgentOutput=object(),
	)
	client = SimpleNamespace(
		ask=AsyncMock(
			return_value={
				'model': answer or {'choice': 'mini', 'confidence': 0.01, 'probabilities': {'mini': 0.95, 'main': 0.05}}
			}
		),
		record=Mock(),
	)
	return JevModelRouter(client), agent, client


async def choose(router, agent, *, original=None, static=False, force_full=False, results=None):
	return await router.choose_mini(
		agent,
		original or messages(),
		previous_results=results if results is not None else [ActionResult(extracted_content='Clicked Search')],
		static=static,
		force_full=force_full,
	)


async def test_routes_by_selected_probability_and_retains_complete_text_without_mutation():
	router, agent, client = setup()
	original = messages()
	before = [m.model_dump() for m in original]
	assert await choose(router, agent, original=original)
	assert [m.model_dump() for m in original] == before
	request = client.ask.call_args.kwargs
	state = request['state']
	assert request['purpose'] == 'native_model_route'
	assert state['native_messages'][0]['text'] == original[0].text
	assert state['native_messages'][1]['text'] == original[1].text
	assert state['native_messages'][1]['image_count'] == 1
	assert state['native_messages'][2]['text'] == original[2].text
	assert state['native_messages'][2]['tool_calls'][0]['function']['arguments'] == '{"index":7}'
	assert 'PRIVATE_IMAGE_BYTES' not in str(state)
	assert client.record.call_args.args[0]['route'] == 'mini'


@pytest.mark.parametrize('static', [False, True])
@pytest.mark.parametrize('step', [0, 1, 4, 8, 12])
async def test_periodic_checkpoints_are_identical_for_static_ablation(static, step):
	router, agent, client = setup(step=step)
	assert not await choose(router, agent, static=static)
	client.ask.assert_not_awaited()


@pytest.mark.parametrize('static', [False, True])
async def test_forced_done_and_explicit_checkpoint_never_route_mini(static):
	router, agent, client = setup()
	assert not await choose(router, agent, static=static, force_full=True)
	agent.AgentOutput = agent.DoneAgentOutput
	assert not await choose(router, agent, static=static)
	client.ask.assert_not_awaited()


@pytest.mark.parametrize('static', [False, True])
@pytest.mark.parametrize('condition', ['failure', 'stagnation', 'paused', 'stopped', 'different_model'])
async def test_recovery_and_runtime_guards_match_static_ablation(static, condition):
	router, agent, client = setup()
	if condition == 'failure':
		agent.state.consecutive_failures = 1
	elif condition == 'stagnation':
		agent.state.loop_detector.consecutive_stagnant_pages = 2
	elif condition == 'different_model':
		agent.llm.model = 'bu-2-0-mini-preview'
	else:
		setattr(agent.state, condition, True)
	assert not await choose(router, agent, static=static)
	client.ask.assert_not_awaited()


@pytest.mark.parametrize('static', [False, True])
@pytest.mark.parametrize(
	'results', [[], [ActionResult(error='failed')], [ActionResult(is_done=True)], [ActionResult(success=False)]]
)
async def test_previous_action_must_have_succeeded(static, results):
	router, agent, client = setup()
	assert not await choose(router, agent, static=static, results=results)
	client.ask.assert_not_awaited()


@pytest.mark.parametrize('static', [False, True])
@pytest.mark.parametrize('condition', ['missing', 'duplicate', 'huge', 'recovery'])
async def test_incomplete_large_or_recovery_context_never_routes_mini(static, condition):
	router, agent, client = setup()
	original = messages()
	if condition == 'missing':
		original = [UserMessage(content='Unstructured state without task/history')]
	elif condition == 'duplicate':
		original.append(original[1].model_copy(deep=True))
	elif condition == 'huge':
		original.append(SystemMessage(content='x' * 90000))
	else:
		original = messages(history='The click failed. Need recovery.')
	assert not await choose(router, agent, original=original, static=static)
	client.ask.assert_not_awaited()


@pytest.mark.parametrize(
	'answer',
	[
		{'choice': 'unknown', 'probabilities': {'mini': 1}},
		{'choice': 'main', 'probabilities': {'mini': 0.01, 'main': 0.99}},
		{'choice': 'mini', 'confidence': 1, 'probabilities': {'mini': 0.79}},
		{'choice': 'mini', 'confidence': 1},
		{'choice': 'mini', 'probabilities': {'mini': float('nan')}},
		{'choice': 'mini', 'probabilities': {'mini': True}},
		{'choice': 'mini', 'probabilities': {'mini': 1.1}},
	],
)
async def test_unknown_or_unconfident_choice_uses_main(answer):
	router, agent, client = setup(answer)
	assert not await choose(router, agent)
	client.ask.assert_awaited_once()


async def test_static_ablation_routes_eligible_step_without_classifier():
	router, agent, client = setup()
	assert await choose(router, agent, static=True)
	client.ask.assert_not_awaited()
	assert client.record.call_args.args[0]['reason'] == 'static_eligible_step'


@pytest.mark.parametrize('static', [False, True])
async def test_same_step_retry_uses_bu2_without_another_classifier_or_mini_call(static):
	router, agent, client = setup()
	assert await choose(router, agent, static=static)
	assert not await choose(router, agent, static=static)
	assert router.last_route_reason == 'same_step_retry'
	assert client.ask.await_count == (0 if static else 1)
	agent.state.n_steps += 1
	assert await choose(router, agent, static=static)


async def test_provider_error_yields_bu2_without_payload_leak():
	router, agent, client = setup()
	client.ask.side_effect = RuntimeError('secret upstream payload')
	assert not await choose(router, agent)
	assert router.last_route_reason == 'error_RuntimeError'
	assert 'secret upstream payload' not in str(client.record.call_args)


async def test_cancellation_propagates():
	router, agent, client = setup()
	client.ask.side_effect = asyncio.CancelledError()
	with pytest.raises(asyncio.CancelledError):
		await choose(router, agent)
