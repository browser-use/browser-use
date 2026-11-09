"""The package's own HTTPS requests trust what the OS trusts. On a fresh Windows host, Python's default context reads
only the roots already in the store, and Windows fetches a missing root (the Starfield root behind api.browser-use.com)
only for its own verifier: the README quickstart failed with CERTIFICATE_VERIFY_FAILED (win-local-1, win-install-1),
and `login --api-key-stdin` stored an unchecked key and said "Signed in" (win-cli-4). A local HTTPS server with a
self-signed certificate stands in for the cloud. No browser, no network."""

import datetime
import ipaddress
import json
import os
import ssl
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KEY = 'bu_' + 't' * 40


def _self_signed(directory: Path) -> tuple[Path, Path]:
	from cryptography import x509
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import ec
	from cryptography.x509.oid import NameOID

	key = ec.generate_private_key(ec.SECP256R1())
	name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'browser-use tls test')])
	now = datetime.datetime.now(datetime.UTC)
	cert = (
		x509.CertificateBuilder()
		.subject_name(name)
		.issuer_name(name)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(now - datetime.timedelta(days=1))
		.not_valid_after(now + datetime.timedelta(days=2))
		.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
		.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
		.sign(key, hashes.SHA256())
	)
	cert_path, key_path = directory / 'cert.pem', directory / 'key.pem'
	cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
	key_path.write_bytes(
		key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
	)
	return cert_path, key_path


@pytest.fixture
def server(tmp_path, monkeypatch):
	"""(https base URL, its certificate) of a server that answers every request 200 with JSON; no TLS settings from the
	environment and a fresh tls_context()."""
	from browser_use import utils

	for var in ('SSL_CERT_FILE', 'SSL_CERT_DIR'):
		monkeypatch.delenv(var, raising=False)
	utils.tls_context.cache_clear()
	cert, key = _self_signed(tmp_path)

	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			raw = json.dumps({'data': [], 'items': [], 'id': 'b1', 'webSocketDebuggerUrl': 'ws://127.0.0.1:1/x'}).encode()
			self.send_response(200)
			self.send_header('Content-Type', 'application/json')
			self.send_header('Content-Length', str(len(raw)))
			self.end_headers()
			self.wfile.write(raw)

		do_POST = do_GET

		def log_message(self, *args):
			pass

	httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	httpd.daemon_threads = True
	tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
	tls.load_cert_chain(cert, key)
	httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
	threading.Thread(target=httpd.serve_forever, daemon=True).start()
	yield f'https://127.0.0.1:{httpd.server_address[1]}', cert
	httpd.shutdown()
	httpd.server_close()
	utils.tls_context.cache_clear()


@pytest.mark.skipif(sys.platform == 'linux', reason='on Linux the OS trust store is the one OpenSSL reads')
def test_requests_trust_a_root_only_the_os_verifier_trusts(server, monkeypatch):
	"""A root the OS verifier trusts but Python's default context never loaded (a fresh Windows store): the gateway
	preflight, a cdp_url lookup and browser-harness's cloud calls in the CLI process all reach the server."""
	import importlib

	from browser_harness import admin

	from browser_use import ChatBrowserUse
	from browser_use.browser import browser as browser_mod
	from browser_use.utils import install_tls_opener

	url, _ = server
	verified: list[str | None] = []
	os_verifier = importlib.import_module('truststore._api')  # the package deletes the name _api
	monkeypatch.setattr(os_verifier, '_verify_peercerts', lambda sock, server_hostname: verified.append(server_hostname))

	assert ChatBrowserUse('bu-fast', api_key=KEY, base_url=f'{url}/api/v4/llm/v1').preflight() is None
	assert browser_mod._ws_url(url) == 'ws://127.0.0.1:1/x'

	monkeypatch.setattr(urllib.request, '_opener', None)  # restored after the test
	install_tls_opener()  # what `browser-use` and the MCP server do first
	monkeypatch.setattr(admin, 'BU_API', f'{url}/api/v4')
	monkeypatch.setenv('BROWSER_USE_API_KEY', KEY)
	assert admin._browser_use('/browsers', 'POST', {})['id'] == 'b1'  # start_remote_daemon's create call
	assert set(verified) == {'127.0.0.1'}  # the OS verifier, not OpenSSL's store, accepted each one


def test_without_truststore_the_certifi_roots_are_trusted(server, monkeypatch):
	import certifi

	from browser_use.utils import urlopen_keyed

	url, cert = server
	monkeypatch.setitem(sys.modules, 'truststore', None)  # import truststore raises ImportError
	monkeypatch.setattr(certifi, 'where', lambda: str(cert))
	with urlopen_keyed(urllib.request.Request(f'{url}/api/v4/browsers'), 10) as r:
		assert r.status == 200


def _login(base_url: str, store: Path) -> subprocess.CompletedProcess[str]:
	env = {k: v for k, v in os.environ.items() if k not in ('BROWSER_USE_API_KEY', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
	env |= {'BROWSER_USE_CLOUD_API_URL': base_url, 'BH_AUTH_PATH': str(store)}
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	return subprocess.run(
		[sys.executable, '-m', 'browser_use', 'login', '--api-key-stdin'],
		cwd=ROOT,
		env=env,
		input=KEY,
		capture_output=True,
		text=True,
		timeout=60,
	)


def test_login_stores_no_key_when_the_tls_check_fails_but_does_offline(server, tmp_path):
	url, _ = server  # its certificate is trusted by nothing
	store = tmp_path / 'auth.json'
	result = _login(url, store)
	assert result.returncode == 1, result.stdout + result.stderr
	assert 'key was not stored' in result.stderr and 'Signed in' not in result.stdout
	assert not store.exists()

	result = _login('http://127.0.0.1:9', store)  # nothing listens: offline, so it is stored unchecked
	assert result.returncode == 0 and 'Signed in' in result.stdout, result.stdout + result.stderr
	assert json.loads(store.read_text())['browser_use']['api_key'] == KEY
