from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest_httpserver import HTTPServer

import browser_use.init_cmd as init_cmd


@pytest.fixture
def template_server(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
	httpserver.expect_request('/templates.json').respond_with_json({'demo': {'file': 'demo.py'}})
	httpserver.expect_request('/demo.py').respond_with_data("print('hello')\n")
	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', httpserver.url_for('/').rstrip('/'))
	monkeypatch.chdir(tmp_path)
	return tmp_path / 'demo' / 'main.py'


def test_init_returns_failure_when_template_cannot_be_written(template_server: Path, capsys: pytest.CaptureFixture[str]):
	template_server.mkdir(parents=True)
	result = CliRunner().invoke(init_cmd.main, ['--template', 'demo', '--force'])
	captured = capsys.readouterr()
	output = captured.out + captured.err + result.output

	assert result.exit_code == 1
	assert 'Error writing file' in output
	assert template_server.name in output.partition('Error writing file:')[2]
	assert 'Next steps' not in output
	assert template_server.is_dir()


@pytest.mark.parametrize('existing_file', [False, True])
def test_init_writes_template_successfully(template_server: Path, existing_file: bool, capsys: pytest.CaptureFixture[str]):
	if existing_file:
		template_server.parent.mkdir()
		template_server.write_text('old content', encoding='utf-8')

	result = CliRunner().invoke(init_cmd.main, ['--template', 'demo', '--force'])
	captured = capsys.readouterr()
	output = captured.out + captured.err + result.output

	assert result.exit_code == 0
	assert template_server.read_text(encoding='utf-8') == "print('hello')\n"
	assert 'Next steps' in output


def test_init_preserves_file_when_overwrite_is_declined(template_server: Path, capsys: pytest.CaptureFixture[str]):
	template_server.parent.mkdir()
	template_server.write_text('keep this content', encoding='utf-8')
	result = CliRunner().invoke(init_cmd.main, ['--template', 'demo'], input='y\nn\n')
	captured = capsys.readouterr()
	output = captured.out + captured.err + result.output

	assert result.exit_code == 0
	assert 'Cancelled' in output
	assert template_server.read_text(encoding='utf-8') == 'keep this content'
	assert 'Next steps' not in output
