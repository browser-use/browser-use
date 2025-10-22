"""Tests for done() call validation in code-use mode."""

import pytest

from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.code_use.namespace import create_namespace
from browser_use.filesystem.file_system import FileSystem


@pytest.fixture
async def browser_session_with_namespace():
	"""Create a browser session and namespace for testing."""
	browser_profile = BrowserProfile(headless=True, disable_security=True)
	browser_session = BrowserSession(browser_profile=browser_profile)
	await browser_session.start()

	import tempfile

	with tempfile.TemporaryDirectory() as tmp_dir:
		file_system = FileSystem(base_dir=tmp_dir)
		namespace = create_namespace(browser_session=browser_session, file_system=file_system)

		yield namespace, file_system

	await browser_session.stop()


async def test_done_in_if_block_raises_error(browser_session_with_namespace):
	"""Test that done() inside if block raises RuntimeError."""
	namespace, _ = browser_session_with_namespace

	# Simulate code with done() in if block
	test_code = """
if True:
	await done("test", success=True)
"""

	namespace['_current_cell_code'] = test_code
	namespace['_all_code_blocks'] = {'python_0': test_code}

	# Try to call done() - should raise RuntimeError
	with pytest.raises(RuntimeError) as exc_info:
		done_func = namespace['done']
		await done_func(text='test', success=True)

	assert 'done() should be called individually' in str(exc_info.value)


async def test_done_in_else_block_raises_error(browser_session_with_namespace):
	"""Test that done() inside else block raises RuntimeError."""
	namespace, _ = browser_session_with_namespace

	# Simulate code with done() in else block
	test_code = """
if False:
	pass
else:
	await done("test", success=False)
"""

	namespace['_current_cell_code'] = test_code
	namespace['_all_code_blocks'] = {'python_0': test_code}

	# Try to call done() - should raise RuntimeError
	with pytest.raises(RuntimeError) as exc_info:
		done_func = namespace['done']
		await done_func(text='test', success=False)

	assert 'done() should be called individually' in str(exc_info.value)


async def test_done_in_elif_block_raises_error(browser_session_with_namespace):
	"""Test that done() inside elif block raises RuntimeError."""
	namespace, _ = browser_session_with_namespace

	# Simulate code with done() in elif block
	test_code = """
if False:
	pass
elif True:
	await done("test", success=True)
"""

	namespace['_current_cell_code'] = test_code
	namespace['_all_code_blocks'] = {'python_0': test_code}

	# Try to call done() - should raise RuntimeError
	with pytest.raises(RuntimeError) as exc_info:
		done_func = namespace['done']
		await done_func(text='test', success=True)

	assert 'done() should be called individually' in str(exc_info.value)


async def test_done_standalone_works(browser_session_with_namespace):
	"""Test that done() works normally when not in conditional."""
	namespace, _ = browser_session_with_namespace

	# Simulate standalone done() call
	test_code = """
result = "task complete"
await done(result, success=True)
"""

	namespace['_current_cell_code'] = test_code
	namespace['_all_code_blocks'] = {'python_0': test_code}

	# Should not raise any error
	done_func = namespace['done']
	await done_func(text='task complete', success=True)

	# Verify task was marked as done
	assert namespace.get('_task_done') is True
	assert namespace.get('_task_success') is True


async def test_done_after_if_block_works(browser_session_with_namespace):
	"""Test that done() works when called after an if block (not inside it)."""
	namespace, _ = browser_session_with_namespace

	# Simulate done() after if block
	test_code = """
if some_condition:
	result = "success"
else:
	result = "failure"
	
await done(result, success=True)
"""

	namespace['_current_cell_code'] = test_code
	namespace['_all_code_blocks'] = {'python_0': test_code}

	# Should not raise any error
	done_func = namespace['done']
	await done_func(text='result', success=True)

	# Verify task was marked as done
	assert namespace.get('_task_done') is True
