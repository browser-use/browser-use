"""Regression tests for GmailService._extract_body nested-multipart handling.

Reproduces the silent-empty-body bug where text leaves nested inside intermediate
``multipart/*`` containers (the common shape for HTML and 2FA/OTP emails) were
dropped because the extractor only scanned the top-level ``parts``. Also covers
defensive handling of malformed and adversarially nested payloads.
"""

import base64

from browser_use.integrations.gmail.service import GmailService


def _b64(text: str) -> str:
	return base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')


def _service() -> GmailService:
	# _extract_body uses no instance state, so skip __init__ (which needs OAuth config).
	return GmailService.__new__(GmailService)


def test_nested_multipart_alternative_prefers_plain_text():
	payload = {
		'mimeType': 'multipart/mixed',
		'parts': [
			{
				'mimeType': 'multipart/alternative',
				'parts': [
					{'mimeType': 'text/plain', 'body': {'data': _b64('Your code is 123456')}},
					{'mimeType': 'text/html', 'body': {'data': _b64('<p>Your code is 123456</p>')}},
				],
			},
			{'mimeType': 'application/pdf', 'filename': 'x.pdf', 'body': {'attachmentId': 'a1'}},
		],
	}
	assert _service()._extract_body(payload) == 'Your code is 123456'


def test_nested_html_only_falls_back_to_html():
	payload = {
		'mimeType': 'multipart/mixed',
		'parts': [
			{
				'mimeType': 'multipart/related',
				'parts': [
					{'mimeType': 'text/html', 'body': {'data': _b64('<p>Hello</p>')}},
				],
			},
		],
	}
	assert _service()._extract_body(payload) == '<p>Hello</p>'


def test_simple_top_level_body_unchanged():
	payload = {'mimeType': 'text/plain', 'body': {'data': _b64('plain top level')}}
	assert _service()._extract_body(payload) == 'plain top level'


def test_flat_multipart_still_works():
	payload = {
		'mimeType': 'multipart/alternative',
		'parts': [
			{'mimeType': 'text/plain', 'body': {'data': _b64('flat plain')}},
			{'mimeType': 'text/html', 'body': {'data': _b64('<p>flat</p>')}},
		],
	}
	assert _service()._extract_body(payload) == 'flat plain'


def test_empty_payload_returns_empty_string():
	assert _service()._extract_body({'mimeType': 'multipart/mixed'}) == ''


def test_malformed_nested_leaf_does_not_block_valid_sibling():
	# A malformed base64 leaf must be skipped, not abort the whole traversal.
	payload = {
		'mimeType': 'multipart/mixed',
		'parts': [
			{
				'mimeType': 'multipart/alternative',
				'parts': [
					{'mimeType': 'text/plain', 'body': {'data': '!!!not-valid-base64!!!'}},
					{'mimeType': 'text/plain', 'body': {'data': _b64('recovered body')}},
				],
			},
		],
	}
	assert _service()._extract_body(payload) == 'recovered body'


def test_deeply_nested_payload_does_not_raise():
	# Build a pathologically deep multipart tree; extraction must not raise.
	leaf = {'mimeType': 'text/plain', 'body': {'data': _b64('deep')}}
	node = leaf
	for _ in range(500):
		node = {'mimeType': 'multipart/mixed', 'parts': [node]}
	# Should return '' (beyond depth bound) rather than raising RecursionError.
	result = _service()._extract_body(node)
	assert isinstance(result, str)
