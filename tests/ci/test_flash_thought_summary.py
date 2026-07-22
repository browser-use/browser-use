from typing import cast

from browser_use import Agent
from browser_use.agent.prompts import SystemPrompt
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import UserMessage
from browser_use.llm.views import ChatInvokeCompletion


class ThoughtSummaryLLM:
	model = 'gemini-3.5-flash-lite'
	provider = 'google'
	name = model

	async def ainvoke(self, messages, output_format=None, **kwargs):
		assert output_format is not None
		completion = output_format.model_validate(
			{
				'memory': 'Verified 1995 and 2017; calculate the difference next.',
				'action': [{'done': {'text': '22 years', 'success': True}}],
			}
		)
		return ChatInvokeCompletion(
			completion=completion,
			thinking='The two dates are verified, so subtraction now completes the task.',
			usage=None,
		)


async def test_flash_mode_injects_native_thought_summary_into_memory():
	agent = Agent(
		task='Calculate the difference between two verified dates.',
		llm=cast(BaseChatModel, ThoughtSummaryLLM()),
		flash_mode=True,
		directly_open_url=False,
	)

	output = await agent.get_model_output([UserMessage(content='The dates are 1995 and 2017.')])

	assert output.memory == (
		'<thought_summary>\n'
		'The two dates are verified, so subtraction now completes the task.\n'
		'</thought_summary>\n'
		'<memory>\n'
		'Verified 1995 and 2017; calculate the difference next.\n'
		'</memory>'
	)


def test_flash_prompt_contains_thought_summary_and_evaluate_two_strike_rules():
	prompt = SystemPrompt(
		max_actions_per_step=4,
		use_thinking=False,
		flash_mode=True,
		model_name='gemini-3.5-flash-lite',
	).get_system_message()
	assert isinstance(prompt.content, str)

	assert 'Keep any exposed thought summary to at most 3 short sentences' in prompt.content
	assert 'After two consecutive failed `evaluate` calls' in prompt.content
	assert 'do not use `evaluate` again on the same page for the same goal' in prompt.content
