"""Release workflows: which events build and push Docker images. Evaluates the job's `if:` expression in Python."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[2] / '.github' / 'workflows'


def gha_if(expression: str, github: NS) -> bool:
	"""A GitHub Actions `if:` built from startsWith/contains, ==, !, && and || (all docker.yml uses)."""
	expr = expression.strip().removeprefix('${{').removesuffix('}}')
	expr = expr.replace('&&', ' and ').replace('||', ' or ').replace('!(', ' not (')
	assert not re.search(r'!(?!=)', expr), f'unsupported expression: {expression}'
	funcs = {'startsWith': lambda s, p: s.startswith(p), 'contains': lambda s, p: p in s}
	return bool(eval(expr, {'__builtins__': {}}, {**funcs, 'github': github, 'true': True, 'false': False}))


def event(name: str, ref: str, prerelease: bool = False) -> NS:
	return NS(event_name=name, ref=ref, ref_name=ref.split('/', 2)[2], event=NS(release=NS(prerelease=prerelease)))


@pytest.mark.parametrize(
	'github, builds',
	[
		(event('push', 'refs/tags/1.0.0rc1'), False),
		(event('release', 'refs/tags/1.0.0rc1', prerelease=True), False),
		(event('release', 'refs/tags/1.0.0'), True),
		(event('push', 'refs/tags/1.0.0'), True),
		(event('push', 'refs/heads/main'), True),
		(event('push', 'refs/heads/releases/source-fix'), True),  # a branch name containing 'rc' still builds
	],
)
def test_docker_images_are_never_built_for_a_release_candidate(github, builds):
	"""Fable r4-6: tagging 1.0.0rc1 built and pushed browseruse/browseruse:1.0.0rc1 from a Dockerfile nobody ran on 1.0."""
	job = yaml.safe_load((WORKFLOWS / 'docker.yml').read_text())['jobs']['build_publish_image']
	assert gha_if(job.get('if', 'true'), github) is builds


def test_pull_requests_never_push_docker_images():
	job = yaml.safe_load((WORKFLOWS / 'docker.yml').read_text())['jobs']['build_publish_image']
	assert gha_if(job['if'], event('pull_request', 'refs/pull/6314/merge')) is False


def test_every_docker_image_is_built_and_run_on_pull_requests_before_one_is_pushed():
	"""package-10: docker.yml had no PR trigger, so the first amd64 build of a changed Dockerfile was the one it pushed."""
	workflow = yaml.safe_load((WORKFLOWS / 'docker.yml').read_text())
	triggers = workflow[True]  # PyYAML reads the `on:` key as True
	assert 'pull_request' in triggers and 'Dockerfile' in triggers['pull_request']['paths']
	smoke = workflow['jobs']['smoke']
	assert {'linux/amd64', 'linux/arm64'} == {row['platform'] for row in smoke['strategy']['matrix']['include']}
	build = next(step for step in smoke['steps'] if 'build-push-action' in step.get('uses', ''))
	assert build['with']['push'] is False and build['with']['load'] is True
	assert not any('login-action' in step.get('uses', '') for step in smoke['steps'])
	runs = '\n'.join(step.get('run', '') for step in smoke['steps'])
	assert '--version' in runs and 'docker/smoke.py' in runs
	assert workflow['jobs']['build_publish_image']['needs'] == 'smoke'


def test_lock_only_dependency_updates_rebuild_the_docker_image_on_pull_requests():
	"""The Dockerfile installs from uv.lock (`uv sync --locked`): a lock-only bump must run the smoke build."""
	assert 'uv.lock' in (WORKFLOWS.parents[1] / 'Dockerfile').read_text()
	assert 'uv.lock' in yaml.safe_load((WORKFLOWS / 'docker.yml').read_text())[True]['pull_request']['paths']


def test_the_wheel_smoke_test_imports_the_wheel_not_the_checkout():
	"""`python -c` puts the cwd first on sys.path: run from the repo root it imports ./browser_use, not the wheel."""
	steps = yaml.safe_load((WORKFLOWS / 'publish.yml').read_text())['jobs']['publish_to_pypi']['steps']
	script = next(step['run'] for step in steps if step.get('name') == 'Smoke test the wheel in a fresh venv')
	lines = script.splitlines()
	first_import = next(i for i, line in enumerate(lines) if 'python -c' in line and not line.lstrip().startswith('#'))
	assert any(line.strip().startswith('cd ') for line in lines[:first_import])


@pytest.mark.skipif(sys.platform == 'win32' or shutil.which('bash') is None, reason='runs the step with bash')
def test_the_chrome_job_fails_when_google_chrome_is_missing(tmp_path):
	"""Without google-chrome every chrome test skipped and the job still went green."""
	steps = yaml.safe_load((WORKFLOWS / 'test.yaml').read_text())['jobs']['chrome']['steps']
	script = next(step['run'] for step in steps if 'pytest' in step.get('run', ''))
	(tmp_path / 'uv').write_text('#!/bin/sh\nexit 0\n')  # pytest would pass with every test skipped
	(tmp_path / 'uv').chmod(0o755)
	env = {'PATH': str(tmp_path), 'HOME': str(tmp_path)}
	bash = shutil.which('bash') or 'bash'  # found before PATH is narrowed to tmp_path
	r = subprocess.run([bash, '-e', '-c', script], env=env, capture_output=True, text=True, timeout=30)
	assert r.returncode != 0 and 'google-chrome not found' in r.stderr
	(tmp_path / 'google-chrome').write_text('#!/bin/sh\n')
	(tmp_path / 'google-chrome').chmod(0o755)
	r = subprocess.run([bash, '-e', '-c', script], env=env, capture_output=True, text=True, timeout=30)
	assert r.returncode == 0, r.stderr


def test_the_docker_smoke_script_runs_an_agent_on_local_chromium(chrome_binary):
	"""docker/smoke.py, the image check above, passes against a real Chromium (here the test Chrome)."""
	import os
	import subprocess
	import sys

	env = {**os.environ, 'BH_CHROME_PATH': chrome_binary, 'ANONYMIZED_TELEMETRY': 'false'}
	r = subprocess.run(
		[sys.executable, str(WORKFLOWS.parents[1] / 'docker' / 'smoke.py')], env=env, capture_output=True, text=True, timeout=180
	)
	assert r.returncode == 0 and "status=completed result='docker smoke'" in r.stdout, r.stdout + r.stderr


def test_ci_test_tools_are_a_standard_dependency_group():
	"""publish.yml dry run: every `uv sync --dev` warned that tool.uv.dev-dependencies is deprecated and will be removed;
	a uv release without it installs no pytest, and test.yaml (unpinned uv) and publish.yml go red."""
	import tomllib

	pyproject = tomllib.loads((WORKFLOWS.parents[1] / 'pyproject.toml').read_text())
	assert 'dev-dependencies' not in pyproject['tool'].get('uv', {})
	dev = pyproject['dependency-groups']['dev']
	assert any(req.startswith('pytest==') for req in dev) and any(req.startswith('pytest-asyncio==') for req in dev)


def publish_steps() -> list[dict]:
	return yaml.safe_load((WORKFLOWS / 'publish.yml').read_text())['jobs']['publish_to_pypi']['steps']


@pytest.mark.skipif(sys.platform == 'win32' or shutil.which('bash') is None or shutil.which('git') is None, reason='bash + git')
def test_publish_needs_the_pyproject_version_tag_on_the_checked_out_commit(tmp_path):
	"""Fable 1.0.0: a dispatch with create_tag=false published whatever pyproject said, untagged, from any branch."""
	steps = publish_steps()
	check = next(i for i, step in enumerate(steps) if 'refs/tags/$version' in step.get('run', ''))
	publish = next(i for i, step in enumerate(steps) if 'pypi-publish' in step.get('uses', ''))
	assert 'if' not in steps[check] and check < publish

	def git(*args: str, cwd: Path) -> str:
		return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

	origin, work = tmp_path / 'origin.git', tmp_path / 'work'
	git('init', '-q', '--bare', str(origin), cwd=tmp_path)
	git('init', '-q', str(work), cwd=tmp_path)
	ident = ('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'tag.gpgSign=false', '-c', 'commit.gpgSign=false')
	(work / 'pyproject.toml').write_text('[project]\nversion = "1.0.1"\n')
	git(*ident, 'add', '.', cwd=work)
	git(*ident, 'commit', '-qm', 'one', cwd=work)
	git('remote', 'add', 'origin', origin.as_uri(), cwd=work)

	def run(event: str, release_tag: str = '') -> subprocess.CompletedProcess:
		env = {**os.environ, 'EVENT_NAME': event, 'RELEASE_TAG': release_tag}
		env['PATH'] = f'{Path(sys.executable).parent}{os.pathsep}{env["PATH"]}'  # python3 with tomllib, as on the runner (3.12)
		return subprocess.run(['bash', '-c', steps[check]['run']], cwd=work, env=env, capture_output=True, text=True, timeout=60)

	assert 'Tag 1.0.1 does not exist' in run('workflow_dispatch').stdout  # no tag anywhere
	git(*ident, 'tag', '-a', '-m', '1.0.1', '1.0.1', cwd=work)  # annotated: compared by the commit it points at
	git(*ident, 'commit', '-q', '--allow-empty', '-m', 'two', cwd=work)
	git('push', '-q', 'origin', 'HEAD:refs/heads/main', 'refs/tags/1.0.1', cwd=work)
	assert 'is not the checked-out commit' in run('workflow_dispatch').stdout  # tag on an older commit
	git('reset', '-q', '--hard', 'HEAD~1', cwd=work)
	assert run('workflow_dispatch').returncode == 0
	assert run('release', release_tag='1.0.1').returncode == 0
	assert 'does not match pyproject.toml version 1.0.1' in run('release', release_tag='1.0.0').stdout


def test_publish_uploads_with_attestations_through_the_trusted_publisher():
	"""PyPI's trusted publisher is publish.yml + environment `release` + OIDC: renaming either breaks the next release."""
	job = yaml.safe_load((WORKFLOWS / 'publish.yml').read_text())['jobs']['publish_to_pypi']
	assert job['environment'] == 'release' and job['permissions']['id-token'] == 'write'
	upload = next(step for step in job['steps'] if 'pypi-publish' in step.get('uses', ''))
	assert upload['uses'].startswith('pypa/gh-action-pypi-publish@') and upload.get('with', {}).get('attestations') is True
	assert not any('uv publish' in step.get('run', '') for step in job['steps'])


