"""Tests for the accounts management module."""

import json
import tempfile
from pathlib import Path

import pytest

from browser_use.accounts.service import AccountService
from browser_use.accounts.views import Account, AccountCredentials, AccountsData, PLATFORM_DOMAINS


@pytest.fixture
def accounts_file(tmp_path):
	"""Create a temporary accounts JSON file with test data."""
	data = AccountsData(
		accounts=[
			Account(
				id='test-id-1',
				label='My GitHub',
				platform='github',
				domains=['github.com', '*.github.com'],
				credentials=AccountCredentials(
					username='testuser',
					password='testpass123',
					email='test@example.com',
				),
				metadata={'nickname': 'tester'},
			),
			Account(
				id='test-id-2',
				label='淘宝账号',
				platform='taobao',
				domains=['taobao.com', '*.taobao.com', 'login.taobao.com'],
				credentials=AccountCredentials(
					username='taobao_user',
					password='taobao_pass',
					phone='13800001234',
				),
			),
			Account(
				id='test-id-3',
				label='Amazon US',
				platform='amazon',
				domains=['amazon.com', '*.amazon.com'],
				credentials=AccountCredentials(
					username='amazon_user@email.com',
					password='amazon_pass',
				),
			),
		]
	)
	file_path = tmp_path / 'accounts.json'
	file_path.write_text(json.dumps(data.model_dump(mode='json'), indent=2, ensure_ascii=False))
	return file_path


@pytest.fixture
def service(accounts_file):
	"""Create an AccountService with test data."""
	return AccountService(path=accounts_file)


class TestAccountService:
	def test_load_accounts(self, service):
		data = service.load()
		assert len(data.accounts) == 3
		assert data.accounts[0].label == 'My GitHub'

	def test_get_all_accounts(self, service):
		accounts = service.get_all_accounts()
		assert len(accounts) == 3

	def test_get_account_by_label_exact(self, service):
		account = service.get_account_by_label('My GitHub')
		assert account is not None
		assert account.platform == 'github'
		assert account.credentials.username == 'testuser'

	def test_get_account_by_label_case_insensitive(self, service):
		account = service.get_account_by_label('my github')
		assert account is not None
		assert account.platform == 'github'

	def test_get_account_by_label_partial(self, service):
		account = service.get_account_by_label('github')
		assert account is not None
		assert account.platform == 'github'

	def test_get_account_by_label_not_found(self, service):
		account = service.get_account_by_label('nonexistent')
		assert account is None

	def test_get_account_by_platform(self, service):
		account = service.get_account_by_platform('taobao')
		assert account is not None
		assert account.label == '淘宝账号'
		assert account.credentials.phone == '13800001234'

	def test_get_accounts_for_url_exact_domain(self, service):
		accounts = service.get_accounts_for_url('https://github.com/browser-use/browser-use')
		assert len(accounts) == 1
		assert accounts[0].platform == 'github'

	def test_get_accounts_for_url_wildcard(self, service):
		accounts = service.get_accounts_for_url('https://login.taobao.com/member/login.jhtml')
		assert len(accounts) == 1
		assert accounts[0].platform == 'taobao'

	def test_get_accounts_for_url_no_match(self, service):
		accounts = service.get_accounts_for_url('https://unknown-site.org/page')
		assert len(accounts) == 0

	def test_add_account_auto_domains(self, service):
		account = service.add_account(
			label='My Google',
			platform='google',
			credentials={'username': 'guser', 'password': 'gpass'},
		)
		assert account.platform == 'google'
		assert 'google.com' in account.domains or '*.google.com' in account.domains
		# Verify persisted
		reloaded = AccountService(path=service.path)
		assert len(reloaded.get_all_accounts()) == 4

	def test_add_account_custom_domains(self, service):
		account = service.add_account(
			label='Custom Site',
			platform='mysite',
			credentials={'username': 'u', 'password': 'p'},
			domains=['mysite.io', '*.mysite.io'],
		)
		assert account.domains == ['mysite.io', '*.mysite.io']

	def test_remove_account(self, service):
		result = service.remove_account('test-id-1')
		assert result is True
		assert len(service.get_all_accounts()) == 2

	def test_remove_account_not_found(self, service):
		result = service.remove_account('nonexistent-id')
		assert result is False

	def test_update_account(self, service):
		updated = service.update_account('test-id-1', label='Updated GitHub')
		assert updated is not None
		assert updated.label == 'Updated GitHub'

	def test_update_account_credentials(self, service):
		updated = service.update_account('test-id-1', credentials={'password': 'newpass'})
		assert updated is not None
		assert updated.credentials.password == 'newpass'
		# Original fields preserved
		assert updated.credentials.username == 'testuser'

	def test_to_sensitive_data(self, service):
		account = service.get_account_by_platform('github')
		result = service.to_sensitive_data(account=account)
		assert len(result) > 0
		# Should be keyed by domain pattern
		domain_key = list(result.keys())[0]
		creds = result[domain_key]
		assert isinstance(creds, dict)
		assert 'github_username' in creds
		assert creds['github_username'] == 'testuser'
		assert 'github_password' in creds
		assert creds['github_password'] == 'testpass123'

	def test_get_sensitive_data_for_url(self, service):
		result = service.get_sensitive_data_for_url('https://github.com/login')
		assert len(result) > 0
		domain_key = list(result.keys())[0]
		creds = result[domain_key]
		assert 'github_username' in creds

	def test_detect_platform_from_url(self):
		assert AccountService.detect_platform_from_url('https://github.com/user/repo') == 'github'
		assert AccountService.detect_platform_from_url('https://www.taobao.com/item/123') == 'taobao'
		assert AccountService.detect_platform_from_url('https://amazon.com/dp/B123') == 'amazon'
		assert AccountService.detect_platform_from_url('https://unknown.org/page') is None
		assert AccountService.detect_platform_from_url('https://accounts.google.com/signin') == 'google'

	def test_ensure_file_creates_new(self, tmp_path):
		new_path = tmp_path / 'new_accounts.json'
		assert not new_path.exists()
		service = AccountService(path=new_path)
		service.load()
		assert new_path.exists()
		data = json.loads(new_path.read_text())
		assert data['version'] == 1
		assert data['accounts'] == []


class TestGitHubHelpers:
	"""Test the GitHub URL helper functions."""

	def test_extract_github_repo(self):
		from browser_use.tools.service import _extract_github_repo

		assert _extract_github_repo('https://github.com/browser-use/browser-use') == 'browser-use/browser-use'
		assert _extract_github_repo('https://github.com/owner/repo/tree/main/src') == 'owner/repo'
		assert _extract_github_repo('https://github.com/owner/repo.git') == 'owner/repo'
		assert _extract_github_repo('https://google.com/something') is None
		assert _extract_github_repo('https://github.com/owner/repo/blob/main/file.py') == 'owner/repo'

	def test_extract_github_branch(self):
		from browser_use.tools.service import _extract_github_branch

		assert _extract_github_branch('https://github.com/owner/repo/tree/main/src') == 'main'
		assert _extract_github_branch('https://github.com/owner/repo/blob/develop/file.py') == 'develop'
		assert _extract_github_branch('https://github.com/owner/repo') is None
		assert _extract_github_branch('https://github.com/owner/repo/issues') is None
