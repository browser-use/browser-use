"""Account management service for browser-use agent."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from uuid_extensions import uuid7str

from browser_use.accounts.views import (
	Account,
	AccountCredentials,
	AccountsData,
	PLATFORM_DOMAINS,
)

logger = logging.getLogger(__name__)

DEFAULT_ACCOUNTS_FILENAME = 'accounts.json'


class AccountService:
	"""Manage user accounts stored in a local JSON file.

	Provides platform auto-detection, domain matching, and conversion
	to the sensitive_data format used by the agent's credential injection.
	"""

	def __init__(self, path: str | Path | None = None):
		"""Initialize with path to accounts JSON file.

		Args:
			path: Path to accounts.json. If None, uses ./accounts.json in cwd.
		"""
		self.path = Path(path).expanduser().resolve() if path else Path.cwd() / DEFAULT_ACCOUNTS_FILENAME
		self._data: AccountsData | None = None

	def _ensure_file(self) -> None:
		"""Create an empty accounts file if it does not exist."""
		if not self.path.exists():
			self.path.parent.mkdir(parents=True, exist_ok=True)
			empty = AccountsData()
			self.path.write_text(
				json.dumps(empty.model_dump(mode='json'), indent=2, ensure_ascii=False),
				encoding='utf-8',
			)
			logger.info(f'Created new accounts file: {self.path}')

	def load(self) -> AccountsData:
		"""Load accounts from the JSON file."""
		self._ensure_file()
		try:
			raw = json.loads(self.path.read_text(encoding='utf-8'))
		except json.JSONDecodeError as exc:
			raise ValueError(f'Invalid accounts JSON at {self.path}: {exc}') from exc
		self._data = AccountsData.model_validate(raw)
		return self._data

	def save(self) -> None:
		"""Persist current accounts data to disk."""
		assert self._data is not None, 'No data loaded; call load() first'
		self.path.write_text(
			json.dumps(self._data.model_dump(mode='json'), indent=2, ensure_ascii=False),
			encoding='utf-8',
		)

	def _get_data(self) -> AccountsData:
		"""Get loaded data, loading from file if needed."""
		if self._data is None:
			self.load()
		assert self._data is not None
		return self._data

	# --- Query methods ---

	def get_all_accounts(self) -> list[Account]:
		"""Return all stored accounts."""
		return self._get_data().accounts

	def get_account_by_label(self, label: str) -> Account | None:
		"""Find an account by its label (case-insensitive partial match)."""
		label_lower = label.lower()
		for account in self._get_data().accounts:
			if account.label.lower() == label_lower:
				return account
		# Partial match fallback
		for account in self._get_data().accounts:
			if label_lower in account.label.lower() or label_lower in account.platform.lower():
				return account
		return None

	def get_account_by_platform(self, platform: str) -> Account | None:
		"""Find an account by platform name."""
		platform_lower = platform.lower()
		for account in self._get_data().accounts:
			if account.platform.lower() == platform_lower:
				return account
		return None

	def get_accounts_for_url(self, url: str) -> list[Account]:
		"""Find all accounts whose domains match the given URL."""
		parsed = urlparse(url)
		host = parsed.netloc.lower().split(':')[0]
		if not host:
			return []

		matched: list[Account] = []
		for account in self._get_data().accounts:
			if self._account_matches_host(account, host):
				matched.append(account)
		return matched

	def _account_matches_host(self, account: Account, host: str) -> bool:
		"""Check if an account's domains match a hostname."""
		for domain in account.domains:
			domain = domain.lower().strip()
			if domain.startswith('*.'):
				# Wildcard: *.example.com matches sub.example.com and example.com
				base = domain[2:]
				if host == base or host.endswith(f'.{base}'):
					return True
			elif host == domain or host.endswith(f'.{domain}'):
				return True
		return False

	# --- Mutation methods ---

	def add_account(
		self,
		label: str,
		platform: str,
		credentials: dict[str, str | None] | None = None,
		domains: list[str] | None = None,
		metadata: dict[str, Any] | None = None,
	) -> Account:
		"""Add a new account entry.

		If domains is not provided, auto-detects from the platform name.
		"""
		# Auto-detect domains from platform
		if domains is None:
			domains = PLATFORM_DOMAINS.get(platform.lower(), [])
			if not domains:
				# Fallback: use platform as domain
				domains = [f'{platform.lower()}.com']

		creds = AccountCredentials(**(credentials or {}))
		now = datetime.now(timezone.utc).isoformat()

		account = Account(
			id=uuid7str(),
			label=label,
			platform=platform.lower(),
			domains=domains,
			credentials=creds,
			metadata=metadata or {},
			created_at=now,
			updated_at=now,
		)

		data = self._get_data()
		data.accounts.append(account)
		self.save()
		logger.info(f'Added account: {label} (platform={platform}, domains={domains})')
		return account

	def remove_account(self, account_id: str) -> bool:
		"""Remove an account by ID. Returns True if found and removed."""
		data = self._get_data()
		before = len(data.accounts)
		data.accounts = [a for a in data.accounts if a.id != account_id]
		if len(data.accounts) < before:
			self.save()
			return True
		return False

	def update_account(self, account_id: str, **updates: Any) -> Account | None:
		"""Update fields on an existing account."""
		data = self._get_data()
		for account in data.accounts:
			if account.id == account_id:
				for key, value in updates.items():
					if key == 'credentials' and isinstance(value, dict):
						# Merge credentials
						existing = account.credentials.model_dump(exclude_none=True)
						existing.update(value)
						account.credentials = AccountCredentials(**existing)
					elif hasattr(account, key):
						setattr(account, key, value)
				account.updated_at = datetime.now(timezone.utc).isoformat()
				self.save()
				return account
		return None

	# --- Integration with Agent sensitive_data ---

	def to_sensitive_data(self, account: Account | None = None, url: str | None = None) -> dict[str, str | dict[str, str]]:
		"""Convert account(s) to the sensitive_data dict format used by Agent.

		If account is provided, uses that specific account.
		If url is provided, finds matching accounts for that URL.
		Returns domain-keyed format: {domain_pattern: {key: value}}
		"""
		accounts_to_convert: list[Account] = []

		if account is not None:
			accounts_to_convert = [account]
		elif url is not None:
			accounts_to_convert = self.get_accounts_for_url(url)

		if not accounts_to_convert:
			return {}

		result: dict[str, str | dict[str, str]] = {}

		for acct in accounts_to_convert:
			# Build the credentials dict (non-None values only)
			creds_dict: dict[str, str] = {}
			cred_data = acct.credentials.model_dump(exclude_none=True)
			for key, value in cred_data.items():
				if value:
					# Prefix with platform to avoid collisions
					creds_dict[f'{acct.platform}_{key}'] = str(value)

			if not creds_dict:
				continue

			# Use the first domain as key, or platform wildcard
			if acct.domains:
				domain_key = acct.domains[0]
				# Normalize: ensure it works with the agent's domain matching
				if domain_key.startswith('*.'):
					domain_key = domain_key  # Already a pattern
				else:
					domain_key = f'*.{domain_key}'
			else:
				domain_key = f'*.{acct.platform}.com'

			result[domain_key] = creds_dict

		return result

	def get_sensitive_data_for_url(self, url: str) -> dict[str, str | dict[str, str]]:
		"""Get sensitive_data dict for all accounts matching a URL."""
		return self.to_sensitive_data(url=url)

	# --- Platform detection ---

	@staticmethod
	def detect_platform_from_url(url: str) -> str | None:
		"""Detect platform name from a URL using built-in domain mappings."""
		parsed = urlparse(url)
		host = parsed.netloc.lower().split(':')[0]
		if not host:
			return None

		for platform, domains in PLATFORM_DOMAINS.items():
			for domain in domains:
				domain = domain.lower()
				if domain.startswith('*.'):
					base = domain[2:]
					if host == base or host.endswith(f'.{base}'):
						return platform
				elif host == domain or host.endswith(f'.{domain}'):
					return platform
		return None
