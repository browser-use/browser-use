import pytest
from pydantic import ValidationError

from browser_use.agent.prompts import (
	SYSTEM_PROMPT_TEMPLATE_SPECS,
	SystemPrompt,
	SystemPromptRenderer,
	SystemPromptTemplateProfile,
	SystemPromptTemplateSource,
)


@pytest.mark.parametrize(
	('profile', 'filename'),
	[
		(SystemPromptTemplateProfile(is_browser_use_model=True, flash_mode=True), 'system_prompt_browser_use_flash.md'),
		(SystemPromptTemplateProfile(is_browser_use_model=True, use_thinking=True), 'system_prompt_browser_use.md'),
		(SystemPromptTemplateProfile(is_browser_use_model=True, use_thinking=False), 'system_prompt_browser_use_no_thinking.md'),
		(SystemPromptTemplateProfile(is_anthropic_4_5=True, flash_mode=True), 'system_prompt_anthropic_flash.md'),
		(SystemPromptTemplateProfile(is_anthropic=True, flash_mode=True), 'system_prompt_flash_anthropic.md'),
		(SystemPromptTemplateProfile(flash_mode=True), 'system_prompt_flash.md'),
		(SystemPromptTemplateProfile(use_thinking=True), 'system_prompt.md'),
		(SystemPromptTemplateProfile(use_thinking=False), 'system_prompt_no_thinking.md'),
	],
)
def test_system_prompt_profile_selects_template(profile: SystemPromptTemplateProfile, filename: str) -> None:
	assert profile.template_filename() == filename


def test_system_prompt_profile_validates_action_count() -> None:
	with pytest.raises(ValidationError):
		SystemPromptTemplateProfile(max_actions_per_step=0)


def test_system_prompt_renderer_formats_selected_template() -> None:
	renderer = SystemPromptRenderer()
	rendered = renderer.render(SystemPromptTemplateProfile(max_actions_per_step=7, flash_mode=True))

	assert 'maximum of 7 actions per step' in rendered
	assert '{max_actions}' not in rendered


def test_system_prompt_renderer_uses_inline_specs_for_small_variants() -> None:
	inline_template_names = {
		'system_prompt_browser_use.md',
		'system_prompt_browser_use_no_thinking.md',
		'system_prompt_browser_use_flash.md',
		'system_prompt_flash.md',
		'system_prompt_flash_anthropic.md',
	}

	for template_name in inline_template_names:
		template_spec = SYSTEM_PROMPT_TEMPLATE_SPECS[template_name]
		assert template_spec.source == SystemPromptTemplateSource.INLINE
		assert template_spec.inline_template


def test_system_prompt_uses_model_capability_prompt_profile() -> None:
	prompt = SystemPrompt(
		max_actions_per_step=7,
		flash_mode=True,
		is_anthropic=True,
		is_anthropic_4_5=False,
		model_name='claude-sonnet-current',
	)

	assert prompt.profile.template_filename() == 'system_prompt_flash_anthropic.md'
	assert 'maximum of 7 actions per step' in prompt.get_system_message().content


def test_system_prompt_can_override_for_native_tool_calling() -> None:
	prompt = SystemPrompt(use_native_tool_calls=True)

	content = prompt.get_system_message().content
	assert isinstance(content, str)
	assert '<native_tool_calling>' in content
	assert 'Do not output JSON action objects' in content
	assert 'AgentOutput tool' not in content
	assert 'You must ALWAYS respond with a valid JSON' not in content
