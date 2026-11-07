from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import ARTIFACT_DIR, DOWNLOADS_DIR

logger = logging.getLogger('browser_buddy.artifacts')

URL_RE = re.compile(r'https?://[^\s<>"\')\]\u4e00-\u9fff，。；：！？、]+')
TRAILING_URL_CHARS = '.,;:!?，。；：！？'
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')


def extract_urls(text: str, limit: int = 5) -> list[str]:
	urls: list[str] = []
	seen: set[str] = set()
	for raw in URL_RE.findall(text or ''):
		url = raw.rstrip(TRAILING_URL_CHARS)
		if not url or urlparse(url).scheme not in ('http', 'https'):
			continue
		key = url.rstrip('/').lower()
		if key in seen:
			continue
		seen.add(key)
		urls.append(url)
		if len(urls) >= limit:
			break
	return urls


async def _fetch_source(client: httpx.AsyncClient, url: str) -> dict[str, str]:
	try:
		resp = await client.get(url)
		resp.raise_for_status()
		soup = BeautifulSoup(resp.text[:250_000], 'html.parser')

		title = soup.title.string.strip() if soup.title and soup.title.string else ''
		og_title = soup.find('meta', property='og:title')
		if og_title and og_title.get('content'):
			title = og_title['content'].strip()

		description = ''
		for attrs in ({'property': 'og:description'}, {'name': 'description'}):
			tag = soup.find('meta', attrs=attrs)
			if tag and tag.get('content'):
				description = tag['content'].strip()
				break

		image = ''
		for attrs in (
			{'property': 'og:image'},
			{'name': 'twitter:image'},
			{'name': 'twitter:image:src'},
		):
			tag = soup.find('meta', attrs=attrs)
			if tag and tag.get('content'):
				image = urljoin(url, tag['content'].strip())
				break

		if not image:
			icon = soup.find('link', rel=lambda value: value and 'icon' in value)
			if icon and icon.get('href'):
				image = urljoin(url, icon['href'])

		if image and urlparse(image).scheme not in ('http', 'https'):
			image = ''

		return {
			'url': url,
			'title': title or url,
			'description': description,
			'image': image,
			'domain': urlparse(url).netloc,
		}
	except Exception:
		return {
			'url': url,
			'title': url,
			'description': '',
			'image': '',
			'domain': urlparse(url).netloc,
		}


async def build_sources(text: str, history_urls: list[str] | None = None, limit: int = 5) -> list[dict[str, str]]:
	urls = extract_urls(text, limit=limit)
	if not urls and history_urls:
		seen: set[str] = set()
		urls = []
		for url in reversed(history_urls):
			if urlparse(url).scheme not in ('http', 'https'):
				continue
			key = url.rstrip('/').lower()
			if key in seen:
				continue
			seen.add(key)
			urls.append(url)
			if len(urls) >= limit:
				break
		urls.reverse()
	if not urls:
		return []

	headers = {
		'User-Agent': (
			'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
			'(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
		)
	}
	async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
		results = await asyncio.gather(
			*(_fetch_source(client, url) for url in urls[:limit]),
			return_exceptions=True,
		)
	return [item for item in results if isinstance(item, dict)]


def _artifact_url(path: Path) -> str:
	return f'/artifacts/{quote(path.name)}'


def _pdf_preview(pdf_path: Path) -> Path | None:
	preview_path = pdf_path.with_suffix('.png')
	if preview_path.exists():
		return preview_path
	try:
		subprocess.run(
			['sips', '-s', 'format', 'png', str(pdf_path), '--out', str(preview_path)],
			check=True,
			capture_output=True,
			timeout=20,
		)
		return preview_path if preview_path.exists() else None
	except Exception as e:
		logger.warning(f'Could not render PDF preview for {pdf_path}: {type(e).__name__}: {e}')
		return None


def collect_artifacts(history) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
	files: list[dict[str, str]] = []
	images: list[dict[str, str]] = []
	seen_files: set[str] = set()
	seen_images: set[str] = set()

	for item in getattr(history, 'history', []):
		for result in getattr(item, 'result', []):
			for raw_path in getattr(result, 'attachments', None) or []:
				source = Path(raw_path).expanduser()
				if not source.exists() and not source.is_absolute():
					source = DOWNLOADS_DIR / source
				if not source.exists():
					continue

				copied = ARTIFACT_DIR / f'{source.stem}-{source.stat().st_mtime_ns}{source.suffix}'
				if not copied.exists():
					try:
						shutil.copy2(source, copied)
					except Exception as e:
						logger.warning(f'Could not copy attachment {source}: {type(e).__name__}: {e}')
						copied = source

				path_key = str(copied)
				if path_key not in seen_files:
					files.append(
						{
							'name': copied.name,
							'display_name': source.name,
							'url': _artifact_url(copied),
							'kind': copied.suffix.lower().lstrip('.') or 'file',
						}
					)
					seen_files.add(path_key)

				suffix = copied.suffix.lower()
				image_path: Path | None = None
				if suffix in IMAGE_SUFFIXES:
					image_path = copied
				elif suffix == '.pdf':
					image_path = _pdf_preview(copied)

				if image_path and str(image_path) not in seen_images:
					display_name = source.name if suffix in IMAGE_SUFFIXES else f'{source.stem} 预览'
					images.append(
						{
							'name': image_path.name,
							'display_name': display_name,
							'url': _artifact_url(image_path),
						}
					)
					seen_images.add(str(image_path))

	return files, images
