"""The package's own HTTPS requests trust what the OS trusts. On a fresh Windows host, Python's default context reads
only the roots already in the store, and Windows fetches a missing root (the Starfield root behind api.browser-use.com)
only for its own verifier: the README quickstart failed with CERTIFICATE_VERIFY_FAILED (win-local-1, win-install-1),
and `login --api-key-stdin` stored an unchecked key and said "Signed in" (win-cli-4). A local HTTPS server with a
self-signed certificate stands in for the cloud. No browser, no network."""

import contextlib
import datetime
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
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
		.add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)  # macOS wants it
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
	monkeypatch.setattr(utils, '_thread_tls', threading.local())
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
	tls.minimum_version = ssl.TLSVersion.TLSv1_2
	tls.load_cert_chain(cert, key)
	httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
	threading.Thread(target=httpd.serve_forever, daemon=True).start()
	yield f'https://127.0.0.1:{httpd.server_address[1]}', cert
	httpd.shutdown()
	httpd.server_close()


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


def test_a_stalled_handshake_in_one_thread_does_not_hold_up_another(server, monkeypatch):
	"""truststore holds a context's lock through each handshake: the telemetry thread's handshake to a PostHog that a
	firewall stalls must not hold the gateway check in another thread until it times out. SSL_CERT_FILE is trusted too."""
	from browser_use.utils import tls_context, urlopen_keyed

	url, cert = server
	monkeypatch.setenv('SSL_CERT_FILE', str(cert))
	silent = socket.socket()  # accepts the connection, never answers the handshake
	silent.bind(('127.0.0.1', 0))
	silent.listen(1)
	stalled_url = f'https://127.0.0.1:{silent.getsockname()[1]}/'

	def stalled():
		with contextlib.suppress(OSError):
			urllib.request.urlopen(stalled_url, timeout=3, context=tls_context())

	threading.Thread(target=stalled, daemon=True).start()
	time.sleep(0.3)  # its handshake is waiting
	started = time.monotonic()
	with urlopen_keyed(urllib.request.Request(f'{url}/api/v4/browsers'), 10) as r:
		assert r.status == 200
	assert time.monotonic() - started < 1.5
	silent.close()


def test_the_installed_opener_uses_a_proxy_set_after_it_was_installed(monkeypatch):
	"""cli.main installs the opener before browser-harness reads its .env: HTTPS_PROXY from there still applies."""
	from browser_use.utils import install_tls_opener

	proxy = socket.socket()
	proxy.bind(('127.0.0.1', 0))
	proxy.listen(1)
	proxy.settimeout(10)
	for var in ('https_proxy', 'HTTPS_PROXY', 'no_proxy', 'NO_PROXY'):
		monkeypatch.delenv(var, raising=False)
	monkeypatch.setattr(urllib.request, '_opener', None)
	install_tls_opener()
	monkeypatch.setenv('HTTPS_PROXY', f'http://127.0.0.1:{proxy.getsockname()[1]}')
	seen: list[bytes] = []

	def accept():  # until the CONNECT: another local process may probe the port first
		while not any(s.startswith(b'CONNECT') for s in seen):
			conn, _ = proxy.accept()
			seen.append(conn.recv(100))
			conn.close()

	thread = threading.Thread(target=accept, daemon=True)
	thread.start()
	with contextlib.suppress(OSError):
		urllib.request.urlopen('https://api.browser-use.com/', timeout=5)
	thread.join(5)
	proxy.close()
	assert any(s.startswith(b'CONNECT api.browser-use.com:443') for s in seen), seen


def test_version_does_not_pay_for_the_tls_setup():
	"""`browser-use --version` imported browser_use.utils to install the opener: its proxy lookup made the call ~14 ms
	slower on macOS (39 -> 55 ms)."""
	code = "import sys; sys.argv = ['browser-use', '--version']; from browser_use.cli import main; main()\n"
	code += "print('browser_use.utils' in sys.modules)"
	env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'false'}
	result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
	assert result.stdout.strip().splitlines()[-1] == 'False', result.stdout + result.stderr


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
