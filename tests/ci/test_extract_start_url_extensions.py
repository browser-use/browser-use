"""_extract_start_url must only skip URLs whose path ends with a file extension, not any URL containing '.py' etc."""

import pytest

from browser_use import Agent


class _LLM:
	model = 'test'
	provider = 'test'
	name = 'test'
	_verified_api_keys = True

	async def ainvoke(self, messages, output_format=None, **kwargs):
		raise AssertionError('not called')


@pytest.fixture
def agent() -> Agent:
	return Agent(task='placeholder', llm=_LLM(), directly_open_url=False)  # type: ignore[arg-type]


@pytest.mark.parametrize(
	'task, expected',
	[
		('Go to https://www.python.org and find the download link', 'https://www.python.org'),
		('Open https://www.texasmonthly.com and summarize the top story', 'https://www.texasmonthly.com'),
		('Visit https://www.exeter.ac.uk and list the courses', 'https://www.exeter.ac.uk'),
		('Check https://cdn.jsdelivr.net/npm/foo for the latest build', 'https://cdn.jsdelivr.net/npm/foo'),
		('Open https://example.com/docs.html?x=1 and read it', 'https://example.com/docs.html?x=1'),
		('Go to example.com/about', 'https://example.com/about'),
	],
)
def test_sites_whose_names_contain_an_extension_are_kept(agent: Agent, task: str, expected: str):
	assert agent._extract_start_url(task) == expected


@pytest.mark.parametrize(
	'task',
	[
		'Go to https://example.com/report.pdf',
		'Download https://example.com/build/app.exe now',
		'Open example.com/index.html',
	],
)
def test_direct_file_links_are_still_skipped(agent: Agent, task: str):
	assert agent._extract_start_url(task) is None
