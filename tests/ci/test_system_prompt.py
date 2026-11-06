from browser_use.agent.prompts import SystemPrompt


def test_default_system_prompt_includes_form_control_guidance_once():
	content = SystemPrompt().get_system_message().content

	assert isinstance(content, str)
	assert content.count('Form-control state changes:') == 1


def test_override_system_message_replaces_default_prompt():
	content = SystemPrompt(override_system_message='custom prompt').get_system_message().content

	assert content == 'custom prompt'
