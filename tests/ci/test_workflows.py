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
