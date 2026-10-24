import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import browser_use


class InstalledWheelTests(unittest.TestCase):
	def test_private_runtime_starts_without_node_on_path(self):
		runtime = Path(browser_use.__file__).with_name('runtime')
		executable = runtime / ('node.exe' if os.name == 'nt' else 'node')
		self.assertTrue(executable.is_file(), 'The installed wheel lacks its private Node runtime.')
		manifest = json.loads((runtime / 'node.json').read_text())
		self.assertEqual(hashlib.sha256(executable.read_bytes()).hexdigest(), manifest['binary_sha256'])
		self.assertGreater((runtime / 'NODE_LICENSE.txt').stat().st_size, 1000)
		self.assertGreater((runtime / 'THIRD_PARTY_NOTICES.txt').stat().st_size, 1000)
		for asset in ('server.mjs', 'worker.js', 'photon_rs_bg.wasm'):
			self.assertTrue((runtime / asset).is_file(), f'Missing engine asset: {asset}')
		with tempfile.TemporaryDirectory(prefix='browser-use-path-') as empty_path:
			previous_path = os.environ.get('PATH')
			previous_override = os.environ.pop('BROWSER_USE_NODE', None)
			os.environ['PATH'] = empty_path
			try:
				self.assertIsNone(shutil.which('node'))
				version = subprocess.check_output([str(executable), '--version'], text=True).strip()
				self.assertEqual(version, f'v{manifest["version"]}')
				asyncio.run(self.start_and_close())
			finally:
				if previous_path is None:
					os.environ.pop('PATH', None)
				else:
					os.environ['PATH'] = previous_path
				if previous_override is not None:
					os.environ['BROWSER_USE_NODE'] = previous_override

	async def start_and_close(self):
		with tempfile.TemporaryDirectory(prefix='browser-use-worker-') as workspace:
			agent = await browser_use.BrowserUse.start()
			try:
				self.assertIsNone(agent._process.returncode)
				await agent.configure(
					browser={'cdpUrl': 'ws://127.0.0.1:9/devtools/browser/unused'}, workspace=workspace, telemetry=False
				)
				self.assertEqual((await agent.execute('21 * 2'))['text'], '42')
			finally:
				await agent.close()
			self.assertIsNotNone(agent._process.returncode)


if __name__ == '__main__':
	unittest.main()
