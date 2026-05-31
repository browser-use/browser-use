import tempfile

from browser_use.agent.views import ActionResult
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools
from browser_use.tools.views import (
	EvaluateAction,
	FindTextAction,
	ReadFileAction,
	ReplaceFileAction,
	WaitAction,
	WriteFileAction,
)


def test_builtin_tools_use_explicit_action_schemas():
	tools = Tools()

	expected_param_models = {
		'wait': WaitAction,
		'find_text': FindTextAction,
		'write_file': WriteFileAction,
		'replace_file': ReplaceFileAction,
		'read_file': ReadFileAction,
		'evaluate': EvaluateAction,
	}

	for action_name, param_model in expected_param_models.items():
		action = tools.registry.registry.actions[action_name]
		assert action.param_model is param_model


async def test_explicit_file_action_schemas_keep_direct_kwargs_compatibility():
	tools = Tools()

	with tempfile.TemporaryDirectory() as temp_dir:
		file_system = FileSystem(temp_dir)

		write_result = await tools.write_file(
			file_name='notes.txt',
			content='old text',
			file_system=file_system,
			trailing_newline=False,
		)
		assert isinstance(write_result, ActionResult)
		assert write_result.error is None

		replace_result = await tools.replace_file(
			file_name='notes.txt',
			old_str='old',
			new_str='new',
			file_system=file_system,
		)
		assert isinstance(replace_result, ActionResult)
		assert replace_result.error is None

		read_result = await tools.read_file(
			file_name='notes.txt',
			available_file_paths=[],
			file_system=file_system,
		)
		assert isinstance(read_result, ActionResult)
		assert read_result.extracted_content is not None
		assert 'new text' in read_result.extracted_content


async def test_direct_tool_calls_do_not_build_dynamic_action_model(monkeypatch):
	tools = Tools()

	async def fail_act(*args, **kwargs):
		raise AssertionError('direct tool calls should not route through Tools.act or a dynamic ActionModel')

	monkeypatch.setattr(tools, 'act', fail_act)

	result = await tools.wait(seconds=0)

	assert isinstance(result, ActionResult)
	assert result.error is None
	assert result.extracted_content == 'Waited for 0 seconds'
