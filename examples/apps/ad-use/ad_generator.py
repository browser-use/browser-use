import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from browser_use.utils import create_task_with_error_handling


def setup_environment(debug: bool):
	if not debug:
		os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
		os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
		logging.getLogger().setLevel(logging.CRITICAL)
	else:
		os.environ['BROWSER_USE_SETUP_LOGGING'] = 'true'
		os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'info'


parser = argparse.ArgumentParser(description='Generate ads from landing pages using browser-use + 🍌')
parser.add_argument('--url', nargs='?', help='Landing page URL to analyze')
parser.add_argument('--debug', action='store_true', default=False, help='Enable debug mode (show browser, verbose logs)')
parser.add_argument('--count', type=int, default=1, help='Number of ads to generate in parallel (default: 1)')
group = parser.add_mutually_exclusive_group()
group.add_argument('--instagram', action='store_true', default=False, help='Generate Instagram image ad (default)')
group.add_argument('--tiktok', action='store_true', default=False, help='Generate TikTok video ad using Veo3')
args = parser.parse_args()
if not args.instagram and not args.tiktok:
	args.instagram = True
setup_environment(args.debug)

from typing import Any, cast

import aiofiles
from google import genai
from PIL import Image

from browser_use import Agent, BrowserSession
from browser_use.llm.google import ChatGoogle

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')


class LandingPageAnalyzer:
	def __init__(self, debug: bool = False):
		self.debug = debug
		self.llm = ChatGoogle(model='gemini-2.0-flash-exp', api_key=GOOGLE_API_KEY)
		self.output_dir = Path('output')
		self.output_dir.mkdir(exist_ok=True)

	async def analyze_landing_page(self, url: str, mode: str = 'instagram') -> dict:
		browser_session = BrowserSession(
			headless=not self.debug,
		)

		agent = Agent(
			task=f"""Go to {url} and quickly extract key brand information for Instagram ad creation.

Steps:
1. Navigate to the website
2. From the initial view, extract ONLY these essentials:
   - Brand/Product name
   - Main tagline or value proposition (one sentence)
   - Primary call-to-action text
   - Any visible pricing or special offer
3. Scroll down half a page, twice (0.5 pages each) to check for any key info
4. Done - keep it simple and focused on the brand

Return ONLY the key brand info, not page structure details.""",
			llm=self.llm,
			browser_session=browser_session,
			max_actions_per_step=2,
			step_timeout=30,
			use_thinking=False,
			vision_detail_level='high',
		)

		screenshot_path = None
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

		async def screenshot_callback(agent_instance):
			nonlocal screenshot_path
			await asyncio.sleep(4)
			screenshot_path = self.output_dir / f'landing_page_{timestamp}.png'
			await agent_instance.browser_session.take_screenshot(path=str(screenshot_path), full_page=False)

		screenshot_task = create_task_with_error_handling(
			screenshot_callback(agent), name='screenshot_callback', suppress_exceptions=True
		)
		history = await agent.run()
		try:
			await screenshot_task
		except Exception as e:
			print(f'Screenshot task failed: {e}')

		analysis = history.final_result() or 'No analysis content extracted'
		return {'url': url, 'analysis': analysis, 'screenshot_path': screenshot_path, 'timestamp': timestamp}


