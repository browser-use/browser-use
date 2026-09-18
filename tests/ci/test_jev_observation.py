"""Jev observation reductions preserve native history and fail open."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from browser_use.agent.jev_observation import apply_jev_compact, apply_jev_vision
from browser_use.llm.messages import (
	BaseMessage,
	ContentPartImageParam,
	ContentPartTextParam,
	ImageURL,
	SystemMessage,
	UserMessage,
)


def observation(dom='[Start of page]\n[1]<button />\n\tSearch\n[End of page]', *, task='Find a flight', history='Ready'):
	return (
		f'<user_request>\n{task}\n</user_request>\n\n'
		f'<agent_history>\n<step>\n{history}\n</agent_history>\n\n'
		'<agent_state>\n<todo_contents>Keep Zurich and London.</todo_contents>\n</agent_state>\n'
		'<browser_state>\n<page_stats>20 links, 30 interactive</page_stats>\nCurrent tab: abcd\n'
		'Available tabs:\nTab abcd: https://example.com/flights - Source title\n'
		f'<page_info>0 pages above, 1 page below</page_info>\nInteractive elements:\n{dom}\n</browser_state>\n'
		'<read_state>source evidence must remain</read_state>\n<step_info>Step2 maximum:50</step_info>\n'
	)


def image(name):
	return ContentPartImageParam(image_url=ImageURL(url=f'data:image/png;base64,{name}'))


def messages(text=None):
	return [
		SystemMessage(content='System unchanged'),
		UserMessage(
			content=[
				ContentPartTextParam(text=text or observation()),
				image('sample'),
				ContentPartTextParam(text='Current screenshot:'),
				image('screenshot'),
				ContentPartTextParam(text='Image from file: source.png'),
				image('file'),
			],
			cache=True,
		),
		UserMessage(content='Context unchanged'),
	]


def client(choice='DOM_ONLY', confidence=0.99):
	async def choose(state, questions, *, purpose):
		return {key: {'choice': choice, 'confidence': confidence} for key in questions}

	mock = AsyncMock()
	mock.ask.side_effect = choose
	return mock


def large_dom():
	# Real native format: an indexed element followed by indented visible text.
	return (
		'[Start of page]\n'
		+ ''.join(
			f'[{i}]<a />\n\tAbout us Company Careers Press Resources Generic navigation ' + ('About the company ' * 110) + '\n'
			for i in range(1, 6)
		)
		+ '[80]<input value=Zurich />\n[81]<span />\n\tPrice CHF 120\n[End of page]'
	)


@pytest.mark.asyncio
async def test_vision_drops_only_current_screenshot_without_mutation():
	original = messages()
	before = [message.model_dump() for message in original]
	mock = client()
	filtered = await apply_jev_vision(original, mock)
	assert [message.model_dump() for message in original] == before
	assert filtered is not original
	assert filtered[0] is original[0] and filtered[2] is original[2]
	assert filtered[1] is not original[1]
	assert filtered[1].cache
	parts = filtered[1].content
	assert isinstance(parts, list)
	assert [p.image_url.url for p in parts if isinstance(p, ContentPartImageParam)] == [
		'data:image/png;base64,sample',
		'data:image/png;base64,file',
	]
	assert 'Current screenshot:' in filtered[1].text
	assert 'FULL_CONTEXT' in filtered[1].text
	assert mock.ask.call_args.kwargs['purpose'] == 'observation_vision'


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,confidence', [('KEEP', 0.99), ('DOM_ONLY', 0.7), ('DOM_ONLY', float('nan')), ('DOM_ONLY', True)])
async def test_vision_uncertainty_keeps_screenshot(answer, confidence):
	original = messages()
	assert await apply_jev_vision(original, client(answer, confidence)) == original


@pytest.mark.asyncio
@pytest.mark.parametrize('history', ['failed to click', 'no progress', 'FULL_CONTEXT', 'Need screenshot to inspect'])
async def test_recovery_never_filters_or_calls_provider(history):
	mock = client('DROP')
	original = messages(observation(large_dom(), history=history))
	assert await apply_jev_vision(original, mock) == original
	if history != 'Need screenshot to inspect':
		assert await apply_jev_compact(original, mock) == original
	mock.ask.assert_not_called()


@pytest.mark.asyncio
async def test_visual_task_keeps_screenshot():
	mock = client()
	original = messages(observation(task='Compare the chart colors'))
	assert await apply_jev_vision(original, mock) == original
	mock.ask.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('filterer', [apply_jev_compact, apply_jev_vision])
async def test_force_full_and_invalid_structure(filterer):
	mock = client('DROP')
	original = messages(observation(large_dom()))
	assert await filterer(original, mock, force_full=True) == original
	duplicate = messages(observation(large_dom()) + '\n<browser_state>\nambiguous\n</browser_state>\n')
	assert await filterer(duplicate, mock) == duplicate
	mock.ask.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('filterer', [apply_jev_compact, apply_jev_vision])
async def test_provider_failure_retains_full_input_but_cancellation_propagates(filterer):
	original = messages(observation(large_dom()))
	mock = client()
	mock.ask.side_effect = RuntimeError('upstream failed')
	assert await filterer(original, mock) == original
	mock.ask.side_effect = asyncio.CancelledError()
	with pytest.raises(asyncio.CancelledError):
		await filterer(original, mock)


@pytest.mark.asyncio
async def test_compact_preserves_values_sources_history_and_original():
	original = messages(observation(large_dom(), task='Research available flights and cite sources'))
	before = [message.model_dump() for message in original]
	mock = client('DROP')
	filtered = await apply_jev_compact(original, mock)
	assert [message.model_dump() for message in original] == before
	assert len(filtered[1].text) < len(original[1].text)
	for preserved in [
		'Current tab: abcd',
		'https://example.com/flights - Source title',
		'<user_request>',
		'Research available flights and cite sources',
		'<agent_history>',
		'[Start of page]',
		'[End of page]',
		'<todo_contents>',
		'[80]<input value=Zurich />',
		'Price CHF 120',
		'<read_state>source evidence must remain</read_state>',
	]:
		assert preserved in filtered[1].text
	assert 'FULL_CONTEXT' in filtered[1].text
	assert isinstance(filtered[1].content, list) and isinstance(original[1].content, list)
	assert filtered[1].content[3] == original[1].content[3]
	assert mock.ask.call_count == 1
	assert len(mock.ask.call_args.kwargs['questions']) > 1
	assert mock.ask.call_args.kwargs['purpose'] == 'observation_compact'


@pytest.mark.asyncio
async def test_compact_drops_only_confident_selected_chunks():
	original = messages(observation(large_dom()))
	mock = client()

	async def choose(state, questions, *, purpose):
		return {key: {'choice': 'DROP' if i == 0 else 'KEEP', 'confidence': 0.99} for i, key in enumerate(questions)}

	mock.ask.side_effect = choose
	filtered = await apply_jev_compact(original, mock)
	assert '[Jev omitted 1 DOM chunks' in filtered[1].text
	assert '[5]<a />' in filtered[1].text


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', [{}, {'unexpected': {'choice': 'DROP', 'confidence': 0.99}}])
async def test_compact_invalid_batch_keeps_full_dom(answer):
	original = messages(observation(large_dom()))
	mock = client()
	mock.ask.side_effect = None
	mock.ask.return_value = answer
	assert await apply_jev_compact(original, mock) == original


@pytest.mark.asyncio
async def test_compact_string_message_small_dom_and_protected_only():
	mock = client('DROP')
	original: list[BaseMessage] = [UserMessage(content=observation())]
	assert await apply_jev_compact(original, mock) == original
	mock.ask.assert_not_called()
	protected = large_dom().replace('Generic navigation', 'value=important')
	original = [UserMessage(content=observation(protected))]
	assert await apply_jev_compact(original, mock) == original
	mock.ask.assert_not_called()
	original = [UserMessage(content=observation(large_dom()))]
	filtered = await apply_jev_compact(original, mock)
	assert isinstance(filtered[0].content, str)
	assert isinstance(original[0].content, str)
	assert len(filtered[0].content) < len(original[0].content)


@pytest.mark.asyncio
@pytest.mark.parametrize('filterer', [apply_jev_compact, apply_jev_vision])
async def test_empty_browser_section_fails_open(filterer):
	import re

	original = messages(
		re.sub(r'<browser_state>.*?</browser_state>', '<browser_state>\n\n</browser_state>', observation(), flags=re.S)
	)
	mock = client()
	assert await filterer(original, mock) == original
	mock.ask.assert_not_called()
