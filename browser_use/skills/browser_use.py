"""Browser Use skill alias for Browser Harness"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

# Skill description agents see before deciding to open the skill. Name the hosted-browser use case so
# agents writing agent code (browser-use library, Playwright, Puppeteer, CDP) open it too.
SKILL_DESCRIPTION = (
	'Direct browser control via CDP for web interaction: automation, scraping, testing, screenshots, and site/app work. '
	'Also covers hosted cloud browsers for AI agents: the browser-use Python library (Browser()), '
	'Playwright, Puppeteer or any CDP client.'
)

# Browser Use-only frontmatter added while generating both checked-in SKILL.md copies.
# Keep this as the source of truth; scripts/sync_browser_harness_skill.py verifies the outputs.
OPENCLAW_METADATA_LINES = (
	'metadata:',
	'  {',
	'    "openclaw":',
	'      {',
	'        "requires": { "bins": ["browser-use"] },',
	'        "install":',
	'          [',
	'            {',
	'              "id": "uv",',
	'              "kind": "uv",',
	'              "package": "browser-use",',
	'              "bins": ["browser-use"],',
	'              "label": "Install Browser Use CLI (uv)",',
	'            },',
	'          ],',
	'      },',
	'  }',
)
# A Browser Use-only Gotchas line, added while generating both SKILL.md copies
FEEDBACK_LINE = (
	'- When browser-use itself fails (a helper that misbehaves, a confusing error, wrong docs), run `browser-use feedback '
	"'what happened'`: it goes straight to the Browser Use team. Never include secrets."
)

HARNESS_INSTALL_LINK = 'read https://github.com/browser-use/browser-harness/blob/main/install.md'  # the sentence's period follows
SETUP_HELP = 'run `browser-use --doctor` and follow its output and the error message'


def as_browser_use_skill(text: str) -> str:
	"""Expose the Browser Harness skill under the Browser Use skill identity."""
	if not text.startswith('---\n'):
		return text

	try:
		_, frontmatter, body = text.split('---\n', 2)
	except ValueError:
		return text

	lines = []
	saw_name = False
	saw_description = False
	for line in frontmatter.splitlines():
		if line.startswith('name:'):
			lines.append('name: browser-use')
			saw_name = True
		elif line.startswith('description:'):
			lines.append(f'description: "{SKILL_DESCRIPTION}"')
			saw_description = True
		else:
			lines.append(line)

	if not saw_name:
		lines.insert(0, 'name: browser-use')
	if not saw_description:
		lines.insert(1, f'description: "{SKILL_DESCRIPTION}"')
	if not any(line.startswith('homepage:') for line in lines):
		lines.append('homepage: https://browser-use.com')
	if not any(line.startswith('metadata:') for line in lines):
		lines.extend(OPENCLAW_METADATA_LINES)

	body = body.replace('# browser-harness', '# Browser Use', 1).replace('# Browser Harness', '# Browser Use', 1)
	# browser-harness's install.md installs and runs `browser-harness`, which `uv tool install browser-use` does not provide
	body = body.replace(HARNESS_INSTALL_LINK, SETUP_HELP)
	# Rebrand every mention except repo URLs (github.com/browser-use/browser-harness/...)
	body = re.sub(r'(?<!/)browser-harness', 'browser-use', body)
	body = body.replace('Browser Harness', 'Browser Use')
	if '\n## Gotchas\n\n' in body:
		body = body.replace('\n## Gotchas\n\n', f'\n## Gotchas\n\n{FEEDBACK_LINE}\n', 1)
	else:
		body = f'{body.rstrip()}\n\n{FEEDBACK_LINE}\n'
	frontmatter_text = '\n'.join(lines)
	return f'---\n{frontmatter_text}\n---\n{body}'


def skill_text() -> str:
	"""Return the canonical Browser Use skill."""
	skill_path = Path(__file__).resolve().parent / 'browser-use' / 'SKILL.md'
	if skill_path.exists():
		return skill_path.read_text(encoding='utf-8')

	try:
		text = resources.files('browser_harness').joinpath('SKILL.md').read_text(encoding='utf-8')
	except ModuleNotFoundError as exc:
		raise RuntimeError(
			'The Browser Use skill relies on the browser-harness package. Install browser-use again: uv tool install --force browser-use'
		) from exc
	return as_browser_use_skill(text)