class AdGenerator:
	def __init__(self, api_key: str | None = GOOGLE_API_KEY, mode: str = 'instagram'):
		if not api_key:
			raise ValueError('GOOGLE_API_KEY is missing or empty – set the environment variable or pass api_key explicitly')

		self.client = genai.Client(api_key=api_key)
		self.output_dir = Path('output')
		self.output_dir.mkdir(exist_ok=True)
		self.mode = mode

	async def create_video_concept(self, browser_analysis: str, ad_id: int) -> str:
		"""Generate a unique creative concept for each video ad"""
		if self.mode != 'tiktok':
			return ''

		concept_prompt = f"""Based on this brand analysis:
{browser_analysis}

Create a UNIQUE and SPECIFIC TikTok video concept #{ad_id}.

Be creative and different! Consider various approaches like:
- Different visual metaphors and storytelling angles
- Various trending TikTok formats (transitions, reveals, transformations)
- Different emotional appeals (funny, inspiring, surprising, relatable)
- Unique visual styles (neon, retro, minimalist, maximalist, surreal)
- Different perspectives (first-person, aerial, macro, time-lapse)

Return a 2-3 sentence description of a specific, unique video concept that would work for this brand.
Make it visually interesting and different from typical ads. Be specific about visual elements, transitions, and mood."""

		response = self.client.models.generate_content(model='gemini-2.0-flash-exp', contents=concept_prompt)
		return response.text if response and response.text else ''

	def create_ad_prompt(self, browser_analysis: str, video_concept: str = '') -> str:
		if self.mode == 'instagram':
			prompt = f"""Create an Instagram ad for this brand:

{browser_analysis}

Create a vibrant, eye-catching Instagram ad image with:
- Try to use the colors and style of the logo or brand, else:
- Bold, modern gradient background with bright colors
- Large, playful sans-serif text with the product/service name from the analysis
- Trendy design elements: geometric shapes, sparkles, emojis
- Fun bubbles or badges for any pricing or special offers mentioned
- Call-to-action button with text from the analysis
- Emphasizes the key value proposition from the analysis
- Uses visual elements that match the brand personality
- Square format (1:1 ratio)
- Use color psychology to drive action

Style: Modern Instagram advertisement, (1:1), scroll-stopping, professional but playful, conversion-focused"""
		else:  # tiktok
			if video_concept:
				prompt = f"""Create a TikTok video ad based on this specific concept:

{video_concept}

Brand context: {browser_analysis}

Requirements:
- Vertical 9:16 format
- High quality, professional execution
- Bring the concept to life exactly as described
- No text overlays, pure visual storytelling"""
			else:
				prompt = f"""Create a viral TikTok video ad for this brand:

{browser_analysis}

Create a dynamic, engaging vertical video with:
- Quick hook opening that grabs attention immediately
- Minimal text overlays (focus on visual storytelling)
- Fast-paced but not overwhelming editing
- Authentic, relatable energy that appeals to Gen Z
- Vertical 9:16 format optimized for mobile
- High energy but professional execution

Style: Modern TikTok advertisement, viral potential, authentic energy, minimal text, maximum visual impact"""
		return prompt

	async def generate_ad_image(self, prompt: str, screenshot_path: Path | None = None) -> bytes | None:
		"""Generate ad image bytes using Gemini. Returns None on failure."""
		try:
			from typing import Any

			contents: list[Any] = [prompt]

			if screenshot_path and screenshot_path.exists():
				img = Image.open(screenshot_path)
				w, h = img.size
				side = min(w, h)
				img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
				contents = [prompt + '\n\nHere is the actual landing page screenshot to reference for design inspiration:', img]

			response = await self.client.aio.models.generate_content(
				model='gemini-2.5-flash-image-preview',
				contents=contents,
			)

			cand = getattr(response, 'candidates', None)
			if cand:
				for part in getattr(cand[0].content, 'parts', []):
					inline = getattr(part, 'inline_data', None)
					if inline:
						return inline.data
		except Exception as e:
			print(f'❌ Image generation failed: {e}')
		return None

	async def generate_ad_video(self, prompt: str, screenshot_path: Path | None = None, ad_id: int = 1) -> bytes:
		"""Generate ad video using Veo3."""
		sync_client = genai.Client(api_key=GOOGLE_API_KEY)

		# Commented out image input for now - it was using the screenshot as first frame
		# if screenshot_path and screenshot_path.exists():
		# 	import base64
		# 	import io

		# 	img = Image.open(screenshot_path)
		# 	img_buffer = io.BytesIO()
		# 	img.save(img_buffer, format='PNG')
		# 	img_bytes = img_buffer.getvalue()

		# 	operation = sync_client.models.generate_videos(
		# 		model='veo-3.0-generate-001',
		# 		prompt=prompt,
		# 		image=cast(Any, {
		# 			'imageBytes': base64.b64encode(img_bytes).decode('utf-8'),
		# 			'mimeType': 'image/png'
		# 		}),
		# 		config=cast(Any, {'aspectRatio': '9:16', 'resolution': '720p'}),
		# 	)
		# else:
		operation = sync_client.models.generate_videos(
			model='veo-3.0-generate-001',
			prompt=prompt,
			config=cast(Any, {'aspectRatio': '9:16', 'resolution': '720p'}),
		)

		while not operation.done:
			await asyncio.sleep(10)
			operation = sync_client.operations.get(operation)

		if not operation.response or not operation.response.generated_videos:
			raise RuntimeError('No videos generated')
		videos = operation.response.generated_videos
		video = videos[0]
		video_file = getattr(video, 'video', None)
		if not video_file:
			raise RuntimeError('No video file in response')
		sync_client.files.download(file=video_file)
		video_bytes = getattr(video_file, 'video_bytes', None)
		if not video_bytes:
			raise RuntimeError('No video bytes in response')
		return video_bytes

	async def save_results(self, ad_content: bytes, prompt: str, analysis: str, url: str, timestamp: str) -> str:
		if self.mode == 'instagram':
			content_path = self.output_dir / f'ad_{timestamp}.png'
		else:  # tiktok
			content_path = self.output_dir / f'ad_{timestamp}.mp4'

		async with aiofiles.open(content_path, 'wb') as f:
			await f.write(ad_content)

		analysis_path = self.output_dir / f'analysis_{timestamp}.txt'
		async with aiofiles.open(analysis_path, 'w', encoding='utf-8') as f:
			await f.write(f'URL: {url}\n\n')
			await f.write('BROWSER-USE ANALYSIS:\n')
			await f.write(analysis)
			await f.write('\n\nGENERATED PROMPT:\n')
			await f.write(prompt)

		return str(content_path)


