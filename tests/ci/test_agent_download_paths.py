from browser_use.agent.service import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from tests.ci.conftest import create_mock_llm


def test_update_available_file_paths_preserves_input_and_download_order(tmp_path):
	session = BrowserSession(browser_profile=BrowserProfile(downloads_path=tmp_path))
	agent = Agent(
		task='Use downloaded files.',
		llm=create_mock_llm(),
		browser_session=session,
		available_file_paths=['/tmp/input-b.txt', '/tmp/input-a.txt'],
	)

	agent._update_available_file_paths(['/tmp/download-b.txt', '/tmp/input-a.txt', '/tmp/download-a.txt', '/tmp/download-b.txt'])

	assert agent.available_file_paths == [
		'/tmp/input-b.txt',
		'/tmp/input-a.txt',
		'/tmp/download-b.txt',
		'/tmp/download-a.txt',
	]
