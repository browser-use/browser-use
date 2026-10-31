import json
import os
import stat
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from browser_use.config import ConfigLoadError, DBStyleConfigJSON, create_default_config, load_and_migrate_config


@pytest.fixture(autouse=True)
def _sandboxed_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path / 'cfgdir'))
	monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))


@pytest.fixture
def corrupt_config(tmp_path: Path) -> Path:
	config_path = tmp_path / 'config.json'
	config_path.write_text(create_default_config().model_dump_json()[:-1], encoding='utf-8')
	return config_path


def _restricted_profile(config: DBStyleConfigJSON) -> dict:
	profiles = [p for p in config.browser_profile.values() if p.default]
	assert profiles, 'expected a default profile'
	return profiles[0].model_dump(exclude_none=True)


def test_absent_file_still_creates_fresh_default(tmp_path: Path):
	config_path = tmp_path / 'config.json'

	config = load_and_migrate_config(config_path)

	assert config_path.exists()
	profile = _restricted_profile(config)
	assert 'allowed_domains' not in profile
	assert 'block_ip_addresses' not in profile


def test_corrupt_file_raises_instead_of_failing_open(corrupt_config: Path):
	with pytest.raises(ConfigLoadError) as exc_info:
		load_and_migrate_config(corrupt_config)

	assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
	assert f'The original file remains at {corrupt_config}.' in str(exc_info.value)


def test_corrupt_file_is_not_overwritten_and_backup_created(corrupt_config: Path):
	original = corrupt_config.read_bytes()
	backup = corrupt_config.with_suffix('.json.bak')

	with pytest.raises(ConfigLoadError) as exc_info:
		load_and_migrate_config(corrupt_config)

	assert corrupt_config.read_bytes() == original
	assert backup.read_bytes() == original
	assert f'A backup was created at {backup}.' in str(exc_info.value)


def test_existing_backup_is_preserved(corrupt_config: Path):
	backup = corrupt_config.with_suffix('.json.bak')
	previous = Path(__file__).read_bytes()
	backup.write_bytes(previous)
	original = corrupt_config.read_bytes()

	with pytest.raises(ConfigLoadError) as exc_info:
		load_and_migrate_config(corrupt_config)

	assert corrupt_config.read_bytes() == original
	assert backup.read_bytes() == previous
	assert f'The existing backup at {backup} was left unchanged.' in str(exc_info.value)


def test_backup_creation_failure_identifies_original(corrupt_config: Path):
	backup = corrupt_config.with_suffix('.json.bak')
	backup.mkdir()
	original = corrupt_config.read_bytes()

	with pytest.raises(ConfigLoadError) as exc_info:
		load_and_migrate_config(corrupt_config)

	assert corrupt_config.read_bytes() == original
	assert backup.is_dir()
	assert f'The original file remains at {corrupt_config}.' in str(exc_info.value)
	assert 'A backup was created' not in str(exc_info.value)


def test_unreadable_source_identifies_backup_failure(tmp_path: Path):
	config_path = tmp_path / 'config.json'
	config_path.mkdir()
	backup = config_path.with_suffix('.json.bak')

	with pytest.raises(ConfigLoadError) as exc_info:
		load_and_migrate_config(config_path)

	assert config_path.is_dir()
	assert not backup.exists()
	assert f'Could not create a complete backup at {backup}:' in str(exc_info.value)
	assert f'The original file remains at {config_path}.' in str(exc_info.value)


def test_concurrent_loads_preserve_original_and_backup(corrupt_config: Path):
	original = corrupt_config.read_bytes()

	def load_config():
		with pytest.raises(ConfigLoadError):
			load_and_migrate_config(corrupt_config)

	with ThreadPoolExecutor(max_workers=4) as executor:
		list(executor.map(lambda _: load_config(), range(16)))

	assert corrupt_config.read_bytes() == original
	assert corrupt_config.with_suffix('.json.bak').read_bytes() == original


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux file size resource limits')
def test_partial_backup_is_removed_and_retry_succeeds(corrupt_config: Path):
	code = textwrap.dedent("""\
		import resource
		import signal
		import sys
		from pathlib import Path
		from browser_use.config import ConfigLoadError, load_and_migrate_config

		config = Path(sys.argv[1])
		original = config.read_bytes()
		backup = config.with_suffix('.json.bak')
		limits = resource.getrlimit(resource.RLIMIT_FSIZE)
		signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
		resource.setrlimit(resource.RLIMIT_FSIZE, (8, limits[1]))
		try:
			load_and_migrate_config(config)
		except ConfigLoadError as error:
			assert 'Could not create a complete backup' in str(error)
		else:
			raise AssertionError('An invalid configuration must fail to load')
		finally:
			resource.setrlimit(resource.RLIMIT_FSIZE, limits)
		assert not backup.exists()
		assert config.read_bytes() == original
		try:
			load_and_migrate_config(config)
		except ConfigLoadError as error:
			assert 'A backup was created' in str(error)
		else:
			raise AssertionError('An invalid configuration must fail to load')
		assert backup.read_bytes() == original
		assert config.read_bytes() == original
	""")
	subprocess.run([sys.executable, '-c', code, str(corrupt_config)], check=True, capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX file permission bits')
@pytest.mark.parametrize('mode', [0o400, 0o600, 0o640])
def test_backup_permissions_do_not_expose_config(corrupt_config: Path, mode: int):
	corrupt_config.chmod(mode)

	with pytest.raises(ConfigLoadError):
		load_and_migrate_config(corrupt_config)

	backup = corrupt_config.with_suffix('.json.bak')
	assert stat.S_IMODE(backup.stat().st_mode) == mode & 0o600


@pytest.mark.skipif(os.name == 'nt', reason='Creating symlinks requires Windows privileges')
@pytest.mark.parametrize('existing_target', [False, True])
def test_backup_symlink_is_not_followed(corrupt_config: Path, existing_target: bool):
	target = corrupt_config.parent / 'backup-target'
	previous = Path(__file__).read_bytes()
	if existing_target:
		target.write_bytes(previous)
	backup = corrupt_config.with_suffix('.json.bak')
	backup.symlink_to(target)
	original = corrupt_config.read_bytes()

	with pytest.raises(ConfigLoadError) as exc_info:
		load_and_migrate_config(corrupt_config)

	assert corrupt_config.read_bytes() == original
	assert backup.is_symlink()
	assert f'The existing backup at {backup} was left unchanged.' in str(exc_info.value)
	if existing_target:
		assert target.read_bytes() == previous
	else:
		assert not target.exists()


def test_valid_restricted_file_still_loads(tmp_path: Path):
	config_path = tmp_path / 'config.json'
	config = create_default_config()
	profile = next(iter(config.browser_profile.values()))
	config.browser_profile[profile.id] = profile.model_copy(
		update={'allowed_domains': ['github.com'], 'prohibited_domains': ['127.0.0.1'], 'block_ip_addresses': True}
	)
	config_path.write_text(config.model_dump_json(), encoding='utf-8')

	loaded = load_and_migrate_config(config_path)

	assert loaded == config
	loaded_profile = _restricted_profile(loaded)
	assert loaded_profile['allowed_domains'] == ['github.com']
	assert loaded_profile['prohibited_domains'] == ['127.0.0.1']
	assert loaded_profile['block_ip_addresses'] is True
