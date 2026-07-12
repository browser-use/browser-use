import asyncio
import base64
import binascii
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from browser_use import ActionResult, Agent, ChatBrowserUse, Tools

MINIMAX_IMAGE_BASE_URL = 'https://api.minimax.io/v1'
MINIMAX_IMAGE_MODEL = 'image-01'

AspectRatio = Literal['1:1', '16:9', '4:3', '3:2', '2:3', '3:4', '9:16', '21:9']


class GenerateImageParams(BaseModel):
	prompt: str = Field(min_length=1, max_length=1500, description='A detailed description of the image to generate.')
	aspect_ratio: AspectRatio = Field(default='1:1', description='The aspect ratio of the generated image.')


class MiniMaxImageGenerationError(RuntimeError):
	pass


def build_image_generation_url(base_url: str) -> str:
	base_url = base_url.rstrip('/')
	if not base_url:
		raise ValueError('MINIMAX_IMAGE_BASE_URL cannot be empty')
	if base_url.endswith('/image_generation'):
		raise ValueError('MINIMAX_IMAGE_BASE_URL must be the API base URL, not the image generation endpoint')
	if not base_url.endswith('/v1'):
		raise ValueError('MINIMAX_IMAGE_BASE_URL must end in /v1')
	return f'{base_url}/image_generation'


def parse_image_response(payload: object) -> bytes:
	if not isinstance(payload, dict):
		raise MiniMaxImageGenerationError('Image generation returned an invalid response')

	base_resp = payload.get('base_resp')
	if isinstance(base_resp, dict):
		status_code = base_resp.get('status_code')
		if status_code not in (None, 0):
			status_msg = base_resp.get('status_msg') or 'unknown API error'
			raise MiniMaxImageGenerationError(f'Image generation failed ({status_code}): {status_msg}')

	data = payload.get('data')
	images = data.get('image_base64') if isinstance(data, dict) else None
	if not isinstance(images, list) or not images or not isinstance(images[0], str):
		raise MiniMaxImageGenerationError('Image generation response did not contain image data')

	try:
		return base64.b64decode(images[0], validate=True)
	except (binascii.Error, ValueError) as exc:
		raise MiniMaxImageGenerationError('Image generation returned invalid base64 data') from exc


async def generate_image_bytes(
	params: GenerateImageParams,
	*,
	api_key: str,
	base_url: str = MINIMAX_IMAGE_BASE_URL,
	client: httpx.AsyncClient | None = None,
) -> bytes:
	request_client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
	close_client = client is None

	try:
		response = await request_client.post(
			build_image_generation_url(base_url),
			headers={'Authorization': f'Bearer {api_key}'},
			json={
				'model': MINIMAX_IMAGE_MODEL,
				'prompt': params.prompt,
				'aspect_ratio': params.aspect_ratio,
				'response_format': 'base64',
				'n': 1,
			},
		)
		try:
			response.raise_for_status()
		except httpx.HTTPStatusError as exc:
			raise MiniMaxImageGenerationError(f'Image generation request failed with HTTP {response.status_code}') from exc

		try:
			payload = response.json()
		except ValueError as exc:
			raise MiniMaxImageGenerationError('Image generation returned invalid JSON') from exc
		return parse_image_response(payload)
	finally:
		if close_client:
			await request_client.aclose()


tools = Tools()


@tools.action(
	'Generate an image from a text prompt and save it locally. Use this after gathering the visual requirements.',
	param_model=GenerateImageParams,
)
async def generate_image(params: GenerateImageParams) -> ActionResult:
	api_key = os.getenv('MINIMAX_API_KEY')
	if not api_key:
		return ActionResult(error='MINIMAX_API_KEY is not set')

	base_url = os.getenv('MINIMAX_IMAGE_BASE_URL', MINIMAX_IMAGE_BASE_URL)
	output_dir = Path(__file__).parent / 'output'
	output_path = output_dir / f'{uuid4().hex}.jpeg'

	try:
		image = await generate_image_bytes(params, api_key=api_key, base_url=base_url)
		await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
		await asyncio.to_thread(output_path.write_bytes, image)
	except (MiniMaxImageGenerationError, httpx.HTTPError, OSError, ValueError) as exc:
		return ActionResult(error=f'Image generation failed: {exc}')

	message = f'Generated image saved to {output_path}'
	return ActionResult(extracted_content=message, long_term_memory=message)


async def main() -> None:
	if not os.getenv('MINIMAX_API_KEY'):
		raise ValueError('MINIMAX_API_KEY is not set')

	agent = Agent(
		task=(
			'Visit https://browser-use.com, identify the primary visual theme, and then call generate_image once '
			'to create a square editorial illustration inspired by that theme.'
		),
		llm=ChatBrowserUse(),
		tools=tools,
	)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
