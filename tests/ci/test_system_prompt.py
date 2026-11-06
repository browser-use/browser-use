import pytest

from browser_use.agent.prompts import SystemPrompt


@pytest.mark.parametrize(
	'prompt_options',
	[
		{},
		{'is_browser_use_model': True},
		{'is_browser_use_model': True, 'flash_mode': True},
		{'is_browser_use_model': True, 'use_thinking': False},
		{'is_anthropic': True, 'flash_mode': True},
	],
)
def test_system_prompt_templates_include_form_control_guidance_once(prompt_options):
	content = SystemPrompt(**prompt_options).get_system_message().content

	assert isinstance(content, str)
	assert content.count('Form-control state changes:') == 1


def test_override_system_message_replaces_default_prompt():
	content = SystemPrompt(override_system_message='custom prompt').get_system_message().content

	assert content == 'custom prompt'
