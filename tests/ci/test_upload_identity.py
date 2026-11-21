"""CDP paths belong to the browser host, even when its file has the expected size."""

import contextlib
import json
import threading

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.sync.server import serve

from browser_use import Browser
from browser_use.repl import Repl


@pytest.mark.parametrize('raw_cdp', [False, True])
async def test_upload_sends_client_bytes_before_the_page_receives_change(chrome, tmp_path, raw_cdp):
	client_path, host_path = tmp_path / 'client' / 'report.txt', tmp_path / 'host' / 'report.txt'
	for path, content in ((client_path, b'client'), (host_path, b'server')):
		path.parent.mkdir()
		path.write_bytes(content)

	def relay(client):
		with connect(chrome['ws'], max_size=None) as upstream:

			def down():
				with contextlib.suppress(ConnectionClosed):
					for message in upstream:
						client.send(message)

			thread = threading.Thread(target=down, daemon=True)
			thread.start()
			try:
				for message in client:
					msg = json.loads(message)
					if msg.get('method') == 'DOM.setFileInputFiles':
						# Model a different host filesystem; every other CDP/browser operation is real.
						files = msg.get('params', {}).get('files', [])
						msg['params']['files'] = [str(host_path) if p == str(client_path) else p for p in files]
					upstream.send(json.dumps(msg))
			except ConnectionClosed:
				pass
			finally:
				upstream.close()
				thread.join(timeout=3)

	server = serve(relay, '127.0.0.1', 0, max_size=None)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	browser = Browser(cdp_url=f'ws://127.0.0.1:{server.socket.getsockname()[1]}/devtools/browser/remote-files')
	repl = None
	try:
		repl = Repl(tmp_path, await browser.start())
		code = (
			"new_tab('data:text/html,<input id=f type=file>'); wait_for_load()\n"
			'js("window.changes=[]; f.onchange=()=>changes.push(f.files[0].text())")\n'
		)
		if raw_cdp:
			code += "node=cdp('DOM.getDocument')['root']['nodeId']\n"
			code += "node=cdp('DOM.querySelector', nodeId=node, selector='#f')['nodeId']\n"
			code += f"cdp('DOM.setFileInputFiles', nodeId=node, files=[{str(client_path)!r}])\n"
		else:
			code += f"upload_file('#f', {str(client_path)!r})\n"
		code += 'print(js("Promise.all(changes)"))'
		r = await repl.call('exec', code, 30)
		assert r['error'] is None, r['error']
		assert r['output'].strip() == "['client']", r['output']
	finally:
		if repl is not None:
			await repl.close()
		await browser.stop()
		server.shutdown()
		thread.join(timeout=3)
