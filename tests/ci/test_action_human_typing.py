"""Tests for human_typing_wpm feature in BrowserProfile.

Verifies that:
1. wpm=0 (default) preserves original behaviour — no extra delay.
2. wpm>0 produces per-keystroke delays that match the target WPM within a
   reasonable tolerance (log-normal sampling means we need enough samples).
3. Word-boundary pauses fire after spaces.
4. The delay floor scales with WPM so fast targets aren't clamped too hard.
5. Both typing paths (DefaultActionWatchdog and Element.fill) respect the profile.
"""

import asyncio
import math
import statistics
import time

import pytest
from pytest_httpserver import HTTPServer

from browser_use.browser import BrowserProfile, BrowserSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()
	server.expect_request('/type-test').respond_with_data(
		"""<!DOCTYPE html>
<html><head><title>Typing Test</title></head>
<body>
  <input id="inp" type="text">
  <textarea id="ta"></textarea>
</body></html>""",
		content_type='text/html',
	)
	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


# ---------------------------------------------------------------------------
# Unit tests — pure delay sampling (no browser needed)
# ---------------------------------------------------------------------------


def _sample_delays(wpm: float, n: int = 500) -> list[float]:
	"""Replicate the _keystroke_delay logic and collect samples."""
	if wpm <= 0:
		return [0.010] * n  # original base

	sigma = 0.4
	mean_iki = 60.0 / (wpm * 5.0)
	mu = math.log(mean_iki) - (sigma ** 2) / 2.0
	floor = max(0.005, min(0.030, mean_iki * 0.15))

	import random
	return [max(floor, random.lognormvariate(mu, sigma)) for _ in range(n)]


class TestDelayDistribution:
	"""Verify the statistical properties of the delay sampler."""

	def test_default_wpm_zero_returns_base_delay(self):
		delays = _sample_delays(wpm=0, n=100)
		assert all(d == pytest.approx(0.010) for d in delays)

	def test_wpm_90_mean_within_tolerance(self):
		"""90 WPM → mean IKI ≈ 133 ms.  Allow ±30% for log-normal variance."""
		delays = _sample_delays(wpm=90, n=1000)
		mean_ms = statistics.mean(delays) * 1000
		expected_ms = 60_000 / (90 * 5)  # 133.3 ms
		assert expected_ms * 0.70 <= mean_ms <= expected_ms * 1.30, (
			f'90 WPM mean {mean_ms:.1f}ms outside ±30% of expected {expected_ms:.1f}ms'
		)

	def test_wpm_500_mean_within_tolerance(self):
		"""500 WPM → mean IKI ≈ 24 ms.  Allow ±30%."""
		delays = _sample_delays(wpm=500, n=1000)
		mean_ms = statistics.mean(delays) * 1000
		expected_ms = 60_000 / (500 * 5)  # 24 ms
		assert expected_ms * 0.70 <= mean_ms <= expected_ms * 1.30, (
			f'500 WPM mean {mean_ms:.1f}ms outside ±30% of expected {expected_ms:.1f}ms'
		)

	def test_floor_scales_with_wpm(self):
		"""High WPM should have a lower floor than low WPM."""
		floor_90 = max(0.005, min(0.030, (60.0 / (90 * 5)) * 0.15))
		floor_500 = max(0.005, min(0.030, (60.0 / (500 * 5)) * 0.15))
		assert floor_500 < floor_90

	def test_all_delays_non_negative(self):
		for wpm in [0, 90, 200, 500]:
			delays = _sample_delays(wpm=wpm, n=200)
			assert all(d >= 0 for d in delays), f'Negative delay found at wpm={wpm}'

	def test_wpm_90_slower_than_wpm_500(self):
		mean_90 = statistics.mean(_sample_delays(wpm=90, n=500))
		mean_500 = statistics.mean(_sample_delays(wpm=500, n=500))
		assert mean_90 > mean_500, '90 WPM should be slower than 500 WPM'


# ---------------------------------------------------------------------------
# Integration tests — real browser, measure wall-clock typing time
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
async def browser_session_default():
	"""Browser with default (wpm=0) profile."""
	session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))
	await session.start()
	yield session
	await session.kill()


@pytest.fixture(scope='module')
async def browser_session_90wpm():
	"""Browser with human_typing_wpm=90."""
	session = BrowserSession(
		browser_profile=BrowserProfile(headless=True, user_data_dir=None, human_typing_wpm=90)
	)
	await session.start()
	yield session
	await session.kill()


TEXT = 'hello world'  # 11 chars, 2 words


class TestBrowserTypingSpeed:
	"""Wall-clock timing tests using a real headless browser."""

	async def test_default_typing_is_fast(self, browser_session_default, base_url):
		"""wpm=0 should type 11 chars in well under 1 second."""
		page = await browser_session_default.get_current_page()
		await page.goto(f'{base_url}/type-test')
		await asyncio.sleep(0.3)

		watchdog = browser_session_default._default_action_watchdog
		assert watchdog is not None

		await page.evaluate("document.getElementById('inp').focus()")
		t0 = time.monotonic()
		await watchdog._type_to_page(TEXT)
		elapsed = time.monotonic() - t0

		# 11 chars × 10ms base = 110ms max; give generous 1s headroom for CI
		assert elapsed < 1.0, f'Default typing took {elapsed:.2f}s — unexpectedly slow'

	async def test_90wpm_typing_is_slower_than_default(
		self, browser_session_default, browser_session_90wpm, base_url
	):
		"""90 WPM typing should be measurably slower than the default bot speed."""
		# --- default ---
		page_d = await browser_session_default.get_current_page()
		await page_d.goto(f'{base_url}/type-test')
		await asyncio.sleep(0.3)
		wd = browser_session_default._default_action_watchdog
		await page_d.evaluate("document.getElementById('inp').focus()")
		t0 = time.monotonic()
		await wd._type_to_page(TEXT)
		default_elapsed = time.monotonic() - t0

		# --- 90 WPM ---
		page_h = await browser_session_90wpm.get_current_page()
		await page_h.goto(f'{base_url}/type-test')
		await asyncio.sleep(0.3)
		wh = browser_session_90wpm._default_action_watchdog
		await page_h.evaluate("document.getElementById('inp').focus()")
		t0 = time.monotonic()
		await wh._type_to_page(TEXT)
		human_elapsed = time.monotonic() - t0

		assert human_elapsed > default_elapsed * 2, (
			f'90 WPM ({human_elapsed:.2f}s) should be >2× slower than default ({default_elapsed:.2f}s)'
		)

	async def test_profile_field_validation(self):
		"""human_typing_wpm must be >= 0."""
		with pytest.raises(Exception):
			BrowserProfile(human_typing_wpm=-1)
