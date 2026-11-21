import subprocess
import sys

from browser_use.skills import install


def test_non_ascii_uv_tool_directory_does_not_reinstall_running_environment(monkeypatch, tmp_path, capsys):
	tool_dir = tmp_path / 'équipe'
	real_run = subprocess.run
	calls = []

	def run(args, **kwargs):
		calls.append(args[1:])
		assert args[1:] == ['tool', 'dir'], 'must not reinstall the running uv tool environment'
		# A real child writes the UTF-8 path uv prints, independent of the parent's locale.
		return real_run(
			[sys.executable, '-c', f'import sys; sys.stdout.buffer.write({str(tool_dir).encode("utf-8")!r})'], **kwargs
		)

	monkeypatch.setattr(subprocess, '_text_encoding', lambda: 'cp1252')
	monkeypatch.setattr(install.shutil, 'which', lambda name: 'uv')
	monkeypatch.setattr(install.subprocess, 'run', run)
	monkeypatch.setattr(install.sys, 'prefix', str(tool_dir / 'browser-use'))
	monkeypatch.setattr('browser_use.utils.get_browser_use_version', lambda: '1.0.6')
	install._install_browser_use_tool()
	assert calls == [['tool', 'dir']]
	assert 'already installed as a uv tool' in capsys.readouterr().out
