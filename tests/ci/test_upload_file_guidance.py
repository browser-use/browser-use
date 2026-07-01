from pathlib import Path

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.views import UploadFileAction


def test_available_html_file_paths_are_described_as_local_files(tmp_path: Path):
	browser_state = BrowserStateSummary(
		url='https://example.com',
		title='Test',
		tabs=[TabInfo(target_id='test-0', url='https://example.com', title='Test')],
		screenshot=None,
		dom_state=SerializedDOMState(_root=None, selector_map={}),
	)
	prompt = AgentMessagePrompt(
		browser_state_summary=browser_state,
		file_system=FileSystem(tmp_path),
		available_file_paths=['/app/something_capabilities.html'],
	)

	user_message = prompt.get_user_message(use_vision=False)

	assert isinstance(user_message.content, str)
	assert '/app/something_capabilities.html' in user_message.content
	assert 'These are local file paths, not URLs' in user_message.content
	assert 'Do not navigate to them, even if they end in .html' in user_message.content
	assert 'Use upload_file to upload them to file inputs' in user_message.content


def test_upload_file_action_schema_describes_available_file_paths():
	schema = UploadFileAction.model_json_schema()

	assert 'file input' in schema['properties']['index']['description']
	assert 'available_file_paths' in schema['properties']['path']['description']
	assert '.html files' in schema['properties']['path']['description']
	assert 'do not navigate' in schema['properties']['path']['description']
