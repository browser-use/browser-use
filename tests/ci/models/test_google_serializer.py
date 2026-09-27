"""Regression tests for GoogleMessageSerializer's handling of system messages."""

from google.genai.types import Content, ContentListUnion, Part

from browser_use.llm.google.serializer import GoogleMessageSerializer
from browser_use.llm.messages import AssistantMessage, SystemMessage, UserMessage


def _role_and_text(contents: ContentListUnion) -> list[tuple[str | None, str | None]]:
	"""Flatten serialized contents into (role, first part text) pairs for assertions."""
	assert isinstance(contents, list)

	pairs: list[tuple[str | None, str | None]] = []
	for content in contents:
		assert isinstance(content, Content)
		parts = content.parts
		assert parts is not None
		assert isinstance(parts[0], Part)
		pairs.append((content.role, parts[0].text))

	return pairs


def test_single_system_message_becomes_the_system_instruction():
	"""The common case must keep returning the system text verbatim."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[SystemMessage(content='Follow the base system rule.'), UserMessage(content='Continue the task.')]
	)

	assert system_instruction == 'Follow the base system rule.'
	assert _role_and_text(contents) == [('user', 'Continue the task.')]


def test_all_system_messages_reach_the_system_instruction():
	"""Every SystemMessage must survive, in order, instead of the last one winning."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the base system rule.'),
			SystemMessage(content='Also follow the additional system rule.'),
			UserMessage(content='Continue the task.'),
		]
	)

	assert system_instruction == 'Follow the base system rule.\n\nAlso follow the additional system rule.'
	assert _role_and_text(contents) == [('user', 'Continue the task.')]


def test_system_text_is_prepended_even_when_an_assistant_message_comes_first():
	"""include_system_in_user must target the first *user* message, not the first message."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[
			SystemMessage(content='Follow the system rule.'),
			AssistantMessage(content='Earlier assistant turn.'),
			UserMessage(content='Continue the task.'),
		],
		include_system_in_user=True,
	)

	assert system_instruction is None
	assert _role_and_text(contents) == [
		('model', 'Earlier assistant turn.'),
		('user', 'Follow the system rule.\n\nContinue the task.'),
	]


def test_system_text_falls_back_to_the_instruction_when_there_is_no_user_message():
	"""With nothing to merge into, the system text must not be silently dropped."""
	_, system_instruction = GoogleMessageSerializer.serialize_messages(
		[SystemMessage(content='Follow the system rule.'), AssistantMessage(content='Earlier assistant turn.')],
		include_system_in_user=True,
	)

	assert system_instruction == 'Follow the system rule.'


def test_system_message_after_the_first_user_turn_is_not_merged_into_a_later_one():
	"""The merge target is the *first* user message; once it is gone, fall back to the instruction."""
	contents, system_instruction = GoogleMessageSerializer.serialize_messages(
		[
			UserMessage(content='First user turn.'),
			SystemMessage(content='Follow the system rule.'),
			UserMessage(content='Second user turn.'),
		],
		include_system_in_user=True,
	)

	assert system_instruction == 'Follow the system rule.'
	assert _role_and_text(contents) == [('user', 'First user turn.'), ('user', 'Second user turn.')]
