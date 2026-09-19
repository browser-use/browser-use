import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_server_manifest_matches_project_version():
	project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
	manifest = json.loads((ROOT / 'server.json').read_text(encoding='utf-8'))
	project_version = project['project']['version']

	assert manifest['version'] == project_version
	pypi_packages = [
		package
		for package in manifest['packages']
		if package['registryType'] == 'pypi' and package['identifier'] == 'browser-use'
	]
	assert len(pypi_packages) == 1
	assert pypi_packages[0]['version'] == project_version
	assert pypi_packages[0]['packageArguments'] == [{'type': 'positional', 'value': '--mcp'}]
