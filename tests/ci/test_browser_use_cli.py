import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_browser_use_cli(*args: str, module: str = 'browser_use.cli') -> subprocess.CompletedProcess[str]:
	env = os.environ.copy()
	env['PYTHONPATH'] = os.pathsep.join(part for part in (str(ROOT), env.get('PYTHONPATH', '')) if part)
	return subprocess.run(
		[sys.executable, '-m', module, *args],
		cwd=ROOT,
		env=env,
		capture_output=True,
		text=True,
		timeout=20,
	)


def test_browser_use_doctor_help_prints_browser_use_usage():
	result = _run_browser_use_cli('doctor', '--help')

	assert result.returncode == 0
	assert result.stdout == 'usage: browser-use doctor [--fix-snap]\n'
	assert result.stderr == ''


def test_browser_use_module_entrypoint_matches_cli_entrypoint():
	cli_result = _run_browser_use_cli('doctor', '--help')
	module_result = _run_browser_use_cli('doctor', '--help', module='browser_use')

	assert module_result.returncode == cli_result.returncode == 0
	assert module_result.stdout == cli_result.stdout
	assert module_result.stderr == cli_result.stderr == ''


def test_normalize_captured_cli_output_handles_string_system_exit(capsys):
	from browser_use.cli import _normalize_captured_cli_output

	def exits_with_string(_argv):
		raise SystemExit('browser-harness failed')

	assert _normalize_captured_cli_output(exits_with_string, []) == 1
	captured = capsys.readouterr()
	assert captured.out == ''
	assert captured.err == 'browser-use failed\n'


def test_browser_use_tui_is_deprecated_alias(monkeypatch, capsys):
	import browser_use.cli as browser_use_cli

	monkeypatch.setattr(browser_use_cli, 'main', lambda: 0)

	assert browser_use_cli.browser_use_tui_main() == 0
	assert capsys.readouterr().err == 'browser-use-tui is deprecated; use browser-use instead.\n'


def test_read_piped_stdin_falls_back_to_utf8_when_process_encoding_rejects(monkeypatch):
	"""UTF-8 pipe bytes that are illegal in the process code page should still decode."""
	import importlib.util
	import io
	from pathlib import Path

	cli_path = Path(__file__).resolve().parents[2] / 'browser_use' / 'cli.py'
	spec = importlib.util.spec_from_file_location('browser_use_cli_under_test', cli_path)
	assert spec is not None and spec.loader is not None
	browser_use_cli = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(browser_use_cli)

	class _LegacyStdin:
		encoding = 'gbk'

		def __init__(self, data: bytes):
			self.buffer = io.BytesIO(data)

		def read(self, *args, **kwargs):
			raise AssertionError('must not decode piped stdin through the legacy text wrapper')

		def isatty(self) -> bool:
			return False

	# UTF-8 of 中文 is invalid under GBK (unlike 你好, which is valid GBK mojibake).
	payload = 'print("中文")\n'.encode()
	try:
		payload.decode('gbk')
		raise AssertionError('expected UTF-8 中文 payload to be invalid GBK')
	except UnicodeDecodeError:
		pass

	monkeypatch.delenv('BROWSER_USE_STDIN_ENCODING', raising=False)
	monkeypatch.setattr(browser_use_cli.sys, 'stdin', _LegacyStdin(payload))
	assert browser_use_cli._read_piped_stdin() == 'print("中文")\n'


def test_read_piped_stdin_uses_process_encoding_for_gbk_only_bytes(monkeypatch):
	"""GBK-piped bytes that are not valid UTF-8 should decode via stdin.encoding."""
	import importlib.util
	import io
	from pathlib import Path

	cli_path = Path(__file__).resolve().parents[2] / 'browser_use' / 'cli.py'
	spec = importlib.util.spec_from_file_location('browser_use_cli_under_test_fallback', cli_path)
	assert spec is not None and spec.loader is not None
	browser_use_cli = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(browser_use_cli)

	class _LegacyStdin:
		encoding = 'gbk'

		def __init__(self, data: bytes):
			self.buffer = io.BytesIO(data)

		def read(self, *args, **kwargs):
			raise AssertionError('buffer already consumed; must decode with process encoding')

		def isatty(self) -> bool:
			return False

	payload = 'print("你好")\n'.encode('gbk')
	# Sanity: these bytes are not valid UTF-8
	try:
		payload.decode('utf-8')
		raise AssertionError('expected GBK payload to be invalid UTF-8')
	except UnicodeDecodeError:
		pass

	monkeypatch.delenv('BROWSER_USE_STDIN_ENCODING', raising=False)
	monkeypatch.setattr(browser_use_cli.sys, 'stdin', _LegacyStdin(payload))
	assert browser_use_cli._read_piped_stdin() == 'print("你好")\n'


