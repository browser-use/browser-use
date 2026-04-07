import os
import tempfile
import uuid

import pytest

from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.views import MessageManagerState
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm import SystemMessage


def _make_message_manager(**kwargs):
	base_tmp = tempfile.gettempdir()
	file_system_path = os.path.join(base_tmp, str(uuid.uuid4()))
	defaults = {
		'task': 't',
		'system_message': SystemMessage(content='s'),
		'state': MessageManagerState(),
		'file_system': FileSystem(file_system_path),
	}
	defaults.update(kwargs)
	return MessageManager(**defaults)


def test_message_manager_max_history_items_none_ok():
	_make_message_manager(max_history_items=None)


def test_message_manager_max_history_items_above_five_ok():
	_make_message_manager(max_history_items=6)


@pytest.mark.parametrize('invalid', [0, 1, 5, -1])
def test_message_manager_max_history_items_invalid_raises(invalid):
	with pytest.raises(ValueError, match='max_history_items must be None or greater than 5'):
		_make_message_manager(max_history_items=invalid)
