"""
Web Bot Auth — End-to-end test of the full developer experience.

  Part A: Without auth → no signature headers on the wire
  Part B: With WebBotAuthConfig.generate() → signatures verified locally
  Part C: With RFC 9421 test key → Cloudflare validates signature server-side

Run:  uv run python tests/scripts/test_web_bot_auth_e2e.py
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from browser_use import BrowserSession, WebBotAuthConfig

# ── Local header capture server ───────────────────────────────────────


class CaptureHandler(BaseHTTPRequestHandler):
	captured: dict[str, str] = {}

	def do_GET(self):
		CaptureHandler.captured = dict(self.headers)
		self.send_response(200)
		self.end_headers()
		self.wfile.write(b'<h1>ok</h1>')

	def log_message(self, *a):
		pass


def start_server() -> tuple[HTTPServer, str]:
	srv = HTTPServer(('127.0.0.1', 0), CaptureHandler)
	threading.Thread(target=srv.serve_forever, daemon=True).start()
	port = srv.server_address[1]
	return srv, f'http://127.0.0.1:{port}/test'


# RFC 9421 test key — matches Cloudflare's verification endpoint.
# From https://github.com/cloudflare/web-bot-auth (examples/rfc9421-keys/ed25519.pem)
RFC9421_TEST_KEY_PEM = """\
-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIJ+DYvh6SEqVTm50DFtMDoQikTmiCqirVv9mWG9qfSnF
-----END PRIVATE KEY-----"""


async def main():
	server, url = start_server()

	# ── Part A: Without auth ──────────────────────────────────────────
	print('\n── Part A: Without Web Bot Auth ──')
	session = BrowserSession(headless=True)
	try:
		await session.start()
		CaptureHandler.captured = {}
		await session.navigate_to(url)
		await asyncio.sleep(1)
		assert not (CaptureHandler.captured.get('Signature') or CaptureHandler.captured.get('signature'))
		print('  No Signature headers (correct)')
	finally:
		await session.stop()

	# ── Part B: With generated identity ───────────────────────────────
	print('\n── Part B: With WebBotAuthConfig.generate() ──')
	config = WebBotAuthConfig.generate()
	print(f'  keyid:      {config.keyid}')
	print(f'  public_jwk: {config.public_jwk}')

	session = BrowserSession(headless=True, web_bot_auth=config)
	try:
		await session.start()
		CaptureHandler.captured = {}
		await session.navigate_to(url)
		await asyncio.sleep(1)

		sig = CaptureHandler.captured.get('Signature') or CaptureHandler.captured.get('signature')
		sig_input = CaptureHandler.captured.get('Signature-Input') or CaptureHandler.captured.get('signature-input')
		assert sig, f'No Signature header! Headers: {list(CaptureHandler.captured.keys())}'
		assert sig_input, 'No Signature-Input header!'
		assert 'web-bot-auth' in sig_input
		assert config.keyid in sig_input
		print('  Signature headers present and contain correct keyid')
	finally:
		await session.stop()

	# ── Part C: Cloudflare verification with RFC 9421 test key ────────
	print('\n── Part C: Cloudflare server-side verification ──')
	cf_config = WebBotAuthConfig(private_key_pem=RFC9421_TEST_KEY_PEM)
	assert cf_config.keyid == 'poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U'
	print(f'  keyid matches Cloudflare directory: {cf_config.keyid}')

	session = BrowserSession(headless=True, web_bot_auth=cf_config)
	try:
		await session.start()
		await session.navigate_to('https://http-message-signatures-example.research.cloudflare.com/')
		await asyncio.sleep(3)

		page = await session.get_current_page()
		text = await page.evaluate('() => document.body.innerText')
		print(f'  Cloudflare says: {(text or "").split(chr(10))[1].strip()}')
		assert 'successfully authenticated' in (text or '').lower(), f'Cloudflare did not validate! Response: {text[:200]}'
	finally:
		await session.stop()
		server.shutdown()

	print('\n  ALL CHECKS PASSED\n')


if __name__ == '__main__':
	asyncio.run(main())
