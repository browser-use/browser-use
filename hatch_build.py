import hashlib
import io
import json
import os
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

NODE_VERSION = '24.22.1'
NODE_ARCHIVES = {
	'linux-x64': ('tar.xz', '6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6', 'manylinux_2_28_x86_64'),
	'linux-arm64': ('tar.xz', 'dbabf7a1cbf947e6059ffad2c27b80041db97dea1e553b62afdee7f13fca336e', 'manylinux_2_28_aarch64'),
	'darwin-x64': ('tar.gz', 'd132557e7ee2b85af08b0c8c34338e65c6430f2238d01f727728ef42dc83b035', 'macosx_14_0_x86_64'),
	'darwin-arm64': ('tar.gz', '89c682593d76cd44233fa53b1563264e7de9cbb189cad169135c5b4fadfbc0a7', 'macosx_14_0_arm64'),
	'win-x64': ('zip', 'd2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5', 'win_amd64'),
}


def node_target():
	system = {'Linux': 'linux', 'Darwin': 'darwin', 'Windows': 'win'}.get(platform.system())
	machine = {'x86_64': 'x64', 'AMD64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
	if system == 'linux' and 'BROWSER_USE_WHEEL_TARGET' not in os.environ:
		libc, version = platform.libc_ver()
		if libc != 'glibc' or tuple(int(part) for part in version.split('.')[:2]) < (2, 28):
			raise RuntimeError('Bundled Linux Node requires glibc 2.28 or later; musl wheels are not available.')
	target = os.environ.get('BROWSER_USE_WHEEL_TARGET', f'{system}-{machine}')
	if target not in NODE_ARCHIVES:
		raise RuntimeError(f'No bundled Node wheel supports {target}; use a supported platform or a source runtime override.')
	return target


def node_files(target, cache):
	extension, expected, _ = NODE_ARCHIVES[target]
	stem = f'node-v{NODE_VERSION}-{target}'
	archive = cache / f'{stem}.{extension}'
	cache.mkdir(parents=True, exist_ok=True)
	if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
		with urllib.request.urlopen(f'https://nodejs.org/dist/v{NODE_VERSION}/{archive.name}', timeout=60) as response:
			content = response.read(150_000_001)
		if len(content) > 150_000_000 or hashlib.sha256(content).hexdigest() != expected:
			raise RuntimeError(f'Node archive checksum failed for {target}.')
		archive.write_bytes(content)
	content = archive.read_bytes()
	binary_name = 'node.exe' if target.startswith('win-') else 'node'
	binary_member = f'{stem}/{binary_name}' if target.startswith('win-') else f'{stem}/bin/node'
	if extension == 'zip':
		with zipfile.ZipFile(io.BytesIO(content)) as package:
			binary = package.read(binary_member)
			license_text = package.read(f'{stem}/LICENSE')
	else:
		with tarfile.open(fileobj=io.BytesIO(content)) as package:
			binary_file = package.extractfile(binary_member)
			license_file = package.extractfile(f'{stem}/LICENSE')
			if binary_file is None or license_file is None:
				raise RuntimeError(f'Node archive lacks required files for {target}.')
			binary = binary_file.read()
			license_text = license_file.read()
	return binary_name, binary, license_text, expected


class CustomBuildHook(BuildHookInterface):
	def initialize(self, version, build_data):
		if version == 'editable':
			return
		root = Path(self.root)
		runtime = root / 'browser_use' / 'runtime'
		required = ('server.mjs', 'worker.js', 'photon_rs_bg.wasm', 'package.json', 'THIRD_PARTY_NOTICES.txt')
		missing = [name for name in required if not (runtime / name).is_file()]
		if missing:
			raise RuntimeError('Build JavaScript assets with npm ci and npm run build:python before building a wheel.')
		target = node_target()
		name, binary, license_text, archive_sha = node_files(target, root / 'build' / 'node')
		staging = root / 'build' / 'node' / target
		staging.mkdir(parents=True, exist_ok=True)
		executable = staging / name
		if not executable.is_file() or hashlib.sha256(executable.read_bytes()).digest() != hashlib.sha256(binary).digest():
			replacement = executable.with_suffix('.new')
			replacement.write_bytes(binary)
			replacement.chmod(0o755)
			replacement.replace(executable)
		license_file = staging / 'NODE_LICENSE.txt'
		license_file.write_bytes(license_text)
		manifest = staging / 'node.json'
		manifest.write_text(
			json.dumps(
				{
					'version': NODE_VERSION,
					'target': target,
					'archive_sha256': archive_sha,
					'binary_sha256': hashlib.sha256(binary).hexdigest(),
				},
				sort_keys=True,
			)
			+ '\n'
		)
		build_data['force_include'][str(executable)] = f'browser_use/runtime/{name}'
		build_data['force_include'][str(license_file)] = 'browser_use/runtime/NODE_LICENSE.txt'
		build_data['force_include'][str(manifest)] = 'browser_use/runtime/node.json'
		build_data['pure_python'] = False
		build_data['tag'] = f'py3-none-{NODE_ARCHIVES[target][2]}'
