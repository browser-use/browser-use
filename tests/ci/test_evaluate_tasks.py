import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = ROOT / 'tests' / 'ci' / 'evaluate_tasks.py'


@pytest.fixture(autouse=True)
def disable_evaluation_api_calls(monkeypatch):
	monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
	monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
	monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


@pytest.mark.parametrize('mode', ['directory', 'single', 'default'])
def test_evaluator_cli_selects_tasks(tmp_path, mode):
	task_file = tmp_path / 'custom.yaml'
	task_file.write_text('task: Offline task selection check\n', encoding='utf-8')
	args = {
		'directory': [str(tmp_path)],
		'single': ['--task', str(task_file)],
		'default': [],
	}[mode]

	result = subprocess.run(
		[sys.executable, str(EVALUATOR), *args],
		cwd=ROOT,
		capture_output=True,
		text=True,
		encoding='utf-8',
		timeout=60,
	)

	assert result.returncode == 0, result.stderr
	if mode == 'single':
		output = json.loads(result.stdout.splitlines()[-1])
		assert output['file'] == task_file.name
		assert output['explanation'] == 'Skipped - API key not available (fork PR or missing secret)'
	else:
		expected_files = [task_file] if mode == 'directory' else list((ROOT / 'tests' / 'agent_tasks').glob('*.yaml'))
		assert f'TOTAL={len(expected_files)}' in result.stdout.splitlines()
		for expected_file in expected_files:
			assert expected_file.name in result.stdout


@pytest.mark.parametrize('path_kind', ['missing', 'file', 'empty'])
def test_evaluator_validates_task_directory(tmp_path, path_kind):
	task_dir = tmp_path / 'tasks'
	if path_kind == 'file':
		task_dir.write_text('', encoding='utf-8')
	elif path_kind == 'empty':
		task_dir.mkdir()

	result = subprocess.run(
		[sys.executable, str(EVALUATOR), str(task_dir)],
		cwd=ROOT,
		capture_output=True,
		text=True,
		encoding='utf-8',
		timeout=60,
	)

	if path_kind == 'empty':
		assert result.returncode == 0, result.stderr
		assert 'No task files found!' in result.stdout
	else:
		assert result.returncode == 2
		assert f'Not a task directory: {task_dir}' in result.stderr