def test_read_piped_stdin_prefers_process_encoding_for_ambiguous_gbk_bytes(monkeypatch):
	"""GBK 茅 (c3 a9) must not be misread as UTF-8 é."""
	import importlib.util
	import io
	from pathlib import Path

	cli_path = Path(__file__).resolve().parents[2] / 'browser_use' / 'cli.py'
	spec = importlib.util.spec_from_file_location('browser_use_cli_under_test_ambiguous', cli_path)
	assert spec is not None and spec.loader is not None
	browser_use_cli = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(browser_use_cli)

	class _LegacyStdin:
		encoding = 'gbk'

		def __init__(self, data: bytes):
			self.buffer = io.BytesIO(data)

		def read(self, *args, **kwargs):
			raise AssertionError('must not decode piped stdin through the legacy text wrapper')

		def isatty(self) -> bool:
			return False

	payload = 'print("茅")\n'.encode('gbk')
	assert payload.decode('utf-8') == 'print("é")\n'  # ambiguity sanity

	monkeypatch.delenv('BROWSER_USE_STDIN_ENCODING', raising=False)
	monkeypatch.setattr(browser_use_cli.sys, 'stdin', _LegacyStdin(payload))
	result = browser_use_cli._read_piped_stdin()
	assert result == 'print("茅")\n'
	assert result != 'print("é")\n'


def test_read_piped_stdin_honors_browser_use_stdin_encoding_override(monkeypatch):
	"""BROWSER_USE_STDIN_ENCODING forces decode even when stdin.encoding differs."""
	import importlib.util
	import io
	from pathlib import Path

	cli_path = Path(__file__).resolve().parents[2] / 'browser_use' / 'cli.py'
	spec = importlib.util.spec_from_file_location('browser_use_cli_under_test_override', cli_path)
	assert spec is not None and spec.loader is not None
	browser_use_cli = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(browser_use_cli)

	class _LegacyStdin:
		encoding = 'gbk'

		def __init__(self, data: bytes):
			self.buffer = io.BytesIO(data)

		def read(self, *args, **kwargs):
			raise AssertionError('must not decode piped stdin through the legacy text wrapper')

		def isatty(self) -> bool:
			return False

	# Same ambiguous GBK bytes: forced UTF-8 should yield é, not 茅.
	payload = 'print("茅")\n'.encode('gbk')
	monkeypatch.setenv('BROWSER_USE_STDIN_ENCODING', 'utf-8')
	monkeypatch.setattr(browser_use_cli.sys, 'stdin', _LegacyStdin(payload))
	assert browser_use_cli._read_piped_stdin() == 'print("é")\n'


def test_read_piped_stdin_unknown_encoding_override_falls_back_to_utf8(monkeypatch):
	"""Unknown BROWSER_USE_STDIN_ENCODING must LookupError-fall back to UTF-8."""
	import importlib.util
	import io
	from pathlib import Path

	cli_path = Path(__file__).resolve().parents[2] / 'browser_use' / 'cli.py'
	spec = importlib.util.spec_from_file_location('browser_use_cli_under_test_lookup', cli_path)
	assert spec is not None and spec.loader is not None
	browser_use_cli = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(browser_use_cli)

	class _LegacyStdin:
		encoding = 'ascii'

		def __init__(self, data: bytes):
			self.buffer = io.BytesIO(data)

		def read(self, *args, **kwargs):
			raise AssertionError('must not decode piped stdin through the legacy text wrapper')

		def isatty(self) -> bool:
			return False

	payload = 'print("中文")\n'.encode()
	monkeypatch.setenv('BROWSER_USE_STDIN_ENCODING', 'not-a-real-codec')
	monkeypatch.setattr(browser_use_cli.sys, 'stdin', _LegacyStdin(payload))
	assert browser_use_cli._read_piped_stdin() == 'print("中文")\n'
