"""Persistent Python REPL for one agent. Runs as a child process so a hung cell can be killed.

Namespace = browser-harness helpers + screenshot/show_image/checkpoint/type_secret (+ bu in ultrafast mode, see ax.py).
Protocol: connect to 127.0.0.1:BU_REPL_PORT, send BU_REPL_TOKEN, read one init line ({"secrets": [[name, value, domain|null], ...]}), then one JSON
line per message. Cell stdout/stderr (including subprocesses) go to a per-cell file, so a killed cell still leaves its
partial output on disk.
"""

import ast
import asyncio
import base64
import codecs
import contextlib
import hashlib
import hmac
import inspect
import io
import json
import os
import pprint
import socket
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

from browser_use import ax
from browser_use.repl.session import MAX_OUTPUT_CHARS, clip, domain_matches, redact, redact_forms, secret_forms

MAX_IMAGES_PER_CELL = 4
MAX_IMAGE_SIDE = 2048  # full-page captures exceeded OpenAI's 30k-patch limit (bub2-002)
CDP_TIMEOUT_S = 20.0  # bu-pi cdp timeout; 30s/60s waits made each stall cost more (v1b: 114 Hard timeouts)
SCREENSHOT_TIMEOUT_S = 60.0  # browser-harness's own screenshot timeout: cloud screenshots routinely take longer