def test_every_workflow_pins_actions_to_a_commit_and_installs_uv_without_curl():
	"""A moved tag (`@v4`, `@beta`) or a replaced install.sh runs someone else's code in CI, with secrets in claude.yml."""
	files = sorted(WORKFLOWS.iterdir())
	assert files and all(f.suffix in ('.yml', '.yaml') for f in files), files
	for f in files:
		text = f.read_text()
		for ref in re.findall(r'uses:\s*(\S+)', text):
			assert ref.startswith('./') or re.fullmatch(r'[\w.-]+/[\w./-]+@[0-9a-f]{40}', ref), f'{f.name}: {ref}'
		assert not re.search(r'curl[^\n]*\|\s*(ba)?sh', text), f.name


def test_claude_gets_no_provider_keys_or_arbitrary_python_and_fetch_on_untrusted_text():
	"""Fable 1.0.0: five provider keys plus python/WebFetch tools on PR and issue text anyone can write."""
	steps = yaml.safe_load((WORKFLOWS / 'claude.yml').read_text())['jobs']['claude']['steps']
	step = next(s for s in steps if 'claude-code-action' in s.get('uses', ''))
	assert 'secrets.' not in step['with']['claude_env']
	tools = {line.strip() for line in step['with']['allowed_tools'].splitlines() if line.strip()}
	assert tools == set(json.loads(step['with']['settings'])['permissions']['allow'])
	for broad in ('WebFetch(*)', 'Bash(python:*)', 'Bash(uv:*)', 'Bash(.venv/bin/*:*)'):
		assert broad not in tools
