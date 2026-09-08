"""MCP OpenAI fallbacks and configured-model precedence."""

import pytest

from browser_use.mcp import server as server_module


@pytest.fixture
def server(monkeypatch, tmp_path):
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'config'))
	monkeypatch.delenv('MODEL_PROVIDER', raising=False)
	instance = server_module.BrowserUseServer()
	instance.config = {
		'llm': {'api_key': 'test-key'},
		'browser_profile': {
			'headless': True,
			'user_data_dir': None,
			'keep_alive': False,
			'downloads_path': str(tmp_path / 'downloads'),
			'file_system_path': str(tmp_path / 'files'),
		},
	}
	return instance


@pytest.mark.parametrize('configured', [None, 'gpt-4.1-mini'])
async def test_extraction_model_default_and_configured_override(server, configured):
	if configured:
		server.config['llm']['model'] = configured
	try:
		await server._init_browser_session()
		assert server.llm is not None
		assert server.llm.model == (configured or 'gpt-5.6-luna')
	finally:
		if server.browser_session:
			await server.browser_session.kill()


@pytest.mark.parametrize(
	('configured', 'explicit', 'expected'),
	[
		(None, None, 'gpt-5.6-luna'),
		('gpt-4.1-mini', None, 'gpt-4.1-mini'),
		('gpt-4.1-mini', 'gpt-6-astra', 'gpt-6-astra'),
	],
)
async def test_agent_model_default_and_override_precedence(server, monkeypatch, configured, explicit, expected):
	if configured:
		server.config['llm']['model'] = configured
	captured = {}

	class ModelSelected(Exception):
		pass

	def capture_llm(**kwargs):
		captured.update(kwargs)
		raise ModelSelected

	# Stop at the LLM constructor: no provider call or agent execution is needed
	# to verify which model the MCP runner selects.
	monkeypatch.setattr(server_module, 'ChatOpenAI', capture_llm)
	with pytest.raises(ModelSelected):
		await server._retry_with_browser_use_agent(task='No external task', model=explicit)
	assert captured['model'] == expected
