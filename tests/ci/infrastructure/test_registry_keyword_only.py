"""Custom actions preserve positional and keyword-only parameter kinds."""

import pytest
from pydantic import BaseModel

from browser_use.tools.registry.service import Registry


@pytest.mark.parametrize('is_async', [False, True])
@pytest.mark.parametrize('count', [None, 3])
async def test_keyword_only_action_and_injected_parameters(is_async: bool, count: int | None) -> None:
	"""Mixed signatures receive action values and injected context correctly."""
	registry = Registry()

	def sync_action(prefix: str, /, text: str, *, count: int = 2, available_file_paths: list[str]) -> dict:
		"""Repeat text and include the injected file paths."""
		return {'text': prefix + text * count, 'paths': available_file_paths}

	async def async_action(prefix: str, /, text: str, *, count: int = 2, available_file_paths: list[str]) -> dict:
		"""Repeat text asynchronously and include the injected file paths."""
		return {'text': prefix + text * count, 'paths': available_file_paths}

	action = registry.action('Repeat text')(async_action if is_async else sync_action)
	params: dict[str, str | int] = {'prefix': 'result: ', 'text': 'hello'}
	if count is not None:
		params['count'] = count
	result = await registry.execute_action(action.__name__, params, available_file_paths=['report.txt'])
	assert result == {'text': 'result: ' + 'hello' * (count if count is not None else 2), 'paths': ['report.txt']}


@pytest.mark.parametrize('is_async', [False, True])
async def test_keyword_only_explicit_parameter_model(is_async: bool) -> None:
	"""An explicit model can be the first keyword-only action parameter."""
	registry = Registry()

	class RepeatParams(BaseModel):
		"""Input for the custom action."""

		text: str
		count: int = 2

	def sync_action(*, values: RepeatParams, available_file_paths: list[str]) -> dict:
		"""Use the validated model and injected context."""
		return {'text': values.text * values.count, 'paths': available_file_paths}

	async def async_action(*, values: RepeatParams, available_file_paths: list[str]) -> dict:
		"""Use the validated model and injected context asynchronously."""
		return {'text': values.text * values.count, 'paths': available_file_paths}

	action = registry.action('Repeat text', param_model=RepeatParams)(async_action if is_async else sync_action)
	result = await registry.execute_action(action.__name__, {'text': 'hello', 'count': 3}, available_file_paths=['report.txt'])
	assert result == {'text': 'hellohellohello', 'paths': ['report.txt']}


async def test_keyword_only_special_parameter_default() -> None:
	"""An optional special parameter uses its default when context is absent."""
	registry = Registry()

	@registry.action('Include the page URL')
	async def action(text: str, *, page_url: str = 'no page') -> dict:
		"""Return the text and page URL."""
		return {'text': text, 'page_url': page_url}

	assert await registry.execute_action('action', {'text': 'hello'}) == {'text': 'hello', 'page_url': 'no page'}


async def test_required_keyword_only_special_parameter_still_rejected() -> None:
	"""Missing required context is rejected before executing the action."""
	registry = Registry()

	@registry.action('Include the page URL')
	async def action(text: str, *, page_url: str) -> str:
		"""Return text with the required URL."""
		return text + page_url

	with pytest.raises(RuntimeError, match="missing required special parameter 'page_url'"):
		await registry.execute_action('action', {'text': 'hello'})