def open_file(file_path: str):
	"""Open file with default system viewer"""
	try:
		if sys.platform.startswith('darwin'):
			subprocess.run(['open', file_path], check=True)
		elif sys.platform.startswith('win'):
			subprocess.run(['cmd', '/c', 'start', '', file_path], check=True)
		else:
			subprocess.run(['xdg-open', file_path], check=True)
	except Exception as e:
		print(f'❌ Could not open file: {e}')


async def create_ad_from_landing_page(url: str, debug: bool = False, mode: str = 'instagram', ad_id: int = 1):
	analyzer = LandingPageAnalyzer(debug=debug)

	try:
		if ad_id == 1:
			print(f'🚀 Analyzing {url} for {mode.capitalize()} ad...')
			page_data = await analyzer.analyze_landing_page(url, mode=mode)
		else:
			analyzer_temp = LandingPageAnalyzer(debug=debug)
			page_data = await analyzer_temp.analyze_landing_page(url, mode=mode)

		generator = AdGenerator(mode=mode)

		if mode == 'instagram':
			prompt = generator.create_ad_prompt(page_data['analysis'])
			ad_content = await generator.generate_ad_image(prompt, page_data.get('screenshot_path'))
			if ad_content is None:
				raise RuntimeError(f'Ad image generation failed for ad #{ad_id}')
		else:  # tiktok
			video_concept = await generator.create_video_concept(page_data['analysis'], ad_id)
			prompt = generator.create_ad_prompt(page_data['analysis'], video_concept)
			ad_content = await generator.generate_ad_video(prompt, page_data.get('screenshot_path'), ad_id)

		result_path = await generator.save_results(ad_content, prompt, page_data['analysis'], url, page_data['timestamp'])

		if mode == 'instagram':
			print(f'🎨 Generated image ad #{ad_id}: {result_path}')
		else:
			print(f'🎬 Generated video ad #{ad_id}: {result_path}')

		open_file(result_path)

		return result_path

	except Exception as e:
		print(f'❌ Error for ad #{ad_id}: {e}')
		raise
	finally:
		if ad_id == 1 and page_data.get('screenshot_path'):
			print(f'📸 Page screenshot: {page_data["screenshot_path"]}')


async def generate_single_ad(page_data: dict, mode: str, ad_id: int):
	"""Generate a single ad using pre-analyzed page data"""
	generator = AdGenerator(mode=mode)

	try:
		if mode == 'instagram':
			prompt = generator.create_ad_prompt(page_data['analysis'])
			ad_content = await generator.generate_ad_image(prompt, page_data.get('screenshot_path'))
			if ad_content is None:
				raise RuntimeError(f'Ad image generation failed for ad #{ad_id}')
		else:  # tiktok
			video_concept = await generator.create_video_concept(page_data['analysis'], ad_id)
			prompt = generator.create_ad_prompt(page_data['analysis'], video_concept)
			ad_content = await generator.generate_ad_video(prompt, page_data.get('screenshot_path'), ad_id)

		# Create unique timestamp for each ad
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S') + f'_{ad_id}'
		result_path = await generator.save_results(ad_content, prompt, page_data['analysis'], page_data['url'], timestamp)

		if mode == 'instagram':
			print(f'🎨 Generated image ad #{ad_id}: {result_path}')
		else:
			print(f'🎬 Generated video ad #{ad_id}: {result_path}')

		return result_path

	except Exception as e:
		print(f'❌ Error for ad #{ad_id}: {e}')
		raise


async def create_multiple_ads(url: str, debug: bool = False, mode: str = 'instagram', count: int = 1):
	"""Generate multiple ads in parallel using asyncio concurrency"""
	if count == 1:
		return await create_ad_from_landing_page(url, debug, mode, 1)

	print(f'🚀 Analyzing {url} for {count} {mode} ads...')

	analyzer = LandingPageAnalyzer(debug=debug)
	page_data = await analyzer.analyze_landing_page(url, mode=mode)

	print(f'🎯 Generating {count} {mode} ads in parallel...')

	tasks = []
	for i in range(count):
		task = create_task_with_error_handling(generate_single_ad(page_data, mode, i + 1), name=f'generate_ad_{i + 1}')
		tasks.append(task)

	results = await asyncio.gather(*tasks, return_exceptions=True)

	successful = []
	failed = []

	for i, result in enumerate(results):
		if isinstance(result, Exception):
			failed.append(i + 1)
		else:
			successful.append(result)

	print(f'\n✅ Successfully generated {len(successful)}/{count} ads')
	if failed:
		print(f'❌ Failed ads: {failed}')

	if page_data.get('screenshot_path'):
		print(f'📸 Page screenshot: {page_data["screenshot_path"]}')

	for ad_path in successful:
		open_file(ad_path)

	return successful


if __name__ == '__main__':
	url = args.url
	if not url:
		url = input('🔗 Enter URL: ').strip() or 'https://www.apple.com/iphone-17-pro/'

	if args.tiktok:
		mode = 'tiktok'
	else:
		mode = 'instagram'

	asyncio.run(create_multiple_ads(url, debug=args.debug, mode=mode, count=args.count))
