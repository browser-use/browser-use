"""Tests for Content-Disposition filename parsing in downloads watchdog.

Verifies RFC 5987/6266 filename*= parsing for non-ASCII filenames (Japanese, etc.)
and backward compatibility with standard filename= parameter.
"""

import re
from urllib.parse import unquote


def parse_filename_from_content_disposition(content_disposition_raw: str) -> str | None:
	"""Extract filename from Content-Disposition header, matching downloads_watchdog.py logic.

	This replicates the parsing logic from DownloadsWatchdog._setup_network_monitoring
	so we can unit test it without spinning up a full browser session.
	"""
	content_disposition = content_disposition_raw.lower()
	suggested_filename = None

	if 'filename' in content_disposition:
		# Try filename*= first (RFC 5987, handles non-ASCII)
		filename_star_match = re.search(
			r"filename\*\s*=\s*UTF-8''([^;\s]+)",
			content_disposition_raw,
			re.IGNORECASE,
		)
		if filename_star_match:
			suggested_filename = unquote(filename_star_match.group(1))
		else:
			# Fall back to standard filename= parameter
			filename_match = re.search(
				r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;\s]+)',
				content_disposition_raw,
				re.IGNORECASE,
			)
			if filename_match:
				suggested_filename = (filename_match.group(1) or filename_match.group(2)).strip('\'"')

	return suggested_filename


async def test_filename_star_utf8_japanese():
	"""filename*=UTF-8'' with Japanese characters should decode correctly."""
	header = "attachment; filename*=UTF-8''%E3%83%86%E3%82%B9%E3%83%88.pdf"
	assert parse_filename_from_content_disposition(header) == '\u30c6\u30b9\u30c8.pdf'


async def test_filename_star_utf8_chinese():
	"""filename*=UTF-8'' with Chinese characters should decode correctly."""
	header = "attachment; filename*=UTF-8''%E6%96%87%E4%BB%B6.pdf"
	assert parse_filename_from_content_disposition(header) == '\u6587\u4ef6.pdf'


async def test_filename_star_utf8_korean():
	"""filename*=UTF-8'' with Korean characters should decode correctly."""
	header = "attachment; filename*=UTF-8''%ED%8C%8C%EC%9D%BC.pdf"
	assert parse_filename_from_content_disposition(header) == '\ud30c\uc77c.pdf'


async def test_filename_star_takes_priority():
	"""When both filename and filename* are present, filename* wins per RFC 6266."""
	header = 'attachment; filename="fallback.pdf"; filename*=UTF-8\'\'%E3%83%86%E3%82%B9%E3%83%88.pdf'
	assert parse_filename_from_content_disposition(header) == '\u30c6\u30b9\u30c8.pdf'


async def test_filename_star_case_insensitive():
	"""The UTF-8 charset label should be matched case-insensitively."""
	header = "attachment; filename*=utf-8''%E3%83%86%E3%82%B9%E3%83%88.pdf"
	assert parse_filename_from_content_disposition(header) == '\u30c6\u30b9\u30c8.pdf'


async def test_plain_filename_quoted():
	"""Standard quoted filename= should still work."""
	header = 'attachment; filename="report.pdf"'
	assert parse_filename_from_content_disposition(header) == 'report.pdf'


async def test_plain_filename_unquoted():
	"""Standard unquoted filename= should still work."""
	header = 'attachment; filename=report.pdf'
	assert parse_filename_from_content_disposition(header) == 'report.pdf'


async def test_filename_with_spaces():
	"""Filename with spaces in quotes should be preserved."""
	header = 'attachment; filename="my report.pdf"'
	assert parse_filename_from_content_disposition(header) == 'my report.pdf'


async def test_filename_star_with_trailing_params():
	"""filename*= should not capture trailing parameters after semicolon."""
	header = "attachment; filename*=UTF-8''%E3%83%86%E3%82%B9%E3%83%88.pdf; size=12345"
	assert parse_filename_from_content_disposition(header) == '\u30c6\u30b9\u30c8.pdf'


async def test_no_filename():
	"""Header without any filename should return None."""
	header = 'attachment'
	assert parse_filename_from_content_disposition(header) is None


async def test_empty_header():
	"""Empty header should return None."""
	assert parse_filename_from_content_disposition('') is None


async def test_filename_star_with_encoded_spaces():
	"""Percent-encoded spaces in filename*= should decode properly."""
	header = "attachment; filename*=UTF-8''my%20report%20%E3%83%86%E3%82%B9%E3%83%88.pdf"
	assert parse_filename_from_content_disposition(header) == 'my report \u30c6\u30b9\u30c8.pdf'
