import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_server_manifest_uses_typed_mcp_server():
	manifest = json.loads((ROOT / 'server.json').read_text(encoding='utf-8'))
	pypi_packages = [
		package
		for package in manifest['packages']
		if package['registryType'] == 'pypi' and package['identifier'] == 'browser-use'
	]
	assert len(pypi_packages) == 1
	assert pypi_packages[0]['version'] == manifest['version']
	assert pypi_packages[0]['packageArguments'] == [{'type': 'positional', 'value': '--mcp'}]
