import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from browser_use.integrations.gmail.service import GmailService


def text_part(text: str, mime_type: str = 'text/plain', filename: str = '') -> dict[str, Any]:
	return {
		'mimeType': mime_type,
		'filename': filename,
		'body': {'data': base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')},
	}


@pytest.fixture
def gmail_service(tmp_path: Path) -> GmailService:
	return GmailService(config_dir=str(tmp_path))


@pytest.mark.parametrize(
	('payload', 'expected'),
	[
		pytest.param(text_part('Single-part body'), 'Single-part body', id='single-part'),
		pytest.param(
			{'mimeType': 'multipart/alternative', 'parts': [text_part('Plain body'), text_part('<p>HTML body</p>', 'text/html')]},
			'Plain body',
			id='flat-plain-first',
		),
		pytest.param(
			{'mimeType': 'multipart/alternative', 'parts': [text_part('<p>HTML body</p>', 'text/html'), text_part('Plain body')]},
			'Plain body',
			id='flat-html-first',
		),
		pytest.param(
			{
				'mimeType': 'multipart/alternative',
				'parts': [
					text_part('Plain body'),
					{'mimeType': 'text/html', 'body': {'data': base64.urlsafe_b64encode(b'\xff').decode('ascii')}},
				],
			},
			'Plain body',
			id='unused-html-is-not-decoded',
		),
		pytest.param(
			{
				'mimeType': 'multipart/mixed',
				'parts': [
					{
						'mimeType': 'multipart/alternative',
						'parts': [text_part('Your code is 123456'), text_part('<p>Your code is 123456</p>', 'text/html')],
					},
					{'mimeType': 'application/pdf', 'filename': 'receipt.pdf', 'body': {'attachmentId': 'attachment-1'}},
				],
			},
			'Your code is 123456',
			id='nested-plain-body',
		),
		pytest.param(
			{
				'mimeType': 'multipart/mixed',
				'parts': [{'mimeType': 'multipart/related', 'parts': [text_part('<p>HTML-only body</p>', 'text/html')]}],
			},
			'<p>HTML-only body</p>',
			id='nested-html-fallback',
		),
		pytest.param(
			{
				'mimeType': 'multipart/mixed',
				'parts': [
					text_part('First'),
					{'mimeType': 'multipart/mixed', 'parts': [text_part(' second'), text_part(' third')]},
				],
			},
			'First second third',
			id='preserve-part-order',
		),
		pytest.param(
			{
				'mimeType': 'multipart/mixed',
				'parts': [text_part('Attachment content', filename='notes.txt'), text_part('<p>Actual body</p>', 'text/html')],
			},
			'<p>Actual body</p>',
			id='text-attachment-is-not-body',
		),
		pytest.param({'mimeType': 'multipart/mixed', 'parts': []}, '', id='empty-message'),
	],
)
def test_extract_body(gmail_service: GmailService, payload: dict[str, Any], expected: str):
	assert gmail_service._extract_body(payload) == expected


def test_extract_body_deeply_nested(gmail_service: GmailService):
	payload = text_part('Nested body')
	for _ in range(1200):
		payload = {'mimeType': 'multipart/mixed', 'parts': [payload]}

	assert gmail_service._extract_body(payload) == 'Nested body'


async def test_get_recent_emails_returns_nested_body(gmail_service: GmailService):
	api = MagicMock()
	messages = api.users.return_value.messages.return_value
	messages.list.return_value.execute.return_value = {'messages': [{'id': 'message-1'}]}
	messages.get.return_value.execute.return_value = {
		'id': 'message-1',
		'threadId': 'thread-1',
		'internalDate': '1700000000000',
		'payload': {
			'headers': [{'name': 'Subject', 'value': 'Verification code'}],
			'mimeType': 'multipart/mixed',
			'parts': [{'mimeType': 'multipart/alternative', 'parts': [text_part('Your code is 123456')]}],
		},
	}
	gmail_service.service = api
	gmail_service._authenticated = True

	emails = await gmail_service.get_recent_emails()

	assert len(emails) == 1
	assert emails[0]['body'] == 'Your code is 123456'
	assert emails[0]['subject'] == 'Verification code'
	messages.get.assert_called_once_with(userId='me', id='message-1', format='full')
