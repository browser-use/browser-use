from pathlib import Path
from unittest.mock import MagicMock

import pytest

from browser_use.integrations.gmail import actions
from browser_use.integrations.gmail.service import GmailService
from browser_use.tools.service import Tools


@pytest.fixture
def gmail_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GmailService:
	service = GmailService(config_dir=str(tmp_path))
	service.service = MagicMock()
	service._authenticated = True
	service.service.users.return_value.messages.return_value.list.return_value.execute.return_value = {'messages': []}
	monkeypatch.setattr('time.time', lambda: 1_800_000_000)
	return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
	('time_filter', 'query', 'expected'),
	[
		('5m', 'otp', 'after:1799999700 otp'),
		('1h', '', 'after:1799996400'),
		('1d', 'invoice', 'newer_than:1d invoice'),
		('', 'otp', 'otp'),
		('5m', 'newer_than:2d otp', 'newer_than:2d otp'),
	],
)
async def test_gmail_time_filter(gmail_service: GmailService, time_filter: str, query: str, expected: str):
	assert await gmail_service.get_recent_emails(max_results=3, query=query, time_filter=time_filter) == []
	assert gmail_service.service is not None
	gmail_service.service.users().messages().list.assert_called_once_with(userId='me', maxResults=3, q=expected)


@pytest.mark.asyncio
async def test_gmail_action_uses_five_minute_window(gmail_service: GmailService, monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setattr(actions, '_gmail_service', None)
	tools = Tools()
	actions.register_gmail_actions(tools, gmail_service=gmail_service)

	await tools.registry.execute_action('get_recent_emails', {'keyword': 'otp'})

	assert gmail_service.service is not None
	gmail_service.service.users().messages().list.assert_called_once_with(userId='me', maxResults=3, q='after:1799999700 otp')
