"""Release workflows: which events build and push Docker images. Evaluates the job's `if:` expression in Python."""

import re
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