def totp(seed: str, now: float | None = None) -> str:
	"""The current 6-digit TOTP code (RFC 6238: SHA-1, 30 s) for a base32 seed, as 0.x generated for secrets whose name
	ends in 'bu_2fa_code' (pyotp.TOTP(seed, digits=6).now())."""
	key = seed.replace(' ', '').upper()
	key = base64.b32decode(key + '=' * (-len(key) % 8))
	digest = hmac.new(key, struct.pack('>Q', int((time.time() if now is None else now) // 30)), hashlib.sha1).digest()
	offset = digest[-1] & 15
	return f'{(int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF) % 1_000_000:06d}'


STATE = Path(os.environ.get('BU_STATE_DIR', '.browser-use'))
images: list[dict] = []


def _add_image(data: bytes, media_type: str = 'image/png') -> bool:
	if len(images) >= MAX_IMAGES_PER_CELL:
		print(f'[image dropped: {MAX_IMAGES_PER_CELL} per call max]')
		return False
	from PIL import Image

	try:  # providers 400 the whole request on an undecodable or oversized image
		img = Image.open(io.BytesIO(data))
		img.load()
	except Exception as e:
		print(f'[image dropped: not a decodable image ({type(e).__name__})]')
		return False
	if len(data) > 5_000_000 or max(img.size) > MAX_IMAGE_SIDE:
		img = img.convert('RGB')
		img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
		out = io.BytesIO()
		img.save(out, 'JPEG', quality=80)
		data, media_type = out.getvalue(), 'image/jpeg'
	images.append({'data': base64.b64encode(data).decode(), 'media_type': media_type})
	return True


def _install(ns: dict, secrets: list) -> ax.AxHelpers | None:
	env = dict(os.environ)  # the allowlisted env the parent gave us
	from browser_harness import helpers  # loads .env files and agent_helpers.py into this process

	os.environ.clear()  # whatever those added (DATABASE_URL, ...) does not survive
	os.environ.update(env)

	raw_cdp = helpers.cdp

	def cdp(method, session_id=None, **params):
		# browser-harness defaults to 5s IPC; heavy cloud pages (Maps, TripAdvisor) blew it on navigate/evaluate/input.
		params.setdefault('_response_timeout', SCREENSHOT_TIMEOUT_S if method == 'Page.captureScreenshot' else CDP_TIMEOUT_S)
		result = raw_cdp(method, session_id, **params)
		# Every screenshot the agent takes is shown to the model as a native image.
		if method == 'Page.captureScreenshot' and isinstance(result, dict) and result.get('data'):
			fmt = params.get('format', 'png')
			_add_image(base64.b64decode(result['data']), f'image/{"jpeg" if fmt == "jpeg" else fmt}')
		return result

	cdp.__doc__ = raw_cdp.__doc__
	helpers.cdp = cdp  # capture_screenshot() and friends go through the wrapper too
	exec('from browser_harness.helpers import *', ns)
	ns['cdp'] = cdp

	shots = STATE / 'screenshots'

	def screenshot(full=False):
		"""Capture the current tab (JPEG q70, like bu-pi) and show it to the model. Returns the file path."""
		shots.mkdir(parents=True, exist_ok=True)
		try:  # a hidden tab (new_tab/switch_tab never activate) produces no frames on Linux headless: capture hangs
			if helpers.js('document.visibilityState') == 'hidden':
				helpers.activate_tab(helpers.current_tab())
		except Exception:  # best effort; the capture below still reports a real failure
			pass
		r = cdp('Page.captureScreenshot', format='jpeg', quality=70, captureBeyondViewport=full)
		path = shots / f'{len(list(shots.iterdir())):04d}.jpg'
		path.write_bytes(base64.b64decode(r['data']))
		return str(path)

	def show_image(path):
		"""Show an image file (png/jpeg/webp/gif) to the model."""
		p = Path(path)
		ext = p.suffix.lower().lstrip('.').replace('jpg', 'jpeg')
		return _add_image(p.read_bytes(), f'image/{ext}')

	def checkpoint(filename, value, partial=False):
		"""Atomically save JSON to the workspace. partial=True also makes it the run's fallback result."""
		path = Path(filename)
		value = redact(
			json.loads(json.dumps(value, default=_jsonable)), secrets
		)  # the checkpoint file never holds a secret value
		_write_atomic(path, json.dumps(value, ensure_ascii=False, indent=1))
		if partial:
			_write_atomic(STATE / 'partial.json', json.dumps({'file': str(path), 'value': value}, ensure_ascii=False))
		return str(path)

	def _frame_url(session: str | None, frame_id: str) -> str | None:
		"""The browser's own record of a frame's URL, from its target's frame tree. None when the frame is not in it."""

		def find(tree: dict) -> str | None:
			if tree['frame']['id'] == frame_id:
				return str(tree['frame'].get('url') or '')
			return next((u for c in tree.get('childFrames') or [] if (u := find(c)) is not None), None)

		return find(helpers.cdp('Page.getFrameTree', session_id=session)['frameTree'])

	def _focused(session: str | None, frame_id: str) -> dict | None:
		"""DOM.describeNode of the focused element in a frame's document, through open and closed shadow roots, read
		in an isolated world: page JS cannot change what document.activeElement reports there. None when none."""
		cdp_ = helpers.cdp
		world = cdp_('Page.createIsolatedWorld', session_id=session, frameId=frame_id, worldName='browser-use-secrets')
		ctx = world['executionContextId']
		obj = cdp_('Runtime.evaluate', session_id=session, expression='document.activeElement', contextId=ctx)['result']
		obj = obj.get('objectId')
		for _ in range(32):
			if not obj:
				return None
			node = cdp_('DOM.describeNode', session_id=session, objectId=obj)['node']
			if not node.get('shadowRoots'):
				return node
			root = cdp_(
				'DOM.resolveNode',
				session_id=session,
				backendNodeId=node['shadowRoots'][0]['backendNodeId'],
				executionContextId=ctx,
			)['object']['objectId']
			inner = cdp_(
				'Runtime.callFunctionOn',
				session_id=session,
				objectId=root,
				functionDeclaration='function () { return this.activeElement }',
			)
			if not inner['result'].get('objectId'):
				return node
			obj = inner['result']['objectId']
		raise RuntimeError('shadow roots nested too deep')

	def _recipient_url() -> str:
		"""URL of the frame typed text reaches: focus followed from the top frame into nested frames, cross-site iframe
		targets included (the attached tab's own target would type into a focused attacker iframe). Raises when it
		cannot be established."""
		session: str | None = None
		frame_id = helpers.cdp('Page.getFrameTree')['frameTree']['frame']['id']
		attached: list[str] = []
		try:
			for _ in range(16):
				node = _focused(session, frame_id)
				if node is None or node.get('nodeName') not in ('IFRAME', 'FRAME'):
					url = _frame_url(session, frame_id)
					if url is None:
						raise RuntimeError('focused frame not found')
					return url
				child = node.get('frameId')
				if not child:
					raise RuntimeError('focused frame has no id')
				if _frame_url(session, child) is None:  # another process: a cross-site iframe target, frame id = target id
					# listing the targets first also makes Chrome accept the attach ("No target with given id" without)
					targets = helpers.cdp('Target.getTargets')['targetInfos']
					if not any(t['targetId'] == child and t['type'] == 'iframe' for t in targets):
						raise RuntimeError('focused frame is neither in the frame tree nor an iframe target')
					sid = helpers.cdp('Target.attachToTarget', targetId=child, flatten=True)['sessionId']
					attached.append(sid)
					session = sid
				frame_id = child
			raise RuntimeError('frames nested too deep')
		finally:
			for attached_sid in attached:
				with contextlib.suppress(Exception):
					helpers.cdp('Target.detachFromTarget', sessionId=attached_sid)

	def _type_keys(value: str) -> None:
		# Key events per character, as 0.x typed sensitive_data: forms that react to keydown/keyup (enable the submit
		# button, validate) see the value. Input.insertText alone fires no key events. A newline is the Enter key (as in
		# 0.x); a tab or other control character goes in as text: as a key event a tab moves focus, and the rest of the
		# secret would land in the next field.
		for ch in value.replace('\r\n', '\n'):
			if ch in '\r\n':
				helpers.press_key('Enter')
			elif ch.isprintable():
				helpers.press_key(ch)
			else:
				helpers.cdp('Input.insertText', text=ch)

	def type_secret(name):
		"""Type the secret called `name` into the focused element. Its value is hidden from your text output.
		A domain-scoped secret types only while the frame that receives the text matches its domain. A secret whose
		name ends in 'bu_2fa_code' is a TOTP seed: the current 6-digit code is typed, never the seed (0.x)."""
		candidates = [(totp(v) if name.endswith('bu_2fa_code') else v, scope) for n, v, scope in secrets if n == name]
		if not candidates:
			raise KeyError(f'No secret named {name!r}; secret_names() lists them')
		scoped = [(v, scope) for v, scope in candidates if scope is not None]
		url = ''
		if scoped:
			try:  # the browser's own records (frame trees, isolated worlds), never page JS
				url = _recipient_url()
			except Exception:  # fail closed: unknown recipient
				url = ''
			for value, scope in scoped:
				if url and domain_matches(url, scope):
					return _type_keys(value)
		for value, scope in candidates:
			if scope is None:
				return _type_keys(value)
		raise PermissionError(
			f'Secret {name!r} may only be typed on {", ".join(sorted({s for _, s in scoped}))}; the focused frame is '
			f'{url or "unknown"}. Focus a field on the right site first.'
		)

	def secret_names():
		"""Names of the secrets you can type with type_secret(name)."""
		return sorted({n for n, _, _ in secrets})

	ns.update(
		screenshot=screenshot, show_image=show_image, checkpoint=checkpoint, type_secret=type_secret, secret_names=secret_names
	)
	if os.environ.get('BU_REMOTE_BROWSER') == '1':
		ns['upload_file'] = _remote_upload(ns['js'])
	if os.environ.get('BU_MODE') != 'ultrafast':
		return None
	bu = ns['bu'] = ax.AxHelpers(cdp)
	helpers.drain_events = ns['drain_events'] = bu.drain_events  # bu reads the daemon's events; the agent still gets them

	def print_(*args, **kwargs):
		"""print() for the cell: a bu result is already printed, so it prints empty (Pi: console.log of it)."""
		print(*('' if isinstance(a, ax.Printed) else a for a in args), **kwargs)

	ns['print'] = print_
	return bu


def _write_atomic(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + '.tmp')
	tmp.write_text(text, encoding='utf-8')
	os.replace(tmp, path)  # a kill mid-write leaves the old file, never a truncated one


def _pump(rfd: int, path: Path, secrets: list) -> None:
	"""Copy a cell's output pipe into its file, redacting on the way, so secret values never reach the disk even
	when the cell is killed. Holds back only the tail that could be the start of a secret."""
	forms = secret_forms(secrets)
	keep = max((len(f) for f, _ in forms), default=1) - 1
	by_line = not any('\n' in f for f, _ in forms)  # then a secret never spans a newline
	decoder, buf = codecs.getincrementaldecoder('utf-8')('replace'), ''
	with open(path, 'w', encoding='utf-8', newline='') as out:  # Windows: the cell already wrote \r\n; no \r\r\n
		while True:
			chunk = os.read(rfd, 65536)
			buf = redact_forms(buf + decoder.decode(chunk, final=not chunk), forms)
			cut = max(len(buf) - keep, buf.rfind('\n') + 1 if by_line else 0) if chunk else len(buf)
			out.write(buf[:cut])
			out.flush()
			buf = buf[cut:]
			if not chunk:
				break
	os.close(rfd)


def _remote_upload(js):
	"""upload_file for a remote browser: local paths mean nothing on the browser host, so send the bytes."""
	import mimetypes

	def upload_file(selector, path):
		"""Set local file(s) on a file input of the remote browser (bytes go through the page, 10MB each max)."""
		files = []
		for p in [path] if isinstance(path, (str, Path)) else path:
			data = Path(p).read_bytes()
			if len(data) > 10_000_000:
				raise ValueError(f'{p} is over 10MB; remote uploads go through the page')
			files.append(
				{
					'name': Path(p).name,
					'type': mimetypes.guess_type(str(p))[0] or 'application/octet-stream',
					'b64': base64.b64encode(data).decode(),
				}
			)
		n = js(f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return -1;
            const dt = new DataTransfer();
            for (const f of {json.dumps(files)}) {{
                const bytes = Uint8Array.from(atob(f.b64), c => c.charCodeAt(0));
                dt.items.add(new File([bytes], f.name, {{type: f.type}}));
            }}
            el.files = dt.files;
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return el.files.length;
        }})()""")
		if n == -1:
			raise RuntimeError(f'no element for {selector}')
		return n

	return upload_file


def _jsonable(value):
	"""json.dumps default for delivery: pydantic models, dataclasses, dates as JSON (str(model) is not the schema)."""
	from pydantic_core import to_jsonable_python

	return to_jsonable_python(value, fallback=str)


def _display(value) -> None:
	if value is None or isinstance(value, ax.Printed):  # bu already printed it
		return
	print(value if isinstance(value, str) else pprint.pformat(value, width=120, sort_dicts=False))


def _compile(code: str, n: int):
	flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
	tree = compile(code, f'<cell {n}>', 'exec', flags=ast.PyCF_ONLY_AST | flags)
	if tree.body and isinstance(tree.body[-1], ast.Expr):  # REPL-style: show the last expression
		last = tree.body[-1]
		call = ast.copy_location(ast.Call(ast.Name('__bu_display', ast.Load()), [last.value], []), last.value)
		tree.body[-1] = ast.copy_location(ast.Expr(call), last)
		ast.fix_missing_locations(tree)
	return compile(tree, f'<cell {n}>', 'exec', flags=flags)


def _run(code_obj, ns, loop):
	if code_obj.co_flags & inspect.CO_COROUTINE:
		return loop.run_until_complete(eval(code_obj, ns))
	return exec(code_obj, ns)


def _error(e: BaseException) -> str:
	lines = traceback.format_exception(e)
	# Drop worker and bu frames; keep the user's cell frames and the exception itself.
	keep = [lines[0]] + [
		line for line in lines[1:] if not line.lstrip().startswith(('File "' + __file__, 'File "' + ax.__file__))
	]
	return ''.join(keep).strip()


def main() -> None:
	sock = socket.create_connection(('127.0.0.1', int(os.environ.pop('BU_REPL_PORT'))))
	rfile, wfile = sock.makefile('rb'), sock.makefile('wb')
	wfile.write(os.environ.pop('BU_REPL_TOKEN').encode() + b'\n')
	wfile.flush()
	secrets = json.loads(rfile.readline())['secrets']
	cells = STATE / 'cells'
	cells.mkdir(parents=True, exist_ok=True)
	sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)  # type: ignore[attr-defined]
	sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)  # type: ignore[attr-defined]
	ns: dict = {'__name__': '__main__', '__bu_display': _display}
	bu = _install(ns, secrets)
	sys.path.append(os.getcwd())  # after the imports (-P kept it off sys.path[0]): modules the agent writes still import
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)

	def send(msg):
		wfile.write(json.dumps(msg).encode() + b'\n')
		wfile.flush()

	send({'type': 'ready'})
	for line in rfile:
		msg = json.loads(line)
		images.clear()
		out_path = cells / f'{msg["n"]:04d}.txt'
		error = value = None
		rfd, wfd = os.pipe()
		pump = threading.Thread(target=_pump, args=(rfd, out_path, secrets), daemon=True)
		pump.start()
		# Cell stdout/stderr, subprocesses included, go through the redacting pump into out_path.
		saved = os.dup(1), os.dup(2)
		os.dup2(wfd, 1)
		os.dup2(wfd, 2)
		os.close(wfd)
		try:
			if msg['op'] == 'exec':
				_run(_compile(msg['code'], msg['n']), ns, loop)
			else:  # 'eval': read an existing value for delivery
				obj = compile(msg['code'], '<finish>', 'eval', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
				value = _run(obj, ns, loop) if obj.co_flags & inspect.CO_COROUTINE else eval(obj, ns)
				value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=_jsonable)
		except BaseException as e:  # - the agent sees every failure
			if isinstance(e, (SystemExit, KeyboardInterrupt)):
				error = f'{type(e).__name__} ignored; the REPL keeps running.'
			else:
				error = _error(e)
		finally:
			# After a cell whose bu actions reached the page, show the resulting state without another model turn.
			if bu is not None and bu.acted:
				try:
					bu.state()
				except Exception as e:
					print(f'[state unavailable: {type(e).__name__}: {e}]')
			sys.stdout.flush()
			sys.stderr.flush()
			os.dup2(saved[0], 1)
			os.dup2(saved[1], 2)
			os.close(saved[0])
			os.close(saved[1])
		pump.join(5)  # a background subprocess may hold the pipe open; its later output still lands in the file
		with open(out_path, encoding='utf-8', errors='replace') as f:
			output = clip(f.read(MAX_OUTPUT_CHARS + 1), out_path)
		send(
			{
				'type': 'result',
				'n': msg['n'],
				'output': output,
				'error': error,
				'value': value,
				'images': list(images),
				'output_file': str(out_path),
			}
		)


if __name__ == '__main__':
	main()
