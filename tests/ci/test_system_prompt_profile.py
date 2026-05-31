import pytest
from pydantic import ValidationError

from browser_use.agent.prompts import SystemPrompt, SystemPromptTemplateProfile


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
