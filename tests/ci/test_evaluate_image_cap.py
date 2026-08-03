"""Tests for bounded image extraction in the evaluate action.

Root cause of #5367: evaluate() extracts data:image/...;base64 URIs from the JavaScript
result into metadata['images'] BEFORE the 20,000-char text truncation, so a single evaluate
call can forward an arbitrarily large image payload to the next LLM request.

The fix caps the number of images (10, matching the max_images screenshot budget) and the size
of each (100_000 base64 chars, roughly 75 KB decoded). Anything beyond the cap is dropped,
replaced with an [Image omitted] placeholder in the text, and counted in an omission note
appended AFTER the truncation so the model knows images were omitted.
"""

import asyncio

from browser_use.tools.service import Tools


def _make_fake_session(js_result: str):
	"""Build a fake CDP session whose Runtime.evaluate returns js_result."""

	class Send:
		class Runtime:
			@staticmethod
			async def evaluate(params=None, session_id=None):
				return {'result': {'value': js_result}}

	class Client:
		send = Send()

	class CdpSession:
		cdp_client = Client()
		session_id = 's'

	class FakeSession:
		async def get_or_create_cdp_session(self):
			return CdpSession()

	return FakeSession()


def _run_evaluate(js_result: str):
	"""Drive the evaluate action against a fake session and return the ActionResult."""
	evaluate = Tools().registry.registry.actions['evaluate'].function
	return asyncio.run(evaluate(code='return document.body.innerHTML', browser_session=_make_fake_session(js_result)))


class TestEvaluateImageCap:
	def test_oversized_single_image_is_dropped_and_noted(self):
		"""One ~300 KB base64 image exceeds the per-image cap -> dropped, noted, payload bounded."""
		big = 'A' * 300_000
		js_result = f'<img src="data:image/png;base64,{big}">'

		result = _run_evaluate(js_result)

		images = (result.metadata or {}).get('images', [])
		assert images == [], f'expected the oversized image to be dropped, got {len(images)} image(s)'
		assert 'image(s) omitted' in result.extracted_content
		# Raw base64 must not leak into the text result either
		assert 'data:image' not in result.extracted_content

	def test_image_count_capped(self):
		"""12 small images -> only 10 kept, the remaining 2 dropped and noted."""
		images = ''.join(f'<img src="data:image/png;base64,{"B" * 10_000}">' for _ in range(12))
		js_result = f'<div>{images}</div>'

		result = _run_evaluate(js_result)

		kept = (result.metadata or {}).get('images', [])
		assert len(kept) == 10
		assert '2 image(s) omitted' in result.extracted_content
		assert 'data:image' not in result.extracted_content

	def test_small_image_passthrough_unchanged(self):
		"""A small inline image is still extracted and placeholder'd as before (regression guard)."""
		js_result = '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=">'

		result = _run_evaluate(js_result)

		images = (result.metadata or {}).get('images', [])
		assert len(images) == 1
		assert images[0] == 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='
		assert '[Image]' in result.extracted_content
		assert 'omitted' not in result.extracted_content
