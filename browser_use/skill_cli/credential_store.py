"""Local JSON-backed profile store for side-panel autofill."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

SENSITIVE_FIELD_TYPES = {'password', 'token', 'api_key', 'secret'}


class AutofillField(BaseModel):
	"""A single value that can be filled into a matching page field."""

	name: str
	value: str
	field_type: str = 'text'
	selectors: list[str] = Field(default_factory=list)
	aliases: list[str] = Field(default_factory=list)


class AutofillProfile(BaseModel):
	"""A group of fields scoped to one or more URL/domain match rules."""

	id: str
	label: str
	domains: list[str] = Field(default_factory=list)
	urls: list[str] = Field(default_factory=list)
	fields: list[AutofillField] = Field(default_factory=list)


class CredentialStoreData(BaseModel):
	"""Top-level persisted credential store schema."""

	version: int = 1
	profiles: list[AutofillProfile] = Field(default_factory=list)


def default_credential_store_path() -> Path:
	"""Return the default local credential store path."""

	base = Path(os.getenv('BROWSER_USE_HOME') or Path.home() / '.browser-use')
	return base / 'sidepanel_profiles.json'


def ensure_credential_store(path: str | Path | None = None) -> Path:
	"""Create an empty credential store if it does not exist."""

	store_path = Path(path).expanduser() if path else default_credential_store_path()
	store_path.parent.mkdir(parents=True, exist_ok=True)
	if not store_path.exists():
		store_path.write_text(
			json.dumps(CredentialStoreData().model_dump(mode='json'), indent=2, ensure_ascii=False),
			encoding='utf-8',
		)
	return store_path


def _normalize_domain(value: str) -> str:
	text = value.strip().lower()
	text = re.sub(r'^https?://', '', text)
	text = text.split('/', 1)[0]
	text = text.split(':', 1)[0]
	return text.lstrip('.')


def _url_matches_pattern(url: str, pattern: str) -> bool:
	if not pattern.strip():
		return False
	if pattern.startswith('regex:'):
		try:
			return bool(re.search(pattern.removeprefix('regex:'), url))
		except re.error:
			return False
	if '*' in pattern:
		regex = '^' + re.escape(pattern).replace('\\*', '.*') + '$'
		return bool(re.match(regex, url, flags=re.IGNORECASE))
	return url.rstrip('/').lower().startswith(pattern.rstrip('/').lower())


def profile_matches_url(profile: AutofillProfile, url: str) -> bool:
	"""Return whether a profile is allowed for the supplied URL."""

	parsed = urlparse(url)
	host = _normalize_domain(parsed.netloc)
	if not host:
		return False

	for domain in profile.domains:
		normalized = _normalize_domain(domain)
		if host == normalized or host.endswith(f'.{normalized}'):
			return True
	for pattern in profile.urls:
		if _url_matches_pattern(url, pattern):
			return True
	return False


class CredentialStore:
	"""Load and query a local JSON credential store."""

	def __init__(self, path: str | Path | None = None):
		self.path = ensure_credential_store(path)

	def load(self) -> CredentialStoreData:
		try:
			raw = json.loads(self.path.read_text(encoding='utf-8'))
		except json.JSONDecodeError as exc:
			raise ValueError(f'Invalid credential store JSON: {self.path}') from exc
		return CredentialStoreData.model_validate(raw)

	def save(self, data: CredentialStoreData) -> None:
		"""Persist credential store data."""

		self.path.write_text(
			json.dumps(data.model_dump(mode='json'), indent=2, ensure_ascii=False),
			encoding='utf-8',
		)

	def add_profile(
		self,
		label: str,
		url: str,
		fields: list[AutofillField],
		profile_id: str | None = None,
	) -> AutofillProfile:
		"""Create and persist an autofill profile for a URL."""

		parsed = urlparse(url)
		host = _normalize_domain(parsed.netloc)
		if not host:
			raise ValueError('url must include a valid http(s) domain')

		profile = AutofillProfile(
			id=profile_id or uuid7str(),
			label=label,
			domains=[host],
			urls=[url],
			fields=fields,
		)
		data = self.load()
		data.profiles = [existing for existing in data.profiles if existing.id != profile.id]
		data.profiles.append(profile)
		self.save(data)
		return profile

	def matching_profiles(self, url: str) -> list[AutofillProfile]:
		data = self.load()
		return [profile for profile in data.profiles if profile_matches_url(profile, url)]

	def preview_matches(self, url: str) -> list[dict[str, Any]]:
		"""Return non-secret metadata for profiles matching a URL."""

		previews: list[dict[str, Any]] = []
		for profile in self.matching_profiles(url):
			previews.append(
				{
					'id': profile.id,
					'label': profile.label,
					'field_count': len(profile.fields),
					'fields': [
						{
							'name': field.name,
							'field_type': field.field_type,
							'masked': field.field_type.lower() in SENSITIVE_FIELD_TYPES,
							'selectors': field.selectors,
							'aliases': field.aliases,
						}
						for field in profile.fields
					],
				}
			)
		return previews

	def resolve_values(self, url: str, profile_id: str | None = None) -> dict[str, Any] | None:
		"""Return fillable values for a matching profile after explicit request."""

		matches = self.matching_profiles(url)
		if profile_id:
			matches = [profile for profile in matches if profile.id == profile_id]
		if not matches:
			return None
		profile = matches[0]
		return {
			'id': profile.id,
			'label': profile.label,
			'fields': [field.model_dump(mode='json') for field in profile.fields],
		}
