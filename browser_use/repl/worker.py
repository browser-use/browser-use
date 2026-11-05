"""Persistent Python REPL for one agent. Runs as a child process so a hung cell can be killed.

Namespace = browser-harness helpers + screenshot/show_image/checkpoint/type_secret (+ bu in ultrafast mode, see ax.py).
Protocol: connect to 127.0.0.1:BU_REPL_PORT, send BU_REPL_TOKEN, read one init line ({"secrets": {...}}), then one JSON
line per message. Cell stdout/stderr (including subprocesses) go to a per-cell file, so a killed cell still leaves its
partial output on disk.
"""

import ast
import asyncio
import base64
import inspect
import io
import json
import os
import pprint
import socket
import sys
import traceback
from pathlib import Path

from browser_use import ax
from browser_use.repl.session import SECRET_ENV

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


def _install(ns: dict, secrets: dict[str, str]) -> ax.AxHelpers | None:
	from browser_harness import helpers

	for k in [k for k in os.environ if SECRET_ENV.search(k)]:  # browser-harness may load .env files into os.environ
		del os.environ[k]

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
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_name(path.name + '.tmp')
		tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str))
		os.replace(tmp, path)
		if partial:
			STATE.mkdir(parents=True, exist_ok=True)
			(STATE / 'partial.json').write_text(json.dumps({'file': str(path), 'value': value}, default=str))
		return str(path)

	type_text = helpers.type_text

	def type_secret(name):
		"""Type the secret called `name` into the focused element. Its value is never shown to you."""
		if name not in secrets:
			raise KeyError(f'No secret named {name!r}; secret_names() lists them')
		type_text(secrets[name])

	def secret_names():
		"""Names of the secrets you can type with type_secret(name)."""
		return sorted(secrets)

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
	sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
	sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
	ns: dict = {'__name__': '__main__', '__bu_display': _display}
	bu = _install(ns, secrets)
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
		with open(out_path, 'wb') as out:
			saved = os.dup(1), os.dup(2)
			os.dup2(out.fileno(), 1)
			os.dup2(out.fileno(), 2)
			try:
				if msg['op'] == 'exec':
					_run(_compile(msg['code'], msg['n']), ns, loop)
				else:  # 'eval': read an existing value for delivery
					obj = compile(msg['code'], '<finish>', 'eval', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
					value = _run(obj, ns, loop) if obj.co_flags & inspect.CO_COROUTINE else eval(obj, ns)
					value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
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
		send(
			{
				'type': 'result',
				'output': out_path.read_text(errors='replace'),
				'error': error,
				'value': value,
				'images': list(images),
				'output_file': str(out_path),
			}
		)


if __name__ == '__main__':
	main()
