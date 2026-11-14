"""upload_file and DOM.setFileInputFiles with local paths, also on a remote browser (cloud, a remote cdp_url), where a
local path means nothing on the browser host and the bytes go through the page. Used by the agent's REPL worker and by
the CLI / MCP server."""

import base64
import concurrent.futures
import contextlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

UPLOAD_PART = 24_000  # bytes per js() call: 32,000 base64 characters, well under browser-harness's 64 KiB per request


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


SIZES = 'function () { return Array.from(this.files || [], f => f.size) }'
PUT = """function (key, i, n, b64) {
	const w = this.ownerDocument.defaultView;
	((w[key] ||= [])[i] ||= [])[n] = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}"""
SET = """function (key, meta) {
	const w = this.ownerDocument.defaultView, parts = w[key] || [];
	delete w[key];
	const dt = new DataTransfer();
	meta.forEach(([name, type], i) => dt.items.add(new File(parts[i] || [], name, {type})));
	this.files = dt.files;
	this.dispatchEvent(new Event('input', {bubbles: true}));
	this.dispatchEvent(new Event('change', {bubbles: true}));
	return this.files.length;
}"""


def set_files(cdp, object_id: str, path, remote: bool) -> int:
	"""Set local file(s) on the file input object_id; returns how many it holds. A remote browser cannot read a local
	path: Browser Use cloud rejects it ('Files must exist in the downloads directory'), another host's Chrome sets empty
	or missing files. There, and whenever the input does not then hold files of the local sizes (Browser(cdp_url=) to a
	remote host), the bytes go through the page, in parts (one browser-harness request takes at most 64 KiB), several
	at a time. cdp(method, **params) runs on the element's session."""
	import mimetypes

	paths = local_paths(path)

	def call(fn: str, *args) -> Any:
		r = cdp(
			'Runtime.callFunctionOn',
			objectId=object_id,
			functionDeclaration=fn,
			arguments=[{'value': a} for a in args],
			returnByValue=True,
		)
		if r.get('exceptionDetails'):
			raise RuntimeError(f'upload_file: {r["exceptionDetails"].get("text", "the page refused the files")}')
		return r.get('result', {}).get('value')

	if not remote:
		with contextlib.suppress(RuntimeError):  # rejected: a remote browser behind cdp_url
			cdp('DOM.setFileInputFiles', objectId=object_id, files=paths)
			if call(SIZES) == [os.path.getsize(p) for p in paths]:
				return len(paths)
	files = [Path(p).read_bytes() for p in paths]
	key = f'__buUpload{os.urandom(4).hex()}'
	parts = [(i, n, k) for i, data in enumerate(files) for n, k in enumerate(range(0, len(data), UPLOAD_PART))]

	def put(part: tuple[int, int, int]) -> None:  # part n of file i, decoded in the page
		i, n, k = part
		call(PUT, key, i, n, base64.b64encode(files[i][k : k + UPLOAD_PART]).decode())

	try:
		with concurrent.futures.ThreadPoolExecutor(8) as pool:  # each part is one round trip to the browser
			list(pool.map(put, parts))
		return call(SET, key, [[Path(p).name, mimetypes.guess_type(p)[0] or 'application/octet-stream'] for p in paths])
	finally:  # SET deletes the parts; a failed part must not leave them in the page either
		with contextlib.suppress(Exception):
			call('function (key) { delete this.ownerDocument.defaultView[key] }', key)


def uploader(cdp, remote: Callable[[], bool]):
	"""upload_file(selector, path) on the attached tab; remote(): whether the browser is a cloud browser."""

	def upload_file(selector, path):
		"""Set local file(s) on a file input. path: a file path or a list of them (relative to the working directory).
		On a remote browser the bytes go through the page."""
		el = cdp('Runtime.evaluate', expression=find(selector))['result']
		if 'objectId' not in el:
			raise RuntimeError(f'no element for {selector}')
		return set_files(cdp, el['objectId'], path, remote())

	return upload_file
