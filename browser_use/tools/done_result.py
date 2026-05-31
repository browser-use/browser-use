from __future__ import annotations

import json
import logging
from typing import Any

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.views import DoneAction, StructuredOutputAction

logger = logging.getLogger(__name__)


def build_done_result(
	params: DoneAction | StructuredOutputAction[Any],
	*,
	file_system: FileSystem,
	browser_session: BrowserSession | None = None,
	display_files_in_done_text: bool = True,
) -> ActionResult:
	"""Build the terminal result for legacy and native done paths."""
	if isinstance(params, DoneAction):
		return build_text_done_result(
			params,
			file_system=file_system,
			display_files_in_done_text=display_files_in_done_text,
		)

	if browser_session is None:
		raise ValueError('Structured done result requires browser_session to resolve downloaded files.')

	return build_structured_done_result(params, file_system=file_system, browser_session=browser_session)


def build_text_done_result(
	params: DoneAction,
	*,
	file_system: FileSystem,
	display_files_in_done_text: bool = True,
) -> ActionResult:
	user_message = params.text

	len_text = len(params.text)
	len_max_memory = 100
	memory = f'Task completed: {params.success} - {params.text[:len_max_memory]}'
	if len_text > len_max_memory:
		memory += f' - {len_text - len_max_memory} more characters'

	attachments = []
	if params.files_to_display:
		if display_files_in_done_text:
			file_msg = ''
			for file_name in params.files_to_display:
				file_content = file_system.display_file(file_name)
				if file_content:
					file_msg += f'\n\n{file_name}:\n{file_content}'
					attachments.append(file_name)
			if file_msg:
				user_message += '\n\nAttachments:'
				user_message += file_msg
			else:
				logger.warning('Agent wanted to display files but none were found')
		else:
			for file_name in params.files_to_display:
				file_content = file_system.display_file(file_name)
				if file_content:
					attachments.append(file_name)

	resolved_attachments = [str(file_system.get_dir() / file_name) for file_name in attachments]

	return ActionResult(
		is_done=True,
		success=params.success,
		extracted_content=user_message,
		long_term_memory=memory,
		attachments=resolved_attachments,
	)


def build_structured_done_result(
	params: StructuredOutputAction[Any],
	*,
	file_system: FileSystem,
	browser_session: BrowserSession,
) -> ActionResult:
	# Exclude success from the output JSON.
	# Use mode='json' to properly serialize enums at all nesting levels.
	output_dict = params.data.model_dump(mode='json')

	attachments: list[str] = []

	if params.files_to_display:
		for file_name in params.files_to_display:
			file_content = file_system.display_file(file_name)
			if file_content:
				attachments.append(str(file_system.get_dir() / file_name))

	session_downloads = browser_session.downloaded_files
	if session_downloads:
		existing = set(attachments)
		for file_path in session_downloads:
			if file_path not in existing:
				attachments.append(file_path)

	return ActionResult(
		is_done=True,
		success=params.success,
		extracted_content=json.dumps(output_dict, ensure_ascii=False),
		long_term_memory=f'Task completed. Success Status: {params.success}',
		attachments=attachments,
	)
