"""Tests for agent history GIF output handling."""

import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from browser_use.agent.gif import create_history_gif


def test_create_history_gif_creates_nested_output_directory(tmp_path: Path):
	"""Test custom GIF paths work when their parent directory does not exist."""
	image_buffer = BytesIO()
	Image.new('RGB', (2, 2), color='white').save(image_buffer, format='PNG')
	screenshot = base64.b64encode(image_buffer.getvalue()).decode()
	item = SimpleNamespace(
		state=SimpleNamespace(url='https://example.com', get_screenshot=lambda: screenshot),
		model_output=None,
	)
	history = SimpleNamespace(history=[item], screenshots=lambda return_none_if_not_screenshot: [screenshot])
	output_path = tmp_path / 'nested' / 'history.gif'

	with patch.object(Image.Image, 'save') as save:
		create_history_gif(task='', history=history, output_path=str(output_path), show_task=False)  # type: ignore[arg-type]

	assert output_path.parent.is_dir()
	save.assert_called_once()
