"""The telemetry notice link must be clickable as printed."""

import os
import re
import subprocess
import sys


def test_telemetry_notice_link_has_no_trailing_period():
	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'true', 'BROWSER_USE_LOGGING_LEVEL': 'info'}
	out = subprocess.run(
		[sys.executable, '-c', 'from browser_use.telemetry.service import ProductTelemetry; ProductTelemetry()'],
		env=env,
		capture_output=True,
		text=True,
		timeout=60,
	)
	text = out.stdout + out.stderr
	# Terminals link the whole non-space run, so a trailing period becomes part of the URL (404).
	urls = re.findall(r'https?://\S+', text)
	assert urls, text
	assert all(not u.endswith('.') for u in urls), urls
