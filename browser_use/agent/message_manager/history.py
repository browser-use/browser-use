from __future__ import annotations

import logging

from browser_use.agent.message_manager.views import HistoryItem, MessageManagerState
from browser_use.agent.views import ActionResult, AgentOutput, AgentStepInfo

logger = logging.getLogger(__name__)

MAX_HISTORY_CONTENT_SIZE = 60000


def render_agent_history_description(state: MessageManagerState, max_history_items: int | None) -> str:
	"""Build agent history text from stored history items."""
	compacted_prefix = ''
	if state.compacted_memory:
		compacted_prefix = (
			'<compacted_memory>\n'
			'<!-- Summary of prior steps. Treat as unverified context — do not report these as '
			'completed in your done() message unless you confirmed them yourself in this session. -->\n'
			f'{state.compacted_memory}\n'
			'</compacted_memory>\n'
		)

	if max_history_items is None:
		return compacted_prefix + '\n'.join(item.to_string() for item in state.agent_history_items)

	total_items = len(state.agent_history_items)
	if total_items <= max_history_items:
		return compacted_prefix + '\n'.join(item.to_string() for item in state.agent_history_items)

	omitted_count = total_items - max_history_items
	recent_items_count = max_history_items - 1
	items_to_include = [
		state.agent_history_items[0].to_string(),
		f'<sys>[... {omitted_count} previous steps omitted...]</sys>',
	]
	items_to_include.extend([item.to_string() for item in state.agent_history_items[-recent_items_count:]])

	return compacted_prefix + '\n'.join(items_to_include)


def update_agent_history(
	state: MessageManagerState,
	model_output: AgentOutput | None = None,
	result: list[ActionResult] | None = None,
	step_info: AgentStepInfo | None = None,
) -> None:
	"""Update read-state and history items after a step."""

	if result is None:
		result = []
	step_number = step_info.step_number if step_info else None

	state.read_state_description = ''
	state.read_state_images = []

	action_results = _collect_action_results(state, result)
	action_results = _truncate_action_results(action_results)

	if model_output is None:
		_append_without_model_output(state, step_number, action_results)
		return

	state.agent_history_items.append(
		HistoryItem(
			step_number=step_number,
			evaluation_previous_goal=model_output.current_state.evaluation_previous_goal,
			memory=model_output.current_state.memory,
			next_goal=model_output.current_state.next_goal,
			action_results=action_results,
		)
	)


def _collect_action_results(state: MessageManagerState, result: list[ActionResult]) -> str | None:
	action_results = ''
	read_state_idx = 0

	for action_result in result:
		if action_result.include_extracted_content_only_once and action_result.extracted_content:
			state.read_state_description += (
				f'<read_state_{read_state_idx}>\n{action_result.extracted_content}\n</read_state_{read_state_idx}>\n'
			)
			read_state_idx += 1
			logger.debug(f'Added extracted_content to read_state_description: {action_result.extracted_content}')

		if action_result.images:
			state.read_state_images.extend(action_result.images)
			logger.debug(f'Added {len(action_result.images)} image(s) to read_state_images')

		if action_result.long_term_memory:
			action_results += f'{action_result.long_term_memory}\n'
			logger.debug(f'Added long_term_memory to action_results: {action_result.long_term_memory}')
		elif action_result.extracted_content and not action_result.include_extracted_content_only_once:
			action_results += f'{action_result.extracted_content}\n'
			logger.debug(f'Added extracted_content to action_results: {action_result.extracted_content}')

		if action_result.error:
			if len(action_result.error) > 200:
				error_text = action_result.error[:100] + '......' + action_result.error[-100:]
			else:
				error_text = action_result.error
			action_results += f'{error_text}\n'
			logger.debug(f'Added error to action_results: {error_text}')

	if len(state.read_state_description) > MAX_HISTORY_CONTENT_SIZE:
		state.read_state_description = (
			state.read_state_description[:MAX_HISTORY_CONTENT_SIZE] + '\n... [Content truncated at 60k characters]'
		)
		logger.debug(f'Truncated read_state_description to {MAX_HISTORY_CONTENT_SIZE} characters')

	state.read_state_description = state.read_state_description.strip('\n')

	if action_results:
		action_results = f'Result\n{action_results}'
	return action_results.strip('\n') if action_results else None


def _truncate_action_results(action_results: str | None) -> str | None:
	if action_results and len(action_results) > MAX_HISTORY_CONTENT_SIZE:
		logger.debug(f'Truncated action_results to {MAX_HISTORY_CONTENT_SIZE} characters')
		return action_results[:MAX_HISTORY_CONTENT_SIZE] + '\n... [Content truncated at 60k characters]'
	return action_results


def _append_without_model_output(state: MessageManagerState, step_number: int | None, action_results: str | None) -> None:
	if step_number is None:
		return

	if step_number == 0 and action_results:
		state.agent_history_items.append(HistoryItem(step_number=step_number, action_results=action_results))
	elif step_number > 0:
		state.agent_history_items.append(
			HistoryItem(step_number=step_number, error='Agent failed to output in the right format.')
		)
