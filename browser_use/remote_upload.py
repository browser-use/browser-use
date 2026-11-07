"""upload_file for a remote browser (cloud): a local path means nothing on the browser host, so the bytes go through
the page. Used by the agent's REPL worker and by the CLI / MCP server while they drive a cloud browser."""

import base64
import concurrent.futures
import contextlib
import json
import os
from pathlib import Path

UPLOAD_PART = 24_000  # bytes per js() call: 32,000 base64 characters, well under browser-harness's 64 KiB per request
UPLOAD_MAX = 10_000_000  # bytes per file


def local_paths(path) -> list[str]:
	"""Absolute paths of existing files (relative ones from the working directory, ~ expanded). Raises otherwise:
	DOM.setFileInputFiles takes any string, and a missing, relative or directory path became a 0-byte upload."""
	out = []
	for p in [path] if isinstance(path, (str, os.PathLike)) else path:
		full = Path(p).expanduser().resolve()
		if not full.is_file():
			raise FileNotFoundError(f'upload_file: {str(p)!r} is not a file ({full})')
		out.append(str(full))
	return out


def find(selector) -> str:
	"""JS for the first match of selector in the page, its open shadow roots and same-origin frames."""
	return f"""(() => {{
		const q = r => {{ let el = r.querySelector({json.dumps(selector)});
			for (const e of r.querySelectorAll('*')) el ||= (e.shadowRoot && q(e.shadowRoot)) || (e.contentDocument && q(e.contentDocument));
			return el; }};
		return q(document);
	}})()"""


def local_upload(cdp):
	"""upload_file for a local browser, with every path checked and made absolute first."""

	def upload_file(selector, path):
		"""Set local file(s) on a file input. path: a file path or a list of them (relative to the working directory)."""
		paths = local_paths(path)
		el = cdp('Runtime.evaluate', expression=find(selector))['result']
		if 'objectId' not in el:
			raise RuntimeError(f'no element for {selector}')
		cdp('DOM.setFileInputFiles', objectId=el['objectId'], files=paths)

	return upload_file


def remote_upload(js):
	"""upload_file for a remote browser: local paths mean nothing on the browser host, so send the bytes through the
	page, in parts (one browser-harness request takes at most 64 KiB), several at a time."""
	import mimetypes

	def upload_file(selector, path):
		"""Set local file(s) on a file input of the remote browser (bytes go through the page, 10MB each max)."""
		files = []
		for p in [path] if isinstance(path, (str, os.PathLike)) else path:
			data = Path(p).expanduser().read_bytes()
			if len(data) > UPLOAD_MAX:
				raise ValueError(f'{p} is over 10MB; remote uploads go through the page')
			files.append((Path(p).name, mimetypes.guess_type(str(p))[0] or 'application/octet-stream', data))
		buf = f'window.__buUpload{os.urandom(4).hex()}'
		js(f'{buf} = {json.dumps([[] for _ in files])}; 0')
		try:

			def put(i: int, n: int, k: int) -> None:  # part n of file i, decoded in the page
				b64 = json.dumps(base64.b64encode(files[i][2][k : k + UPLOAD_PART]).decode())
				js(f'{buf}[{i}][{n}] = Uint8Array.from(atob({b64}), c => c.charCodeAt(0)); 0')

			parts = [(i, n, k) for i, f in enumerate(files) for n, k in enumerate(range(0, len(f[2]), UPLOAD_PART))]
			with concurrent.futures.ThreadPoolExecutor(8) as pool:  # each js() is one round trip to the browser
				list(pool.map(lambda part: put(*part), parts))
			meta = json.dumps([[name, mime] for name, mime, _ in files])
			n = js(f"""(() => {{
				const el = {find(selector)};
				if (!el) return -1;
				const dt = new DataTransfer();
				{meta}.forEach(([name, type], i) => dt.items.add(new File({buf}[i], name, {{type}})));
				el.files = dt.files;
				el.dispatchEvent(new Event('input', {{bubbles: true}}));
				el.dispatchEvent(new Event('change', {{bubbles: true}}));
				return el.files.length;
			}})()""")
		finally:
			with contextlib.suppress(Exception):
				js(f'delete {buf}; 0')
		if n == -1:
			raise RuntimeError(f'no element for {selector}')
		return n

	return upload_file
