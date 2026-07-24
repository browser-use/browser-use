import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from examples.integrations.minimax import image_generation
from examples.integrations.minimax.image_generation import (
	GenerateImageParams,
	MiniMaxImageGenerationError,
	build_image_generation_url,
	generate_image_bytes,
)


@pytest.mark.parametrize(
	('base_url', 'expected'),
	[
		('https://api.minimax.io/v1', 'https://api.minimax.io/v1/image_generation'),
		('https://api.minimax.io/v1/', 'https://api.minimax.io/v1/image_generation'),
		('https://api.minimaxi.com/v1', 'https://api.minimaxi.com/v1/image_generation'),
	],
)
def test_build_image_generation_url(base_url: str, expected: str) -> None:
	assert build_image_generation_url(base_url) == expected


def test_build_image_generation_url_rejects_full_endpoint() -> None:
	with pytest.raises(ValueError, match='API base URL'):
		build_image_generation_url('https://api.minimax.io/v1/image_generation')


def test_build_image_generation_url_requires_versioned_base() -> None:
	with pytest.raises(ValueError, match='end in /v1'):
		build_image_generation_url('https://api.minimax.io')


async def test_generate_image_bytes_uses_official_request_shape() -> None:
	image = b'test-image'

	def handler(request: httpx.Request) -> httpx.Response:
		assert str(request.url) == 'https://api.minimaxi.com/v1/image_generation'
		assert request.headers['Authorization'] == 'Bearer test-key'
		assert request.headers['Content-Type'] == 'application/json'
		assert json.loads(request.content) == {
			'model': 'image-01',
			'prompt': 'A precise test image',
			'aspect_ratio': '16:9',
			'response_format': 'base64',
			'n': 1,
		}
		return httpx.Response(
			200,
			json={
				'data': {'image_base64': [base64.b64encode(image).decode()]},
				'base_resp': {'status_code': 0, 'status_msg': 'success'},
			},
		)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		result = await generate_image_bytes(
			GenerateImageParams(prompt='A precise test image', aspect_ratio='16:9'),
			api_key='test-key',
			base_url='https://api.minimaxi.com/v1',
			client=client,
		)

	assert result == image


async def test_generate_image_returns_saved_file_as_attachment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	image = b'test-image'
	generate = AsyncMock(return_value=image)
	monkeypatch.setattr(image_generation, 'generate_image_bytes', generate)
	monkeypatch.setattr(image_generation, '__file__', str(tmp_path / 'image_generation.py'))
	monkeypatch.setenv('MINIMAX_API_KEY', 'test-key')
	monkeypatch.delenv('MINIMAX_IMAGE_BASE_URL', raising=False)

	result = await image_generation.generate_image(params=GenerateImageParams(prompt='A precise test image'))

	generate.assert_awaited_once()
	assert result.attachments is not None
	assert len(result.attachments) == 1
	output_path = Path(result.attachments[0])
	assert output_path.parent == tmp_path / 'output'
	assert output_path.read_bytes() == image
	assert result.extracted_content == f'Generated image saved to {output_path}'


async def test_generate_image_bytes_surfaces_api_errors() -> None:
	def handler(request: httpx.Request) -> httpx.Response:
		return httpx.Response(
			200,
			json={
				'data': {},
				'base_resp': {'status_code': 2013, 'status_msg': 'Invalid input parameters'},
			},
		)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		with pytest.raises(MiniMaxImageGenerationError, match='2013'):
			await generate_image_bytes(
				GenerateImageParams(prompt='A precise test image'),
				api_key='test-key',
				client=client,
			)
