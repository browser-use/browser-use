"""Client for the skillbase server — fetches domain skill indexes and individual skill files."""

import logging
import os
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SKILLBASE_URL = 'https://skills.browser-use.tools'


def normalize_domain(url: str) -> str:
	"""Extract the registrable domain from a URL (e.g. 'https://en.wikipedia.org/wiki/X' -> 'wikipedia.org')."""
	try:
		hostname = urlparse(url).hostname or ''
	except Exception:
		return ''
	parts = hostname.split('.')
	if len(parts) >= 2:
		return '.'.join(parts[-2:])
	return hostname


class SkillbaseService:
	"""Fetches skill indexes and skill files from the skillbase HTTP API."""

	def __init__(self, api_key: str | None = None, base_url: str | None = None):
		self.api_key = api_key or os.getenv('SKILLBASE_API_KEY', '')
		self.base_url = (base_url or os.getenv('SKILLBASE_URL', DEFAULT_SKILLBASE_URL)).rstrip('/')
		if not self.api_key:
			raise ValueError('SKILLBASE_API_KEY is required (set env var or pass api_key)')
		self._client = httpx.AsyncClient(
			base_url=self.base_url,
			headers={'x-api-key': self.api_key},
			timeout=10,
		)
		self._fetched_domains: dict[str, list[dict] | None] = {}

	async def fetch_index(self, domain: str) -> list[dict] | None:
		"""Fetch the skill index for a domain. Returns list of {file, for} or None if no skills."""
		if domain in self._fetched_domains:
			return self._fetched_domains[domain]
		try:
			r = await self._client.get(f'/skills/{domain}')
			if r.status_code == 200:
				data = r.json()
				skills = data.get('skills', [])
				self._fetched_domains[domain] = skills
				logger.info(f'Fetched {len(skills)} skills for {domain}')
				return skills
			self._fetched_domains[domain] = None
			return None
		except Exception as e:
			logger.warning(f'Skillbase fetch failed for {domain}: {e}')
			self._fetched_domains[domain] = None
			return None

	async def fetch_skill(self, domain: str, filename: str) -> str | None:
		"""Fetch the raw markdown content of a single skill file."""
		try:
			r = await self._client.get(f'/skills/{domain}/{filename}')
			if r.status_code == 200:
				return r.text
			return None
		except Exception as e:
			logger.warning(f'Skillbase fetch failed for {domain}/{filename}: {e}')
			return None

	def format_index(self, domain: str, skills: list[dict]) -> str:
		"""Format a skill index into a string for injection into agent context."""
		lines = [f'Available skills for {domain}:']
		for s in skills:
			lines.append(f'  - {s["file"]}: {s["for"]}')
		lines.append('Use read_skill to read any skill relevant to your current task.')
		return '\n'.join(lines)

	async def close(self) -> None:
		await self._client.aclose()
