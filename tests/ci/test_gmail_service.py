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


@pytest.mark.parametrize(
	('header_name', 'disposition'),
	[
		('Content-Disposition', 'attachment'),
		('content-disposition', 'Attachment; filename=""'),
		('CONTENT-DISPOSITION', ' ATTACHMENT ; size=123'),
	],
)
@pytest.mark.parametrize('multipart_attachment', [False, True])
def test_extract_body_excludes_unnamed_attachments(
	gmail_service: GmailService, header_name: str, disposition: str, multipart_attachment: bool
):
	attachment = text_part('Attachment content')
	if multipart_attachment:
		attachment = {'mimeType': 'multipart/mixed', 'parts': [attachment]}
	attachment['headers'] = [{'name': header_name, 'value': disposition}]
	payload = {
		'mimeType': 'multipart/mixed',
		'parts': [attachment, text_part('<p>Actual body</p>', 'text/html')],
	}

	assert gmail_service._extract_body(payload) == '<p>Actual body</p>'


def test_extract_body_preserves_inline_text(gmail_service: GmailService):
	payload = text_part('Inline body')
	payload['headers'] = [{'name': 'Content-Disposition', 'value': 'inline'}]

	assert gmail_service._extract_body(payload) == 'Inline body'


@pytest.mark.parametrize(
	('mime_type', 'content_type', 'raw', 'expected'),
	[
		('text/plain', 'text/plain; charset="ISO-8859-1"', b'caf\xe9', 'café'),
		('text/html', 'text/html; charset=windows-1252', b'<p>\x93Hello\x94</p>', '<p>“Hello”</p>'),
		('text/plain', 'text/plain; charset=utf-16', '你好'.encode('utf-16'), '你好'),
		('text/plain', 'text/plain; charset=shift_jis', '日本語'.encode('shift_jis'), '日本語'),
		('text/plain', 'text/plain; charset=unknown-charset', 'café'.encode(), 'café'),
		('text/plain', 'text/plain; charset=unknown-charset', b'caf\xff', 'caf�'),
		('text/plain', 'text/plain; charset=utf-8', b'caf\xff', 'caf�'),
		('text/plain', 'text/plain; charset=ascii', b'caf\xff', 'caf�'),
		('text/plain', 'text/plain', b'caf\xff', 'caf�'),
	],
)
def test_extract_body_decodes_declared_charset(
	gmail_service: GmailService, mime_type: str, content_type: str, raw: bytes, expected: str
):
	payload = {
		'mimeType': 'multipart/mixed',
		'parts': [
			{
				'mimeType': mime_type,
				'headers': [{'name': 'content-type', 'value': content_type}],
				'body': {'data': base64.urlsafe_b64encode(raw).decode('ascii')},
			}
		],
	}

	assert gmail_service._extract_body(payload) == expected


def test_extract_body_decodes_each_part_separately(gmail_service: GmailService):
	latin_part = {
		'mimeType': 'text/plain',
		'headers': [{'name': 'Content-Type', 'value': 'text/plain; charset=iso-8859-1'}],
		'body': {'data': base64.urlsafe_b64encode(b'caf\xe9 ').decode('ascii')},
	}
	payload = {'mimeType': 'multipart/mixed', 'parts': [latin_part, text_part('日本語')]}

	assert gmail_service._extract_body(payload) == 'café 日本語'


async def test_get_recent_emails_preserves_batch_with_non_utf8_body(gmail_service: GmailService):
	api = MagicMock()
	messages = api.users.return_value.messages.return_value
	messages.list.return_value.execute.return_value = {'messages': [{'id': 'message-1'}, {'id': 'message-2'}]}
	latin_part = {
		'mimeType': 'text/plain',
		'headers': [{'name': 'Content-Type', 'value': 'text/plain; charset=iso-8859-1'}],
		'body': {'data': base64.urlsafe_b64encode(b'caf\xe9').decode('ascii')},
	}
	messages.get.return_value.execute.side_effect = [
		{
			'id': message_id,
			'threadId': message_id,
			'internalDate': '1700000000000',
			'payload': {'headers': [], 'mimeType': 'multipart/mixed', 'parts': [body]},
		}
		for message_id, body in [('message-1', text_part('Earlier valid body')), ('message-2', latin_part)]
	]
	gmail_service.service = api
	gmail_service._authenticated = True

	emails = await gmail_service.get_recent_emails()

	assert [email['body'] for email in emails] == ['Earlier valid body', 'café']


@pytest.mark.parametrize('mime_type', ['text/plain', 'text/html'])
def test_extract_body_skips_malformed_part_and_preserves_valid_parts(gmail_service: GmailService, mime_type: str):
	payload = {
		'mimeType': 'multipart/mixed',
		'parts': [
			text_part('First', mime_type),
			{'mimeType': mime_type, 'body': {'data': 'a'}},
			text_part(' last', mime_type),
		],
	}

	assert gmail_service._extract_body(payload) == 'First last'


@pytest.mark.parametrize('data', ['a', 'not-ascii-✓', '%%%%'])
def test_extract_body_falls_back_to_html_when_plain_body_is_unusable(gmail_service: GmailService, data: str):
	payload = {
		'mimeType': 'multipart/alternative',
		'parts': [
			{'mimeType': 'text/plain', 'body': {'data': data}},
			text_part('<p>Valid HTML</p>', 'text/html'),
		],
	}

	assert gmail_service._extract_body(payload) == '<p>Valid HTML</p>'


def test_extract_body_returns_empty_when_all_parts_are_malformed(gmail_service: GmailService):
	payload = {
		'mimeType': 'multipart/alternative',
		'parts': [{'mimeType': mime_type, 'body': {'data': 'a'}} for mime_type in ('text/plain', 'text/html')],
	}

	assert gmail_service._extract_body(payload) == ''


async def test_get_recent_emails_preserves_batch_with_malformed_body(gmail_service: GmailService):
	api = MagicMock()
	messages = api.users.return_value.messages.return_value
	message_bodies = [
		('message-1', text_part('Earlier valid body')),
		('message-2', {'mimeType': 'text/plain', 'body': {'data': 'a'}}),
		('message-3', text_part('Later valid body')),
	]
	messages.list.return_value.execute.return_value = {'messages': [{'id': message_id} for message_id, _ in message_bodies]}
	messages.get.return_value.execute.side_effect = [
		{
			'id': message_id,
			'threadId': message_id,
			'internalDate': '1700000000000',
			'payload': {'headers': [], **body},
		}
		for message_id, body in message_bodies
	]
	gmail_service.service = api
	gmail_service._authenticated = True

	emails = await gmail_service.get_recent_emails()

	assert [(email['id'], email['body']) for email in emails] == [
		('message-1', 'Earlier valid body'),
		('message-2', ''),
		('message-3', 'Later valid body'),
	]
