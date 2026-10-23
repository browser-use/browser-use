"""The 60k prefix cut stays unless one compress call returns a shorter preview."""

import json

from browser_use.agent.message_manager.compress_oversized import (
	choose_compress_target,
	compress_context,
	fit_to_cap,
	prefix_cut,
)


class _Body:
	def __init__(self, payload: bytes):
		self._payload = payload

	def read(self) -> bytes:
		return self._payload

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return False


def _opener(text: str):
	def open_url(request, timeout):
		assert timeout == 5.0
		assert request.get_header('X-api-key') == 'test-key'
		assert request.full_url == 'https://api.supercompress.dev/v1/compress'
		body = json.loads(request.data.decode())
		assert body['query'] == 'where did the disk fill up'
		assert 'error: disk full' in body['context']
		return _Body(json.dumps({'compressed_text': text}).encode())

	return open_url


def test_prefix_cut_matches_the_existing_notice():
	text = 'x' * 80
	cut = prefix_cut(text, 60)
	assert cut == ('x' * 60) + '\n... [Content truncated at 60k characters]'


def test_choose_compress_target_is_the_longer_oversized_field():
	assert choose_compress_target({'read': 10, 'action': 20}, 60) is None
	assert choose_compress_target({'read': 90, 'action': 70}, 60) == 'read'
	assert choose_compress_target({'read': 70, 'action': 90}, 60) == 'action'


def test_fit_to_cap_without_a_key_is_the_prefix_cut():
	text = 'head ' + ('x' * 80) + ' error: disk full'
	cut = fit_to_cap(text, 60, query='where did the disk fill up', enabled=True, api_key='')
	assert cut.startswith('head ')
	assert cut.endswith('[Content truncated at 60k characters]')
	assert 'disk full' not in cut


def test_fit_to_cap_keeps_a_shorter_preview():
	text = ('noise\n' * 30) + 'error: disk full\n'
	result = fit_to_cap(
		text,
		60,
		query='where did the disk fill up',
		enabled=True,
		api_key='test-key',
		opener=_opener('error: disk full'),
	)
	assert result == 'error: disk full'


def test_fit_to_cap_ignores_a_preview_that_is_not_shorter():
	text = 'x' * 80
	calls = {'n': 0}

	def opener(request, timeout):
		calls['n'] += 1
		return _Body(json.dumps({'compressed_text': text}).encode())

	result = fit_to_cap(text, 60, query='task', enabled=True, api_key='test-key', opener=opener)
	assert calls['n'] == 1
	assert result == prefix_cut(text, 60)


def test_disabled_field_does_not_call_out():
	def opener(_request, _timeout):
		raise AssertionError('should not be called')

	text = 'y' * 80
	assert fit_to_cap(text, 60, query='task', enabled=False, api_key='test-key', opener=opener) == prefix_cut(text, 60)


def test_compress_context_skips_text_over_the_api_limit():
	assert compress_context('x' * 120_001, 'task', 'test-key', opener=_opener('nope')) is None
