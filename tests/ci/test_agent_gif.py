from __future__ import annotations

from PIL import Image

from browser_use.agent.gif import create_history_gif
from browser_use.agent.views import AgentHistory, AgentHistoryList
from browser_use.browser.views import BrowserStateHistory


def test_create_history_gif_creates_parent_directories(tmp_path):
	"""Nested custom GIF output paths should behave like other saved artifacts."""
	screenshot_path = tmp_path / 'screenshot.png'
	Image.new('RGB', (8, 8), color='white').save(screenshot_path)

	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[],
				state=BrowserStateHistory(
					url='https://example.com',
					title='Example',
					tabs=[],
					interacted_element=[],
					screenshot_path=str(screenshot_path),
				),
			)
		]
	)

	output_path = tmp_path / 'nested' / 'gif' / 'agent_history.gif'

	create_history_gif(
		task='test task',
		history=history,
		output_path=str(output_path),
		show_task=False,
		show_goals=False,
	)

	assert output_path.exists()
