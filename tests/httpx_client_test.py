import httpx

from browser_use.browser import BrowserProfile, BrowserSession


async def test_browser_close_doesnt_affect_external_httpx_clients():
	"""
	Test that Browser.close() doesn't close HTTPX clients created outside the Browser instance.
	This test demonstrates the issue where Browser.close() is closing all HTTPX clients.
	"""
	# Create an external HTTPX client that should remain open
	external_client = httpx.AsyncClient()

	# Create a BrowserSession instance
	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True))
	await browser_session.start()

	# Close the browser (which should trigger cleanup_httpx_clients)
	await browser_session.stop()

	# Check if the external client is still usable
	try:
		# If the client is closed, this will raise RuntimeError
		# Using a simple HEAD request to a reliable URL
		await external_client.head('https://www.example.com', timeout=2.0)
		client_is_closed = False
	except RuntimeError as e:
		# If we get "Cannot send a request, as the client has been closed"
		client_is_closed = 'client has been closed' in str(e)
	except Exception:
		# Any other exception means the client is not closed but request failed
		client_is_closed = False
	finally:
		# Always clean up our test client properly
		await external_client.aclose()

	# Our external client should not be closed by browser.close()
	assert not client_is_closed, 'External HTTPX client was incorrectly closed by Browser.close()'
