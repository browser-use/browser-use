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
import inspect
import io
import json
import os
import pprint
import socket
import sys
import threading
import traceback
from pathlib import Path

from browser_use import ax
from browser_use.repl.session import MAX_OUTPUT_CHARS, clip, domain_matches, redact, redact_forms, secret_forms

MAX_IMAGES_PER_CELL = 4
MAX_IMAGE_SIDE = 2048  # full-page captures exceeded OpenAI's 30k-patch limit (bub2-002)
CDP_TIMEOUT_S = 20.0  # bu-pi cdp timeout; 30s/60s waits made each stall cost more (v1b: 114 Hard timeouts)
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
		params.setdefault('_response_timeout', CDP_TIMEOUT_S)
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
		value = redact(json.loads(json.dumps(value, default=str)), secrets)  # secret values never reach the disk
		_write_atomic(path, json.dumps(value, ensure_ascii=False, indent=1))
		if partial:
			_write_atomic(STATE / 'partial.json', json.dumps({'file': str(path), 'value': value}, ensure_ascii=False))
		return str(path)

	type_text = helpers.type_text

	def _page_url() -> str:
		# The browser's own record of the page type_text types into (same CDP session), never page JS: page_info()
		# runs JSON.stringify in the page, which the page can override to report an allowed URL.
		frame = (helpers.cdp('Page.getFrameTree').get('frameTree') or {}).get('frame') or {}
		return str(frame.get('url') or '')

	def type_secret(name):
		"""Type the secret called `name` into the focused element. Its value is hidden from your text output.
		A domain-scoped secret types only while the current page matches its domain."""
		candidates = [(v, scope) for n, v, scope in secrets if n == name]
		if not candidates:
			raise KeyError(f'No secret named {name!r}; secret_names() lists them')
		scoped = [(v, scope) for v, scope in candidates if scope is not None]
		if scoped:
			url = _page_url()
			for value, scope in scoped:
				if domain_matches(url, scope):
					return type_text(value)
		for value, scope in candidates:
			if scope is None:
				return type_text(value)
		raise PermissionError(
			f'Secret {name!r} may only be typed on {", ".join(sorted({s for _, s in scoped}))}; the current page is '
			f'{url or "unknown"}. Navigate to the right site first.'
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
