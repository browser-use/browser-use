"""Keep runtime payload tags out of the static system prompt templates.

The per-step user message wraps live data in tags like `<user_request>`, `<agent_history>`,
`<agent_state>`, `<browser_state>` and `<read_state>`. Some system prompt templates used to
document those payloads by re-opening the same tags with example content inside.

Two problems with that. A reader (human or model) sees `<user_request>...</user_request>` in
the system prompt and reasonably concludes that is where the request lives at runtime, when
it actually arrives in a user turn. And it couples the static template to the per-step data
shape, so if real per-step content ever leaks into one of those blocks the system prompt
stops being byte-identical between calls and implicit prompt caching dies silently.

Documentation blocks use a `_details` suffix instead (`<browser_state_details>`), which the
templates already did in places. This test keeps it that way.
"""

import importlib.resources
import re

import pytest

# Tags the agent emits around live data in the per-step user message.
# See AgentMessagePrompt.get_user_message in browser_use/agent/prompts.py.
RUNTIME_TAGS = (
	'user_request',
	'agent_history',
	'agent_state',
	'browser_state',
	'read_state',
	'page_specific_actions',
	'step_info',
	'file_system',
	'todo_contents',
	# Conditional blocks nested inside <agent_state> / <browser_state>.
	'plan',
	'sensitive_data',
	'available_file_paths',
	'browser_state_error',
	'page_info',
	'page_stats',
)

# Deliberately not listed: <input>, <instructions> and <output>. Those name sections of a
# prompt rather than wrapping a per-step payload, and the templates use them as headings.


# The two large templates still document payload shapes under the runtime names. Narrowing
# that is a behaviour change that needs its own eval, so they are excluded here rather than
# silently rewritten. The flash templates are held to the rule.
TEMPLATES_UNDER_RULE = (
	'system_prompt_flash.md',
	'system_prompt_flash_anthropic.md',
	'system_prompt_anthropic_flash.md',
	'system_prompt_browser_use.md',
	'system_prompt_browser_use_flash.md',
	'system_prompt_browser_use_no_thinking.md',
)


def _read_template(filename: str) -> str:
	return (importlib.resources.files('browser_use.agent.system_prompts') / filename).read_text(encoding='utf-8')


@pytest.mark.parametrize('filename', TEMPLATES_UNDER_RULE)
def test_template_does_not_open_runtime_payload_tags(filename: str):
	"""A template may reference a runtime tag in prose, but must not open a block with it."""
	content = _read_template(filename)
	offenders = [tag for tag in RUNTIME_TAGS if re.search(rf'^</?{tag}>', content, re.MULTILINE)]
	assert not offenders, (
		f'{filename} opens runtime payload tags {offenders} as document blocks. '
		f'Use a `_details` suffix (e.g. <{offenders[0]}_details>) so the static template '
		f'is not coupled to the per-step data shape.'
	)
