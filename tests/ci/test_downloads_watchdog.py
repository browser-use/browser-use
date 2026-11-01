import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.watchdogs.downloads_watchdog import DownloadsWatchdog, _should_auto_download_network_response


def test_downloads_watchdog_skips_generic_text_attachment_without_file_url():
	assert not _should_auto_download_network_response(
		url='https://www.google.com/complete/search?q=test&client=gws-wiz&xssi=t',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_pdf_network_response():
	assert _should_auto_download_network_response(
		url='https://example.com/view?id=123',
		content_type='application/pdf',
		is_pdf=True,
		is_download_attachment=False,
		suggested_filename=None,
	)


def test_downloads_watchdog_keeps_named_file_attachment():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='text/csv',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='report.csv',
	)


def test_downloads_watchdog_keeps_text_attachment_with_file_url():
	assert _should_auto_download_network_response(
		url='https://example.com/files/summary.txt?download=1',
		content_type='text/plain',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='f.txt',
	)


def test_downloads_watchdog_keeps_attachment_without_known_extension():
	assert _should_auto_download_network_response(
		url='https://example.com/download?id=123',
		content_type='application/vnd.example.custom',
		is_pdf=False,
		is_download_attachment=True,
		suggested_filename='statement',
	)


@pytest.mark.parametrize('accept_downloads', [True, False])
async def test_downloads_watchdog_honors_accept_downloads(tmp_path, accept_downloads):
	"""An explicit downloads directory must not override the acceptance setting."""
	cdp_client = SimpleNamespace(send=AsyncMock(), register=Mock())
	profile = BrowserProfile(downloads_path=tmp_path, accept_downloads=accept_downloads, auto_download_pdfs=False)
	session = SimpleNamespace(browser_profile=profile, cdp_client=cdp_client, logger=logging.getLogger(__name__))
	watchdog = DownloadsWatchdog.model_construct(browser_session=session)

	await watchdog.attach_to_target('target-1')

	cdp_client.send.Browser.setDownloadBehavior.assert_awaited_once()
	params = cdp_client.send.Browser.setDownloadBehavior.call_args.kwargs['params']
	assert params['behavior'] == ('allow' if accept_downloads else 'deny')
	assert params['eventsEnabled'] is True
	if accept_downloads:
		assert params['downloadPath'] == str(tmp_path.resolve())
	else:
		assert 'downloadPath' not in params


@pytest.mark.parametrize('accept_downloads', [True, False])
@pytest.mark.parametrize('auto_download_pdfs', [True, False])
def test_downloads_watchdog_auto_download_respects_acceptance(accept_downloads, auto_download_pdfs):
	"""PDF/network auto-downloads cannot bypass disabled download acceptance."""
	profile = BrowserProfile(accept_downloads=accept_downloads, auto_download_pdfs=auto_download_pdfs)
	watchdog = DownloadsWatchdog.model_construct(browser_session=SimpleNamespace(browser_profile=profile))
	assert watchdog._is_auto_download_enabled() is (accept_downloads and auto_download_pdfs)
