from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Type

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
	AIMessage,
	BaseMessage,
	HumanMessage,
)
from langchain_openai import ChatOpenAI

from browser_use.agent.message_manager.views import MessageHistory, MessageMetadata
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt
from browser_use.agent.views import ActionResult, AgentOutput, AgentStepInfo
from browser_use.browser.views import BrowserState

logger = logging.getLogger(__name__)


class MessageManager:
	def __init__(
		self,
		llm: BaseChatModel,
		task: str,
		action_descriptions: str,
		system_prompt_class: Type[SystemPrompt],
		max_input_tokens: int = 128000,
		estimated_tokens_per_character: int = 3,
		image_tokens: int = 800,
		include_attributes: list[str] = [],
		max_error_length: int = 400,
		max_actions_per_step: int = 10,
		tool_call_in_content: bool = True,
	):
		self.llm = llm
		self.system_prompt_class = system_prompt_class
		self.max_input_tokens = max_input_tokens
		self.history = MessageHistory()
		self.task = task
		self.action_descriptions = action_descriptions
		self.ESTIMATED_TOKENS_PER_CHARACTER = estimated_tokens_per_character
		self.IMG_TOKENS = image_tokens
		self.include_attributes = include_attributes
		self.max_error_length = max_error_length

		system_message = self.system_prompt_class(
			self.action_descriptions,
			current_date=datetime.now(),
			max_actions_per_step=max_actions_per_step,
		).get_system_message()

		self._add_message_with_tokens(system_message)
		self.system_prompt = system_message
		self.tool_call_in_content = tool_call_in_content
		tool_calls = [
			{
				'name': 'AgentOutput',
				'args': {
					'current_state': {
						'evaluation_previous_goal': 'Unknown - No previous actions to evaluate.',
						'memory': '',
						'next_goal': 'Obtain task from user',
					},
					'action': [],
				},
				'id': '',
				'type': 'tool_call',
			}
		]
		if self.tool_call_in_content:
			# openai throws error if tool_calls are not responded -> move to content
			example_tool_call = AIMessage(
				content=f'{tool_calls}',
				tool_calls=[],
			)
		else:
			example_tool_call = AIMessage(
				content=f'',
				tool_calls=tool_calls,
			)

		self._add_message_with_tokens(example_tool_call)

		task_message = HumanMessage(content=f'Your task is: {task}')
		self._add_message_with_tokens(task_message)

	def add_state_message(
		self,
		state: BrowserState,
		result: Optional[List[ActionResult]] = None,
		step_info: Optional[AgentStepInfo] = None,
	) -> None:
		"""Add browser state as human message"""

		# if keep in memory, add to directly to history and add state without result
		if result:
			for r in result:
				if r.include_in_memory:
					if r.extracted_content:
						msg = HumanMessage(content='Action result: ' + str(r.extracted_content))
						self._add_message_with_tokens(msg)
					if r.error:
						msg = HumanMessage(
							content='Action error: ' + str(r.error)[-self.max_error_length :]
						)
						self._add_message_with_tokens(msg)
					result = None  # if result in history, we dont want to add it again

		# otherwise add state message and result to next message (which will not stay in memory)
		state_message = AgentMessagePrompt(
			state,
			result,
			include_attributes=self.include_attributes,
			max_error_length=self.max_error_length,
			step_info=step_info,
		).get_user_message()
		self._add_message_with_tokens(state_message)

	def _remove_last_state_message(self) -> None:
		"""Remove last state message from history"""
		if len(self.history.messages) > 2 and isinstance(
			self.history.messages[-1].message, HumanMessage
		):
			self.history.remove_message()

	def add_model_output(self, model_output: AgentOutput) -> None:
		"""Add model output as AI message"""
		tool_calls = [
			{
				'name': 'AgentOutput',
				'args': model_output.model_dump(mode='json', exclude_unset=True),
				'id': '',
				'type': 'tool_call',
			}
		]
		if self.tool_call_in_content:
			msg = AIMessage(
				content=f'{tool_calls}',
				tool_calls=[],
			)
		else:
			msg = AIMessage(
				content='',
				tool_calls=tool_calls,
			)

		self._add_message_with_tokens(msg)

	def get_messages(self) -> List[BaseMessage]:
		"""Get current message list, potentially trimmed to max tokens"""
		self.cut_messages()
		return [m.message for m in self.history.messages]

	def cut_messages(self):
		"""Get current message list, potentially trimmed to max tokens"""
		diff = self.history.total_tokens - self.max_input_tokens
		if diff <= 0:
			return None

		msg = self.history.messages[-1]

		# if list with image remove image
		if isinstance(msg.message.content, list):
			text = ''
			for item in msg.message.content:
				if 'image_url' in item:
					msg.message.content.remove(item)
					diff -= self.IMG_TOKENS
					msg.metadata.input_tokens -= self.IMG_TOKENS
					self.history.total_tokens -= self.IMG_TOKENS
					logger.debug(
						f'Removed image with {self.IMG_TOKENS} tokens - total tokens now: {self.history.total_tokens}/{self.max_input_tokens}'
					)
				elif 'text' in item and isinstance(item, dict):
					text += item['text']
			msg.message.content = text
			self.history.messages[-1] = msg

		if diff <= 0:
			return None

		# if still over, remove text from state message proportionally to the number of tokens needed with buffer
		# Calculate the proportion of content to remove
		proportion_to_remove = diff / msg.metadata.input_tokens
		if proportion_to_remove > 0.99:
			raise ValueError(
				f'Max token limit reached - history is too long - reduce the system prompt or task less tasks or remove old messages. '
				f'proportion_to_remove: {proportion_to_remove}'
			)
		logger.debug(
			f'Removing {proportion_to_remove * 100:.2f}% of the last message  {proportion_to_remove * msg.metadata.input_tokens:.2f} / {msg.metadata.input_tokens:.2f} tokens)'
		)

		content = msg.message.content
		characters_to_remove = int(len(content) * proportion_to_remove)
		content = content[:-characters_to_remove]

		# remove tokens and old long message
		self.history.remove_message(index=-1)

		# new message with updated content
		msg = HumanMessage(content=content)
		self._add_message_with_tokens(msg)

		last_msg = self.history.messages[-1]

		logger.debug(
			f'Added message with {last_msg.metadata.input_tokens} tokens - total tokens now: {self.history.total_tokens}/{self.max_input_tokens} - total messages: {len(self.history.messages)}'
		)

	def _add_message_with_tokens(self, message: BaseMessage) -> None:
		"""Add message with token count metadata"""
		token_count = self._count_tokens(message)
		metadata = MessageMetadata(input_tokens=token_count)
		self.history.add_message(message, metadata)

	def _count_tokens(self, message: BaseMessage) -> int:
		"""Count tokens in a message using the model's tokenizer"""
		tokens = 0
		if isinstance(message.content, list):
			for item in message.content:
				if 'image_url' in item:
					tokens += self.IMG_TOKENS
				elif isinstance(item, dict) and 'text' in item:
					tokens += self._count_text_tokens(item['text'])
		else:
			tokens += self._count_text_tokens(message.content)
		return tokens

	def _count_text_tokens(self, text: str) -> int:
		"""Count tokens in a text string"""
		if isinstance(self.llm, (ChatOpenAI, ChatAnthropic)):
			try:
				tokens = self.llm.get_num_tokens(text)
			except Exception:
				tokens = (
					len(text) // self.ESTIMATED_TOKENS_PER_CHARACTER
				)  # Rough estimate if no tokenizer available
		else:
			tokens = (
				len(text) // self.ESTIMATED_TOKENS_PER_CHARACTER
			)  # Rough estimate if no tokenizer available
		return tokens
