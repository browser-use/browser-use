"""0.x API compatibility: what is kept, what raises (before any browser or billing starts). No browser needed."""

import logging
import re
import sys

import pytest
from conftest import script
from pydantic import BaseModel

from browser_use import ActionResult, Agent, AgentHistoryList, Browser, ChatAnthropic, ChatGoogle, Controller, Tools
from browser_use.agent.loop import Session, build_agent, run
from browser_use.repl import Repl
from browser_use.tools import RemovedField


@pytest.fixture
def no_browser(monkeypatch):
	async def fail(self):
		raise AssertionError('browser started')

	monkeypatch.setattr(Browser, 'start', fail)


REMOVED = (
	r'was removed in browser-use 1\.0\. Open an issue at https://github\.com/browser-use/browser-use/issues if you need it\.'
)
GUIDE = r' Migration guide: https://github\.com/browser-use/browser-use/blob/main/MIGRATING\.md$'


@pytest.mark.parametrize(
	'kwarg',
	[
		'sample_images',  # vision input
		'initial_actions',
		'register_new_step_callback',  # step callbacks
		'register_done_callback',
		'register_should_stop_callback',
		'generate_gif',
		'judge_llm',  # judge
		'ground_truth',
		'enable_planning',  # planner
		'planner_llm',
		'planning_replan_on_stall',
	],
)
def test_removed_0x_agent_kwarg_raises_one_error_naming_it(kwarg, no_browser):
	with pytest.raises(TypeError, match=rf'^Agent\({kwarg}=\.\.\.\) {REMOVED}'):
		Agent('t', script()[0], **{kwarg: True})


def test_unknown_agent_kwarg_is_not_called_removed(no_browser):
	with pytest.raises(TypeError, match=r'^Agent\(some_new_kwarg=\.\.\.\) is not a browser-use 1\.0 option'):
		Agent('t', script()[0], some_new_kwarg=True)


def test_removed_alternative_is_named(no_browser):
	with pytest.raises(TypeError, match=rf'In 1\.0: extend_system_message=\.\.\. \(the core prompt is fixed\)\.{GUIDE}'):
		Agent('t', script()[0], override_system_message='x')


def test_agent_highlight_elements_names_highlight_actions(no_browser, caplog, monkeypatch):
	"""C7: the cloud dashboard snippet's Agent(highlight_elements=...) raised a generic 'not a 1.0 option'. 0.x Agent took
	it in **kwargs and ignored it: 1.0 ignores it too, with a warning naming highlight_actions."""
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	with caplog.at_level('WARNING', logger='browser_use'):
		Agent('t', script()[0], highlight_elements=True)
	assert 'Agent(highlight_elements=...) is ignored in browser-use 1.0: Agent(highlight_actions=True | False)' in caplog.text


def test_available_file_paths_error_says_there_is_no_allowlist(no_browser):
	"""C30: the agent can upload any file the user can read; the error must not imply the workspace is a boundary."""
	with pytest.raises(
		TypeError, match=rf'In 1\.0: there is no file allowlist: .* any file you can read\. .* container or VM\.{GUIDE}'
	):
		Agent('t', script()[0], available_file_paths=['/tmp/a.pdf'])


def test_0x_tuning_knobs_warn_and_construct(no_browser, caplog, monkeypatch):
	"""use_vision=False alone is on 31% of 0.x devices: a script that only tuned the old loop keeps running."""
	knobs = dict(use_vision=False, max_actions_per_step=3, flash_mode=True, use_judge=False, use_thinking=True, max_failures=5)
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	with caplog.at_level('WARNING', logger='browser_use'):
		Agent('t', script()[0], **knobs)
	warnings = [r.getMessage() for r in caplog.records if 'is ignored in browser-use 1.0' in r.getMessage()]
	assert [w.split('=')[0] for w in warnings] == [f'Agent({k}' for k in knobs if k != 'use_vision']  # False is kept
	assert not Agent('t', script()[0], use_vision=False).use_vision and Agent('t', script()[0], use_vision='auto').use_vision
	assert "Agent(use_thinking=...) is ignored in browser-use 1.0: reasoning='low' | 'medium' | 'high'." in warnings
	with pytest.raises(TypeError, match=r'^Agent\(initial_actions=\.\.\.\)'):  # a real removed feature still raises
		Agent('t', script()[0], use_vision=False, initial_actions=[])


def test_agent_max_steps_points_to_run(no_browser):
	with pytest.raises(
		TypeError, match=r'^Agent\(max_steps=\.\.\.\) is not an option: pass it to agent\.run\(max_steps=\.\.\.\)\.$'
	):
		Agent('t', script()[0], max_steps=5)


async def test_step_hooks_on_run_raise(no_browser):
	agent = Agent('t', script()[0], browser=Browser(local=True))
	for hook in ('on_step_start', 'on_step_end'):
		with pytest.raises(TypeError, match=rf'^Agent\.run\({hook}=\.\.\.\) {REMOVED} In 1\.0: each step logs one INFO line'):
			await agent.run(**{hook: lambda a: None})
	with pytest.raises(TypeError, match=rf'^Agent\.run_sync\(on_step_end=\.\.\.\) {REMOVED}'):
		agent.run_sync(on_step_end=lambda a: None)


@pytest.mark.parametrize(
	'method', ['pause', 'resume', 'stop', 'step', 'multi_act', 'rerun_history', 'load_and_rerun', 'save_history']
)
def test_removed_agent_methods_raise_one_error(method, no_browser):
	agent = Agent('t', script()[0])
	with pytest.raises(AttributeError, match=rf'^Agent\.{method}\(\) {REMOVED}'):
		getattr(agent, method)
	assert not hasattr(agent, method)
	with pytest.raises(AttributeError, match='no attribute'):
		agent.definitely_not_a_method


def test_stop_error_gives_the_cancel_recipe(no_browser):
	"""C56: agent.stop() / state.should_stop end ~13k 0.x runs a week; the error must show how to cancel, not just say so."""
	agent = Agent('t', script()[0])
	for attr in ('stop', 'pause', 'state'):
		with pytest.raises(AttributeError, match=r'asyncio\.create_task\(agent\.run\(\)\).*call_soon_threadsafe\(task\.cancel\)'):
			getattr(agent, attr)


def test_short_or_list_shaped_sensitive_data_is_explained(no_browser, caplog):
	"""M23 and a low: a short value warns (redacted only where it stands alone); a list of tuples gave a raw dict error."""
	import logging

	logging.getLogger('browser_use').propagate = True
	try:
		Agent('t', script()[0], browser=Browser(local=True), sensitive_data={'pin': '42', 'pw': 'long-enough'})
	finally:
		logging.getLogger('browser_use').propagate = False
	assert 'sensitive_data pin: values under 4 characters' in caplog.text and 'pw' not in caplog.text.split('sensitive_data')[1]
	with pytest.raises(TypeError, match='sensitive_data must be a dict'):
		Agent('t', script()[0], browser=Browser(local=True), sensitive_data=[('pw', 'x', 'https://a.com')])


def test_0x_environment_variables_1_0_ignores_say_so(no_browser, monkeypatch, caplog):
	"""M38: DEFAULT_LLM (runs billed bu-fast), BROWSER_USE_HEADLESS and log level 'result' were silently ignored. Low:
	ANONYMIZED_TELEMETRY='' left telemetry on."""
	import logging

	from browser_use.config import CONFIG
	from browser_use.logging_config import setup_logging

	monkeypatch.setenv('DEFAULT_LLM', 'openai_gpt_4o')
	monkeypatch.setenv('BROWSER_USE_HEADLESS', 'false')
	monkeypatch.setenv('BROWSER_USE_LLM_URL', 'https://llm.staging.example.test/v1')  # rr-legacy 6: sent to production
	monkeypatch.setenv('BROWSER_USE_DEBUG_LOG_FILE', 'debug.log')  # review: 0.x wrote it; 1.0 wrote nothing, silently
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)
	Agent('t', browser=Browser(local=True))
	logging.getLogger('browser_use').addHandler(caplog.handler)  # setup_logging turns propagation off
	try:
		setup_logging('result')
	finally:
		logging.getLogger('browser_use').removeHandler(caplog.handler)
	assert 'DEFAULT_LLM is set' in caplog.text and 'BROWSER_USE_HEADLESS is set' in caplog.text
	assert 'BROWSER_USE_LLM_URL is set but browser-use 1.0 does not read it' in caplog.text
	assert "BROWSER_USE_LOGGING_LEVEL='result' is not a level" in caplog.text
	assert 'BROWSER_USE_DEBUG_LOG_FILE is set but browser-use 1.0 does not read it' in caplog.text
	setup_logging('info')
	for value, on in (('', False), ('false', False), ('nope', False), ('true', True), ('1', True)):
		monkeypatch.setenv('ANONYMIZED_TELEMETRY', value)
		assert CONFIG.ANONYMIZED_TELEMETRY is on, value


def test_domain_scoped_sensitive_data_is_accepted_and_bad_shapes_raise(no_browser):
	Agent('t', script()[0], sensitive_data={'https://example.com': {'pw': 'x'}, 'pin': '1'})
	with pytest.raises(TypeError, match='must be a string'):
		Agent('t', script()[0], sensitive_data={'pw': 123})


def test_dotenv_in_the_working_directory_supplies_the_key(tmp_path):
	"""Roast C16: 0.x loaded .env on import; 1.0 resolved the key before anything read .env ('missing key')."""
	import os
	import subprocess
	import sys

	(tmp_path / '.env').write_text('BROWSER_USE_API_KEY=fake-dotenv-key\n', encoding='utf-8')
	env = {k: v for k, v in os.environ.items() if k != 'BROWSER_USE_API_KEY'}
	env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / 'cfg'))
	code = "from browser_use import Agent\nAgent('t')._build()\nprint('resolved')"
	r = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
	assert r.stdout.strip() == 'resolved', r.stderr[-2000:]


def test_removed_classes_raise_with_pointer():
	import browser_use

	for name in ['BrowserSession', 'BrowserProfile', 'ChatGroq', 'DomService']:
		with pytest.raises(ImportError, match=rf'^browser_use\.{name} {REMOVED}'):
			getattr(browser_use, name)
	# C19: each provider class names its own replacement (Azure was 16.7% of external 0.x runs and got a groq example)
	for name, instead in [
		('ChatAzureOpenAI', "llm='azure:<deployment>' with AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and OPENAI_API_VERSION"),
		('ChatAWSBedrock', "llm='bedrock:<model id>' (pip install 'pydantic-ai-slim[bedrock]'"),
		('ChatDeepSeek', "llm='deepseek:deepseek-chat' with DEEPSEEK_API_KEY"),
		('ChatGroq', "llm='groq:<model>' (pip install 'pydantic-ai-slim[groq]'"),
		('ChatOpenRouter', "llm='openrouter:"),
		('ChatOllama', "ChatOpenAI('<model>', base_url='http://localhost:11434/v1'"),
	]:
		with pytest.raises(ImportError, match=rf'{REMOVED} In 1\.0: {re.escape(instead)}'):
			exec(f'from browser_use import {name}')
		with pytest.raises(ImportError, match=rf'^browser_use\.llm\.{name} {REMOVED} In 1\.0: '):
			exec(f'from browser_use.llm import {name}')  # the common 0.x import path
	with pytest.raises(ImportError, match='cannot import name'):
		exec('from browser_use.llm import NotAThing')


@pytest.mark.parametrize(
	'path, instead',
	[
		('browser_use.browser.events', "logging.getLogger('browser_use')"),  # the 0.x hooks docs, verbatim
		('browser_use.browser.session', 'from browser_use import Browser'),
		('browser_use.browser.watchdogs.dom_watchdog', 'from browser_use import Browser'),
		('browser_use.mcp.client', '@tools.action'),
		('browser_use.controller.service', 'from browser_use import Tools'),
		('browser_use.tools.service', 'from browser_use import Tools'),  # browser_use.tools is a module in 1.0
		('browser_use.tools.registry.views', 'from browser_use import Tools'),
		('browser_use.llm.openai.chat', 'from browser_use import ChatOpenAI'),
		('browser_use.llm.google.chat', 'from browser_use import ChatGoogle'),
		('browser_use.llm.aws.chat_bedrock', "llm='bedrock:<model id>'"),
		('browser_use.llm.azure.chat', "llm='azure:<deployment>'"),
		('browser_use.llm.base', 'pydantic_ai.Agent(llm.pydantic_model())'),
		('browser_use.llm.messages', 'pydantic_ai.Agent(llm.pydantic_model())'),
		('browser_use.observability', 'pydantic_ai.Agent.instrument_all()'),
		('browser_use.dom.service', 'Python and raw CDP'),
		('browser_use.actor.page', 'Python and raw CDP'),
		('browser_use.agent.message_manager.service', 'result.messages'),
		('browser_use.tokens.service', 'result.cost_usd'),
		('browser_use.filesystem.file_system', 'Agent(workspace=...)'),
		('browser_use.sandbox', ''),
		('browser_use.browser.context', 'from browser_use import Browser'),  # 0.1.x-0.5.x
		('browser_use.agent.memory.service', 'compacted'),
		('browser_use.code_use.service', 'writes Python itself'),  # 0.8.x-0.11.x
		('browser_use.skill_cli.main', 'browser-harness'),  # 0.11.x-0.12.x
	],
)
def test_0x_module_paths_name_their_replacement(path, instead):
	"""rr-legacy: 157 of 178 0.13.14 module paths (and older 0.x ones) gave a bare ModuleNotFoundError (the 0.x hooks docs,
	MCPClient, every deep import); each names its 1.0 replacement and links MIGRATING.md. Still an ImportError, for
	`except ImportError` fallbacks."""
	import importlib

	with pytest.raises(ModuleNotFoundError, match=rf'^browser_use\.[\w.]+ {REMOVED}.*{GUIDE}') as raised:
		importlib.import_module(path)
	assert instead in str(raised.value) and path.startswith(raised.value.name or '-')
	with pytest.raises(ModuleNotFoundError, match=r"^No module named 'browser_use\.not_a_0x_module'$"):
		importlib.import_module('browser_use.not_a_0x_module')  # a path 0.x never had is left to Python


@pytest.mark.parametrize(
	'package, module',
	[
		('browser_use', 'dom'),
		('browser_use', 'controller'),
		('browser_use.browser', 'session'),
		('browser_use.llm', 'openai'),
		('browser_use.agent', 'message_manager'),
		('browser_use.tools', 'registry'),  # browser_use.tools is a module in 1.0
		('browser_use.mcp', 'client'),
	],
)
def test_0x_submodules_imported_from_their_package_name_their_replacement(package, module):
	"""`from browser_use.browser import session`: Python's from-import asks the package for the name first and swallows
	the import hook's ModuleNotFoundError for a missing submodule, so it raised a bare "cannot import name 'session'"."""
	import subprocess

	with pytest.raises(ModuleNotFoundError, match=rf'^{re.escape(package)}\.{module} {REMOVED}.*{GUIDE}'):
		exec(f'from {package} import {module}')
	# real 1.0 modules under a 0.x prefix the hook knows (browser_use.tools, browser_use.llm) still import, in a fresh
	# interpreter where no package has them as attributes yet
	code = 'from browser_use import tools, llm, agent, skills; from browser_use.mcp import cli_mcp; from browser_use.skills import install'
	r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60)
	assert r.returncode == 0, r.stderr


def test_0x_names_and_members_name_their_replacement():
	"""rr-legacy: ProxySettings, AgentOutput/AgentState, BaseChatModel, Browser.list_chrome_profiles() and llm.ainvoke()
	gave a bare ImportError / AttributeError."""
	import browser_use.utils
	from browser_use import ChatOpenAI

	for module, name, instead in [
		('browser_use.browser', 'ProxySettings', 'cloud_proxy_country_code'),
		('browser_use.agent.views', 'AgentOutput', 'result.messages'),
		('browser_use.agent.views', 'AgentState', 'AgentHistoryList'),
		('browser_use.llm', 'BaseChatModel', 'pydantic_ai.models.Model'),
		('browser_use.llm', 'UserMessage', 'pydantic_ai.Agent(llm.pydantic_model())'),
		('browser_use.mcp', 'MCPClient', '@tools.action'),
		('browser_use.utils', 'time_execution_async', 'internal helper'),
		('browser_use', 'BrowserContextConfig', 'Browser(...)'),  # 0.1.x-0.5.x
		('browser_use.browser.browser', 'BrowserContextConfig', 'Browser(...)'),
		('browser_use', 'CodeAgent', 'writes Python itself'),
		('browser_use.cli', 'BrowserUseApp', 'browser-harness'),
	]:
		with pytest.raises(ImportError, match=rf'^{re.escape(module)}\.{name} {REMOVED} In 1\.0: .*{GUIDE}') as raised:
			exec(f'from {module} import {name}')
		assert instead in str(raised.value), name
	for fn, match in [
		(
			lambda: ChatOpenAI('gpt-4.1-mini', api_key='x').ainvoke,
			r'^ChatOpenAI\.ainvoke .*pydantic_ai\.Agent\(llm\.pydantic_model\(\)\)',
		),
		(lambda: Browser.list_chrome_profiles(), r"^Browser\.list_chrome_profiles\(\) .*Browser\('chrome', profile='Work'\)"),
	]:
		with pytest.raises(AttributeError, match=rf'{match}.*{GUIDE}'):
			fn()
	assert not hasattr(browser_use.utils, 'not_a_0x_name') and not hasattr(ChatOpenAI('m', api_key='x'), 'nope')


def test_0x_names_from_every_tag_name_their_replacement():
	"""Live migration survey (ast over all 152 0.x tags, 20 popular GitHub files): 0.1-0.13 Agent arguments and
	methods, BrowserSession/BrowserContext members, Controller and @action arguments and the llm.<model> instances gave
	a bare AttributeError or "not a browser-use 1.0 option" with no answer; ActionResult(images=...) went to the model
	as base64 JSON text."""
	from browser_use import llm

	usage = {'input': 1, 'output': 1, 'cache_read': 0, 'cache_write': 0, 'requests': 1}
	result = AgentHistoryList('completed', 't', 't', 1, 1.0, usage, 0.0, None, None, [], True)
	agent = Agent('t', script()[0], browser=Browser(local=True))
	tools = Tools()
	cases = [
		(lambda: Agent('t', script()[0], validate_output=True), TypeError, r'Agent\(validate_output=\.\.\.\) .*result\.success'),
		(lambda: Agent('t', script()[0], browser_context=object()), TypeError, r'In 1\.0: pass a Browser'),
		(lambda: Agent('t', script()[0], tool_calling_method='auto'), TypeError, r'Agent\(tool_calling_method=\.\.\.\)'),
		(lambda: agent.logger, AttributeError, r"Agent\.logger\(\) .*getLogger\('browser_use'\)"),
		(lambda: agent.get_model_output, AttributeError, r'Agent\.get_model_output\(\) .*Python cells'),
		(lambda: Browser(local=True).new_context, AttributeError, r'Browser\.new_context .*raw CDP'),
		(lambda: Browser().get_or_create_cdp_session, AttributeError, r'Browser\.get_or_create_cdp_session '),
		(lambda: result.load_from_dict, AttributeError, r'AgentHistoryList\.load_from_dict '),
		(lambda: Controller(headless=True), TypeError, r'Tools\(headless=\.\.\.\) .*Browser\(\.\.\.\)'),
		(lambda: tools.action('d', terminates_sequence=True), TypeError, r'@tools\.action\(terminates_sequence='),
		(lambda: tools.action('d', page_filter=len), TypeError, r'allowed_domains'),
		(lambda: tools.exclude_action, AttributeError, r'Tools\.exclude_action\(\) .*no built-in actions'),
		(lambda: ActionResult(images=[{'name': 'a.png', 'data': 'iVBORw0KGgo'}]), RemovedField, r'ActionResult\(images=\.\.\.\)'),
		(lambda: llm.openai_gpt_4o, ImportError, r"llm\.openai_gpt_4o .*ChatOpenAI\('gpt-4o'\)"),
		(lambda: exec('from browser_use.llm import google_gemini_2_5_flash'), ImportError, r'ChatGoogle'),
		(lambda: exec('from browser_use.llm import get_llm_by_name'), ImportError, r"llm='openai:gpt-4o'"),
		# the settings= answer for temperature failed live: Anthropic 400s it on Claude 4.x, after the browser started
		(lambda: ChatAnthropic('claude-sonnet-4-0', temperature=0.0), TypeError, r"In 1\.0: delete it: Anthropic's API rejects"),
		(lambda: ChatGoogle('gemini-flash-latest', temperature=1.0), TypeError, r"GoogleModel\('gemini-\.\.\.', settings="),
	]
	for fn, error, match in cases:
		with pytest.raises(error, match=match) as raised:
			fn()
		assert 'was removed in browser-use 1.0' in str(raised.value), match
	assert not hasattr(llm, 'not_a_model') and not hasattr(Browser(local=True), 'not_a_0x_member')


def test_browser_session_alias_and_controller_alias():
	browser = Browser(local=True)
	assert Agent('t', script()[0], browser_session=browser).browser is browser
	assert Controller is Tools


def result(status='completed', output='done', error=None):
	return AgentHistoryList(status, str(output), output, 3, 1.5, {}, None, None, error, [])


def test_printing_a_result_leaves_out_the_transcript():
	"""M41: print(result) dumped about 565 KB, screenshots' JPEG bytes included."""
	from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart

	shot = BinaryContent(b'\xff\xd8' + b'x' * 200_000, media_type='image/jpeg')
	messages = [ModelRequest(parts=[ToolReturnPart('python', ['ok', shot])])]
	usage = {'input': 1, 'output': 1, 'cache_read': 0, 'cache_write': 0, 'requests': 1}
	r = AgentHistoryList('completed', 'answer', 'answer', 1, 1.0, usage, 0.01, None, None, messages, True)
	assert len(repr(r)) < 1000 and "text='answer'" in repr(r) and '<1 messages>' in str(r)


def test_0x_api_shapes_raise_the_removed_error(no_browser):
	"""M36: these 0.x shapes gave bare TypeError / AttributeError / ImportError instead of the removed error naming the
	1.0 alternative."""
	from browser_use import ChatBrowserUse, ChatOpenAI

	usage = {'input': 1, 'output': 1, 'cache_read': 0, 'cache_write': 0, 'requests': 1}
	result = AgentHistoryList('completed', 't', 't', 1, 1.0, usage, 0.0, None, None, [], True)
	agent = Agent('t', script()[0], browser=Browser(local=True))
	cases = [
		(lambda: ChatAnthropic('claude-haiku-5-5', temperature=0.0), TypeError, r'ChatAnthropic\(temperature=\.\.\.\)'),
		(lambda: ChatGoogle('gemini-3.5-flash', thinking_budget=0), TypeError, r'ChatGoogle\(thinking_budget='),
		(lambda: ChatOpenAI('gpt-6-luna', seed=1), TypeError, r'ChatOpenAI\(seed='),
		(lambda: ChatBrowserUse(fast=True), TypeError, r"In 1\.0: model='bu-ultrafast'"),
		(lambda: Tools(exclude_actions=['x']), TypeError, r'Tools\(exclude_actions='),
		(lambda: Controller(output_model=int), TypeError, r'In 1\.0: Agent\(output_model_schema=\.\.\.\)'),
		(lambda: Browser(local=True).stop_session, AttributeError, r'Browser\.stop_session .*await browser\.stop\(\)'),
		(lambda: Browser(local=True).get_current_page, AttributeError, r'Browser\.get_current_page '),
		(lambda: Browser.from_system_chrome(), AttributeError, r"Browser\('chrome'\)"),
		(lambda: agent.state, AttributeError, r'Agent\.state '),
		(lambda: agent.history, AttributeError, r'Agent\.history '),
		(lambda: agent.browser_session, AttributeError, r'In 1\.0: agent\.browser\.'),
		(lambda: result.usage.total_cost, AttributeError, r'In 1\.0: result\.cost_usd\.'),
		(lambda: len(result), TypeError, r'len\(AgentHistoryList\) .*number_of_steps'),
		(lambda: result.model_dump(), AttributeError, r'AgentHistoryList\.model_dump '),
		(lambda: result.total_input_tokens(), AttributeError, r"usage\['input'\]"),
		(
			lambda: __import__('browser_use.browser', fromlist=['BrowserSession']).BrowserSession,
			ImportError,
			r'Browser\(\.\.\.\)',
		),
		# C63: the 0.1.x import path gave a raw ImportError naming site-packages; Browser(config=) a generic message
		(lambda: exec('from browser_use.browser.browser import BrowserConfig'), ImportError, r'BrowserConfig was removed'),
		(lambda: Browser(config=object()), TypeError, r'^Browser\(config=\.\.\.\) was removed'),
	]
	for fn, error, match in cases:
		with pytest.raises(error, match=match) as raised:
			fn()
		assert 'was removed in browser-use 1.0' in str(raised.value), match
	assert result and result.usage == usage and result.usage['input'] == 1  # still a plain dict to read
	with pytest.raises(AttributeError, match="no attribute 'nope'"):
		Browser(local=True).nope


def test_version_is_the_installed_package_version():
	"""C63: browser_use.__version__ raised AttributeError; only importlib.metadata knew it."""
	from importlib.metadata import version

	import browser_use

	assert browser_use.__version__ == version('browser-use')


def test_version_of_a_checkout_that_is_not_installed_is_unknown(monkeypatch):
	"""Review: PackageNotFoundError (an ImportError) escaped __version__, so hasattr(browser_use, '__version__') raised."""
	from importlib.metadata import PackageNotFoundError

	import browser_use
	from browser_use import utils

	def missing(name):
		raise PackageNotFoundError(name)

	monkeypatch.setattr(utils, 'version', missing)
	utils.get_browser_use_version.cache_clear()
	try:
		assert browser_use.__version__ == 'unknown' and hasattr(browser_use, '__version__')
	finally:
		utils.get_browser_use_version.cache_clear()


def test_docs_say_the_default_workspace_is_kept():
	"""M17 (documented, not changed): default workspaces are never deleted (3,772 in $TMPDIR, with page text and
	screenshots); the docs said only "a temp dir"."""
	from pathlib import Path

	migrating = (Path(__file__).resolve().parents[2] / 'MIGRATING.md').read_text(encoding='utf-8')
	assert 'kept after the run: it holds page text, screenshots and cell output' in migrating


def test_result_keeps_common_0x_methods():
	r = result()
	assert (r.final_result(), r.is_done(), r.is_successful(), r.errors(), r.has_errors()) == ('done', True, None, [], False)
	# a result built without a verdict is not a success (it defaulted to True): MIGRATING.md, a missing verdict is None
	r.success = True
	assert r.is_successful() is True
	assert (r.total_duration_seconds(), r.number_of_steps(), r.structured_output) == (1.5, 3, None)
	failed = result('error', '', 'boom')
	assert (failed.final_result(), failed.is_done(), failed.is_successful(), failed.errors()) == (None, False, None, ['boom'])


@pytest.mark.parametrize('name', ['urls', 'screenshots', 'action_names', 'model_thoughts', 'history', 'judgement', 'is_judged'])
def test_removed_result_methods_raise_attribute_error(name):
	with pytest.raises(AttributeError, match=rf'^AgentHistoryList\.{name} {REMOVED} In 1\.0: '):
		getattr(result(), name)
	with pytest.raises(AttributeError):
		result().definitely_not_a_method


def test_removed_result_methods_work_with_hasattr_and_getattr_default():
	"""C40: hasattr()/getattr(default) only swallow AttributeError; serializers duck-type on hasattr(obj, 'model_dump')."""
	r = result()
	assert not hasattr(r, 'urls')
	assert getattr(r, 'model_dump', None) is None


def test_removed_result_classmethod_raises_on_the_class():
	"""0.x AgentHistoryList.load_from_file(path) was a classmethod: called on the class, not an instance."""
	with pytest.raises(AttributeError, match=rf'^AgentHistoryList\.load_from_file {REMOVED} In 1\.0: '):
		AgentHistoryList.load_from_file('history.json')


def test_tools_plain_function_and_param_model():
	tools = Tools()

	@tools.action('Price of a product')
	def get_price(sku: str) -> str:
		return f'{sku}: 9.99'

	class Order(BaseModel):
		sku: str
		qty: int

	@tools.registry.action('Place an order', param_model=Order)
	async def place_order(params):
		return ActionResult(extracted_content=f'{params.qty}x {params.sku}')

	assert [t.name for t in tools.functions] == ['get_price', 'place_order']
	assert get_price('a') == 'a: 9.99'  # the decorator returns the function unchanged


def test_registering_an_action_name_again_replaces_it_as_in_0x():
	"""0.x kept actions in a dict: running a notebook cell with @tools.action again replaced the action. 1.0 kept both,
	and the next run raised pydantic-ai's 'UserError: Tool name conflicts with existing tool'."""
	tools = Tools()
	for version in ('old', 'new'):

		@tools.action('Price of a product')
		def get_price(sku: str, v=version) -> str:
			return f'{v} {sku}'

	assert [t.name for t in tools.functions] == ['get_price']
	assert tools.functions[0].function('a') == 'new a'
	build_agent('test', tools=tools.functions)  # no name conflict


@pytest.mark.parametrize('param', ['browser_session', 'page_extraction_llm', 'file_system'])
def test_tools_injected_params_raise(param):
	tools = Tools()
	with pytest.raises(TypeError, match=rf'^Injecting {param} into @tools\.action act\(\) {REMOVED}'):
		exec(f'@tools.action("x")\nasync def act(text: str, {param}=None): pass', {'tools': tools})


async def test_tools_params_0x_never_injected_come_from_the_model(tmp_path):
	"""0.13.14 passed `page` and `browser` through from the model; 1.0 refused to register such actions."""
	from conftest import script
	from test_compaction import FakeRepl

	from browser_use.agent.loop import Session, build_agent, run

	tools, got = Tools(), []

	@tools.action('Search the catalog')
	def search_catalog(query: str, page: int = 1, browser: str = 'any') -> str:
		got.append((query, page, browser))
		return 'found'

	model, _ = script(
		('search_catalog', {'query': 'shoes', 'page': 3, 'browser': 'firefox'}), ('finish', {'result': 'ok', 'success': True})
	)
	result = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=FakeRepl(tmp_path)), 'function:x')
	assert result.status == 'completed' and got == [('shoes', 3, 'firefox')]


def test_tools_domain_filters_and_reserved_names_raise():
	tools = Tools()
	for name in ('domains', 'allowed_domains'):
		with pytest.raises(TypeError, match=rf'^@tools\.action\({name}=\.\.\.\) {REMOVED} In 1\.0: Browser\(allowed_domains'):
			tools.action('x', **{name: ['*.example.com']})
	with pytest.raises(ValueError, match='built-in'):

		@tools.action('x')
		def finish(result: str):
			return result


def test_tool_names_providers_reject_raise_at_registration():
	"""M12: a lambda ('<lambda>') registered fine and the provider 400ed the first request. Low: @tools.action without
	parentheses silently registered nothing."""
	tools = Tools()
	with pytest.raises(ValueError, match='not a valid tool name'):
		tools.action('x')(lambda q: q)
	with pytest.raises(ValueError, match='not a valid tool name'):

		@tools.action('x')
		def a_name_much_longer_than_the_sixty_four_characters_that_providers_accept_for_tools(q: str) -> str:
			return q

	with pytest.raises(TypeError, match='with parentheses'):

		@tools.action
		def nop(x: int) -> int:
			return x

	assert tools.functions == []


async def test_removed_action_result_fields_raise_and_end_the_run(tmp_path):
	"""M39: ActionResult(is_done=True, success=...) was silently accepted (extra='allow'): the run went on as if the
	action had ended it. Now the removed error, ending the run so the developer sees it (not the model)."""
	for field, value in (('is_done', True), ('attachments', ['a.pdf']), ('images', [{'name': 'a', 'data': 'x'}])):
		with pytest.raises(TypeError, match=rf'^ActionResult\({field}=\.\.\.\) {REMOVED}'):
			ActionResult(extracted_content='x', **{field: value})
	assert ActionResult(extracted_content='x', note='extra fields still pass').note == 'extra fields still pass'
	tools = Tools()
	ns: dict = {'ActionResult': ActionResult}
	exec("def done():\n\treturn ActionResult(is_done=True, extracted_content='all done')", ns)
	tools.action('Done')(ns['done'])  # no source to read at registration: refused when the action returns it
	model, _ = script(('done', {}))
	r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert r.status == 'error' and 'ActionResult(is_done=...) was removed in browser-use 1.0' in (r.error or '')


async def test_0x_action_result_defaults_never_end_the_run_and_done_actions_are_refused_when_registered(tmp_path):
	"""Live migration (0.13.14 examples/custom-functions/notification.py; GitHub: ActionResult(is_done=False,
	success=True, ...) in 0.x tool code): spelled-out 0.x defaults ended a billed run with the removed error, and a done
	action (return ActionResult(is_done=True, ...)) failed only once it ran, after the browser had started."""
	assert ActionResult(extracted_content='x', is_done=False, success=False, attachments=None, images=[]).model_dump(
		exclude_none=True
	) == {'extracted_content': 'x'}
	tools = Tools()

	@tools.action('Click')
	def click(index: int) -> ActionResult:
		return ActionResult(is_done=False, success=True, extracted_content=f'clicked {index}')

	model, _ = script(('click', {'index': 3}), ('finish', {'result': 'ok', 'success': True}))
	r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.status, r.text) == ('completed', 'ok'), r.error
	for source in (
		"return ActionResult(is_done=True, extracted_content='Email sent!')",
		'return ActionResult(is_done=True, success=params.success, extracted_content=params.text)',
		"return ActionResult(extracted_content='saved', attachments=['report.pdf'])",
	):
		ns: dict = {'ActionResult': ActionResult}
		exec(f'def done(params=None):\n\t{source}', ns)
		with pytest.raises(
			TypeError, match=rf'ActionResult\((is_done|attachments)=\.\.\.\) in @tools\.action done\(\) {REMOVED}'
		):
			Tools().action('Done')(_with_source(ns['done'], f'def done(params=None):\n\t{source}'))


def test_an_action_that_spells_out_empty_0x_defaults_registers():
	"""ActionResult(images=[], attachments=[]) runs (an empty list is the 0.x default spelled out, dropped at runtime), so
	registering the action that returns it must not refuse it before the run."""
	for source in (
		"return ActionResult(extracted_content='x', images=[])",
		"return ActionResult(extracted_content='x', attachments=[], images=())",
		"return ActionResult(extracted_content='x', attachments=None, is_done=False, success=True)",
	):
		ns: dict = {'ActionResult': ActionResult}
		exec(f'def act():\n\t{source}', ns)
		tools = Tools()
		tools.action('Act')(_with_source(ns['act'], f'def act():\n\t{source}'))
		assert [t.name for t in tools.functions] == ['act']
		assert ns['act']().extracted_content == 'x'


def _with_source(fn, source: str):
	"""exec'd functions have no file: give inspect.getsource what a module function has."""
	import linecache

	name = f'<test-action-{id(fn)}>'
	linecache.cache[name] = (len(source), None, [line + '\n' for line in source.splitlines()], name)
	fn.__code__ = fn.__code__.replace(co_filename=name)
	return fn


def test_action_result_include_extracted_content_only_once_says_it_is_ignored(monkeypatch, caplog):
	"""rr-legacy 4: ActionResult(include_extracted_content_only_once=True) (the 0.x way to keep a big extract out of
	later steps) was accepted without a word, and the content stayed in context."""
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	result = ActionResult(extracted_content='x', long_term_memory='short', include_extracted_content_only_once=True)
	assert 'ActionResult(include_extracted_content_only_once=...) is ignored in browser-use 1.0' in caplog.text
	assert result.model_dump(exclude_none=True) == {'extracted_content': 'x', 'long_term_memory': 'short'}


async def test_action_result_include_in_memory_warns_and_the_run_goes_on(tmp_path, monkeypatch, caplog):
	"""rr-legacy L08 / error contract: a 0.x action returning ActionResult(include_in_memory=True) (examples/custom-functions
	style) ended the run with status 'error' after the browser had started and was billed. 1.0 keeps every result in the
	conversation, so the field is ignored with a warning and the model gets the result."""
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	tools = Tools()

	@tools.action('Stock level of a product')
	def stock_level(product: str) -> ActionResult:
		return ActionResult(extracted_content=f'{product}: 7 in stock', include_in_memory=True)

	model, seen = script(('stock_level', {'product': 'Red Mug'}), ('finish', {'result': '7', 'success': True}))
	r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert r.status == 'completed' and r.final_result() == '7', r.error
	assert 'Red Mug: 7 in stock' in str(seen[1][-1])
	assert 'ActionResult(include_in_memory=...) is ignored in browser-use 1.0' in caplog.text


async def test_custom_action_is_a_model_tool(tmp_path):
	tools = Tools()

	@tools.action('Price of a product')
	def get_price(sku: str) -> ActionResult:
		return ActionResult(extracted_content=f'{sku} costs 9.99')

	model, seen = script(('get_price', {'sku': 'A1'}), ('finish', {'success': True, 'result': 'done'}))
	session = Session(repl=Repl(tmp_path))
	r = await run(build_agent(model, tools=tools.functions), 'task', session, 'm')
	assert r.output == 'done'
	assert 'A1 costs 9.99' in str(seen[1][-1])


async def test_custom_tool_results_never_show_a_secret_to_the_model(tmp_path):
	"""Roast r2-1: a custom action returning a registered secret (ActionResult, nested model, plain str, retry
	message) reached the model in plaintext; 0.x filtered action results."""
	from pydantic_ai import ModelRetry

	secret = 'hunter2-Zq9'
	tools = Tools()

	class Account(BaseModel):
		user: str
		password: str

	@tools.action('Look up the account')
	def account() -> ActionResult:
		return ActionResult(extracted_content=f'pw={secret}', account=Account(user='me', password=secret))

	@tools.action('Read a note')
	def note() -> list:
		return [{'text': f'the password is {secret}'}]

	@tools.action('Check')
	def check() -> str:
		raise ModelRetry(f'wrong password {secret}')

	model, seen = script(('account', {}), ('note', {}), ('check', {}), ('finish', {'success': True, 'result': 'done'}))
	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	r = await run(build_agent(model, tools=tools.functions), 'task', session, 'm')
	assert r.output == 'done'
	assert secret not in str(seen) and secret not in str(r.messages)
	assert 'pw=<secret:pw>' in str(seen[1][-1]) and 'wrong password <secret:pw>' in str(seen[3][-1])


@pytest.mark.parametrize('tool', ['finish', 'finish_from_repl'])
async def test_finish_can_report_a_failed_task(tool, tmp_path):
	"""Roast C9: 'Unable to log in. Access denied.' came back with is_successful() == True; 0.x had success=False."""
	args = {'result': 'Unable to log in. Access denied.'} if tool == 'finish' else {'expression': "'Access denied.'"}
	model, _ = script((tool, {**args, 'success': False}))
	r = await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.is_done(), r.is_successful(), r.success) == (True, False, False)
	model, _ = script(('finish', {'success': True, 'result': 'done'}))
	assert (await run(build_agent(model), 'task', Session(repl=Repl(tmp_path)), 'm')).is_successful() is True


@pytest.mark.parametrize(
	'call,expected',
	[({'result': 'The book does not exist.'}, None), ({'result': 'The book does not exist.', 'success': False}, False)],
)
async def test_finish_success_verdict_is_optional(tmp_path, call, expected):
	"""agent-llm F1: a finish without a verdict must never read as success. The verdict is optional (a required one made
	the model give up early on long tasks: ablation 1107), so an omitted verdict is None, not True. It is described, so
	the model gives it."""
	from pydantic_ai.messages import ModelResponse, ToolCallPart
	from pydantic_ai.models.function import FunctionModel

	seen = []

	def fn(messages, info):
		seen.append({t.name: t.parameters_json_schema for t in info.output_tools})
		return ModelResponse(parts=[ToolCallPart('finish', call)])

	r = await run(build_agent(FunctionModel(fn)), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert len(seen) == 1 and not any('success' in schema.get('required', []) for schema in seen[0].values()), seen
	# C10: an undescribed verdict was left out on most runs (None on 15/21 correct runs); the description makes it given
	assert all('description' in seen[0][t]['properties']['success'] for t in ('finish', 'finish_from_repl')), seen
	# C11: a verdict not tied to evidence let a strict schema (ISBN pattern) get values from memory with success=True
	assert all('from memory' in seen[0][t]['properties']['success']['description'] for t in ('finish', 'finish_from_repl'))
	assert (r.status, r.output, r.is_successful()) == ('completed', 'The book does not exist.', expected)


@pytest.mark.parametrize(
	'budget',
	[
		{'max_steps': 0},
		{'max_steps': -1},
		{'max_steps': 2.5},
		{'timeout': 0},
		{'timeout': -5},
	],
)
async def test_impossible_budgets_raise_before_any_browser(budget, no_browser):
	"""agent-llm: run(max_steps=0) and run(timeout<=0) started (and billed) a browser, then ended in an error."""
	with pytest.raises(ValueError, match='max_steps' if 'max_steps' in budget else 'timeout'):
		await Agent('t', script()[0], browser=Browser(local=True)).run(**budget)


async def test_structured_final_result_is_the_models_json(tmp_path):
	"""Roast C10: final_result() was '"title=\'x\' points=3"' (str() of the model) instead of 0.x model_dump_json()."""

	class Story(BaseModel):
		title: str
		points: int

	model, _ = script(('finish', {'success': True, 'result': {'title': 'x', 'points': 3}}))
	r = await run(build_agent(model, output_type=Story), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert r.final_result() == Story(title='x', points=3).model_dump_json()
	assert r.structured_output == Story(title='x', points=3)


@pytest.mark.parametrize('schema', ['literal', 'strenum'])
async def test_structured_output_of_a_str_valued_schema(schema, fake_browser, tmp_path):
	"""M8: structured_output was None for Literal and StrEnum schemas: it only checked isinstance(output, str)."""
	from enum import StrEnum
	from typing import Literal

	class Answer(StrEnum):
		yes = 'yes'
		no = 'no'

	output_type = Literal['yes', 'no'] if schema == 'literal' else Answer
	model, _ = script(('finish', {'success': True, 'result': 'yes'}))
	agent = Agent('t', model, browser=Browser(local=True), output_model_schema=output_type, workspace=tmp_path)
	r = await agent.run()
	assert r.structured_output == 'yes' and r.final_result() == 'yes'
	model, _ = script(('finish', {'success': True, 'result': 'plain'}))
	assert (await Agent('t', model, browser=Browser(local=True), workspace=tmp_path).run()).structured_output is None


async def test_output_model_schema_that_is_not_a_type_raises_at_agent(fake_browser, tmp_path):
	"""C42: a JSON-schema dict passed Agent() and crashed run() with a raw pydantic SchemaError. StructuredDict, which
	the error names, delivers a dict."""
	from pydantic_ai import StructuredDict

	schema = {'type': 'object', 'properties': {'titles': {'type': 'array', 'items': {'type': 'string'}}}}
	for bad in (schema, 3, 'x'):
		with pytest.raises(TypeError, match=r'output_model_schema must be a type .*StructuredDict'):
			Agent('t', script()[0], browser=Browser(local=True), output_model_schema=bad)
	model, _ = script(('finish', {'success': True, 'result': {'titles': ['a', 'b']}}))
	agent = Agent('t', model, browser=Browser(local=True), output_model_schema=StructuredDict(schema), workspace=tmp_path)
	assert (await agent.run()).structured_output == {'titles': ['a', 'b']}


async def test_a_tools_own_timeout_is_an_error_not_the_run_budget(tmp_path):
	"""Fable: socket.timeout is TimeoutError; it was reported as status='timeout', error=None with budget unused. The
	model now gets it as the tool's error (H2) and the run goes on."""
	tools = Tools()

	@tools.action('Fetch a URL')
	def fetch(url: str) -> str:
		raise TimeoutError('timed out')

	model, seen = script(('fetch', {'url': 'https://x.test'}), ('finish', {'success': False, 'result': 'fetch timed out'}))
	r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert (r.status, r.error, r.output) == ('completed', None, 'fetch timed out')
	assert 'TimeoutError: timed out' in str(seen[1][-1])


async def test_a_custom_tool_that_raises_returns_the_error_to_the_model(tmp_path):
	"""H2: a custom tool raising an ordinary exception ended the whole run; 0.x returned ActionResult(error=...) to the
	model. Sync and async tools, with and without sensitive_data."""
	tools = Tools()

	@tools.action('Look up a price')
	def price(sku: str) -> str:
		raise KeyError(f'no such sku {sku}')

	@tools.action('Look up stock')
	async def stock(sku: str) -> str:
		raise ValueError('stock service down hunter2-Zq9')

	for secrets in (None, {'pw': 'hunter2-Zq9'}):
		model, seen = script(
			('price', {'sku': 'A1'}), ('stock', {'sku': 'A1'}), ('finish', {'success': False, 'result': 'unknown'})
		)
		r = await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path, secrets=secrets)), 'm')
		assert (r.status, r.output) == ('completed', 'unknown'), r.error
		assert "KeyError: 'no such sku A1'" in str(seen[1][-1])
		assert 'ValueError: stock service down' in str(seen[2][-1])
		if secrets:
			assert 'hunter2-Zq9' not in str(seen) and '<secret:pw>' in str(seen[2][-1])


@pytest.mark.parametrize(
	'llm', [lambda: ChatAnthropic('claude-opus-4-1', api_key='k'), lambda: ChatGoogle('gemini-2.5-pro', api_key='k')]
)
async def test_cost_is_priced_with_the_models_provider(llm, fake_browser, tmp_path, monkeypatch):
	"""Fable: the bare model name was priced as OpenAI, so cost_usd was None for every Anthropic/Google model."""
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	import browser_use.agent.service as service
	from browser_use.agent.loop import usage_and_cost

	refs = []

	async def fake_run(agent, task, session, model_ref, **kw):
		refs.append(model_ref)
		return result()

	monkeypatch.setattr(service, 'run', fake_run)
	monkeypatch.setattr(service, 'provider_preflight', lambda model: None)  # the provider would reject the fake key
	await Agent('t', llm(), browser=Browser(local=True), workspace=tmp_path).run()
	usage = RequestUsage(input_tokens=1000, output_tokens=100)
	assert usage_and_cost([ModelResponse(parts=[TextPart('x')], usage=usage)], refs[0])[1]


async def test_param_model_is_authoritative(tmp_path):
	"""Roast C14: with `params: Any` the param_model was ignored; the action got a dict and params.qty broke."""
	from typing import Any

	tools = Tools()

	class Order(BaseModel):
		sku: str
		qty: int

	@tools.action('Place an order', param_model=Order)
	def place_order(params: Any) -> str:
		return f'{params.qty}x {params.sku}'

	model, seen = script(('place_order', {'params': {'sku': 'A1', 'qty': '3'}}), ('finish', {'success': True, 'result': 'done'}))
	await run(build_agent(model, tools=tools.functions), 'task', Session(repl=Repl(tmp_path)), 'm')
	assert '3x A1' in str(seen[1][-1])


@pytest.fixture
def fake_browser(monkeypatch):
	"""Browser.start/stop as no-ops that count stops; the REPL worker still runs for real."""
	stops = []

	async def start(self):
		return {}

	async def stop(self, downloads_dir=None):
		stops.append(self)
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	return stops


async def test_two_agents_never_run_on_one_browser_at_once(fake_browser, tmp_path):
	"""H5: two Agents on one Browser drove one tab, and the first to finish stopped the browser under the other. The
	second run now raises before it starts anything; one after another (keep_alive) still works."""
	import asyncio

	browser = Browser(local=True, keep_alive=True)
	slow, _ = script(('python', {'code': 'import time; time.sleep(1)'}), ('finish', {'success': True, 'result': 'one'}))
	quick, _ = script(('finish', {'success': True, 'result': 'two'}), ('finish', {'success': True, 'result': 'three'}))
	first = Agent('t', slow, browser=browser, workspace=tmp_path / 'a')
	second = Agent('t', quick, browser=browser, workspace=tmp_path / 'b')
	try:
		r1, r2 = await asyncio.gather(first.run(), second.run(), return_exceptions=True)
		assert isinstance(r2, RuntimeError) and 'in use by another running Agent' in str(r2)
		assert not isinstance(r1, BaseException) and r1.final_result() == 'one'
		assert (await second.run()).final_result() == 'two'  # one after another is fine
	finally:
		await first.close()
		await second.close()


def test_run_sync_follow_up_keeps_the_repl_with_keep_alive(fake_browser, tmp_path):
	# 0.x scripts call run_sync() twice; the REPL worker belongs to the first call's event loop.
	model, _ = script(
		('python', {'code': 'x = 41'}),
		('finish', {'success': True, 'result': 'one'}),
		('finish_from_repl', {'success': True, 'expression': 'str(x + 1)'}),
	)
	agent = Agent('t', model, browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	assert agent.run_sync().final_result() == 'one'
	agent.add_new_task('again')
	second = agent.run_sync()
	assert second.final_result() == '42', second.error  # same REPL: the variable survived
	import asyncio

	runner_loop = agent._runner.get_loop()
	asyncio.run(agent.close())  # from another loop: kills the worker without awaiting it
	assert agent._repl is None and not fake_browser
	assert agent._runner is None and runner_loop.is_closed()  # Fable r2-9: run_sync's loop leaked


@pytest.mark.skipif(sys.platform == 'win32', reason='reads the process state with ps')
def test_an_agent_dropped_without_close_ends_its_repl_worker(fake_browser, tmp_path):
	"""rr-failure 1: with Browser(keep_alive=True) each Agent kept its REPL worker (~35 MB) until close() or exit, also
	once nothing referenced it; a service running one keep_alive Browser for many Agents (MIGRATING) grew by one
	process per Agent."""
	import gc
	import subprocess

	from browser_use.repl.session import _WORKERS

	model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'success': True, 'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	assert agent.run_sync().final_result() == 'one'
	assert agent._repl and agent._repl.proc
	pid = agent._repl.proc.pid
	del agent
	gc.collect()
	state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
	assert pid not in _WORKERS and state[:1] in ('', 'Z'), state  # killed (a zombie until asyncio reaps it)


def test_close_sync_ends_run_sync_follow_ups(fake_browser, tmp_path):
	model, _ = script(('python', {'code': 'x = 1'}), ('finish', {'success': True, 'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True, keep_alive=True), workspace=tmp_path)
	assert agent.run_sync().final_result() == 'one'
	runner_loop, repl = agent._runner.get_loop(), agent._repl
	agent.close_sync()
	assert agent._runner is None and runner_loop.is_closed() and agent._repl is None
	assert repl.proc is None


async def test_failed_follow_up_still_stops_the_browser(fake_browser, monkeypatch, tmp_path):
	model, _ = script(('finish', {'success': True, 'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True), workspace=tmp_path)
	assert (await agent.run()).final_result() == 'one' and len(fake_browser) == 1

	async def broken(self):
		raise RuntimeError('browser failed')

	monkeypatch.setattr(Browser, 'start', broken)
	agent.add_new_task('again')
	result = await agent.run()  # error contract: a failed browser start returns status='error', never raises
	assert (result.status, result.error) == ('error', 'browser failed')
	assert len(fake_browser) == 2  # a pending follow-up no longer keeps a failed run's browser alive


async def test_failed_follow_up_never_returns_the_previous_tasks_result(tmp_path):
	"""Roast r2-6: a follow-up that failed before its first checkpoint returned the previous task's partial or last
	text as its own result."""
	from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
	from pydantic_ai.models.function import FunctionModel

	def broken(messages, info):
		raise RuntimeError('provider down')

	history = [ModelRequest(parts=[UserPromptPart('task A')]), ModelResponse(parts=[TextPart('answer to task A')])]
	repl = Repl(tmp_path)
	repl.state.mkdir(parents=True)
	(repl.state / 'partial.json').write_text('{"file": "a.json", "value": "partial of task A"}', encoding='utf-8')
	r = await run(build_agent(FunctionModel(broken)), 'task B', Session(repl=repl), 'm', message_history=history)
	assert (r.status, r.partial, r.text) == ('error', None, '')


async def test_run_error_never_shows_a_secret(tmp_path):
	"""Roast r2-8: an exception quoting a registered secret stayed plaintext in result.error, which Agent.run logs."""
	from pydantic_ai.models.function import FunctionModel

	secret = 'hunter2-Zq9'

	def provider(messages, info):  # a custom tool's exception goes back to the model (H2): the provider's ends the run
		raise RuntimeError(f'login failed for password {secret}')

	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	r = await run(build_agent(FunctionModel(provider)), 'task', session, 'm')
	assert r.status == 'error' and r.error == 'RuntimeError: login failed for password <secret:pw>'


async def test_failed_run_fallback_output_never_shows_a_secret(tmp_path):
	"""Roast r5-1: a text reply quoting a secret, then a provider failure: the fallback became raw result.output."""
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.models.function import AgentInfo, FunctionModel

	secret = 'hunter2-Zq9'
	calls = []

	def reply(messages, info: AgentInfo) -> ModelResponse:
		calls.append(1)
		if len(calls) == 1:
			return ModelResponse(parts=[TextPart(f'The password is {secret}')])
		raise RuntimeError('provider down')

	session = Session(repl=Repl(tmp_path, secrets={'pw': secret}))
	# structured result: the text reply gets a delivery repair turn (a str result would take it as the answer, C33)
	r = await run(build_agent(FunctionModel(reply), output_type=dict[str, str]), 'task', session, 'm')
	assert r.status == 'error'
	assert secret not in str(r.output) and secret not in r.text and '<secret:pw>' in str(r.output)


def test_cost_is_the_price_of_the_model_that_answered():
	"""H12: Gemini was priced as the requested alias (gemini-3.5-flash) while the response came from (and was billed as)
	gemini-3.6-flash: about 2.3x too high. Review: an unknown served model was priced as the requested one; only a
	snapshot of the requested model (or no served name) falls back to the requested price."""
	from genai_prices import calc_price
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	from browser_use.agent.loop import usage_and_cost

	u = RequestUsage(input_tokens=1_000_000, output_tokens=100_000)
	served = float(calc_price(u, model_ref='gemini-2.5-flash', provider_id='google').total_price)
	requested = float(calc_price(u, model_ref='gemini-2.5-pro', provider_id='google').total_price)
	answer = ModelResponse(parts=[TextPart('x')], usage=u, model_name='gemini-2.5-flash')
	assert usage_and_cost([answer], 'google-gla:gemini-2.5-pro')[1] == pytest.approx(served) != pytest.approx(requested)
	unknown = ModelResponse(parts=[TextPart('x')], usage=u, model_name='gemini-made-up-model-9')
	assert usage_and_cost([unknown], 'google-gla:gemini-2.5-pro')[1] is None
	for served in ('gemini-2.5-pro-made-up-snapshot-9', None):
		answer = ModelResponse(parts=[TextPart('x')], usage=u, model_name=served)
		assert usage_and_cost([answer], 'google-gla:gemini-2.5-pro')[1] == pytest.approx(requested), served


def test_cost_includes_cache_writes():
	"""Roast r2-9: cache_write_tokens were dropped from pricing, so Anthropic runs were under-reported."""
	from genai_prices import Usage, calc_price
	from pydantic_ai.messages import ModelResponse, TextPart
	from pydantic_ai.usage import RequestUsage

	from browser_use.agent.loop import usage_and_cost

	u = RequestUsage(input_tokens=6000, cache_write_tokens=5000, cache_read_tokens=0, output_tokens=500)
	usage, cost = usage_and_cost([ModelResponse(parts=[TextPart('x')], usage=u)], 'anthropic:claude-sonnet-4-5')
	expected = calc_price(
		Usage(input_tokens=6000, cache_write_tokens=5000, output_tokens=500), 'claude-sonnet-4-5', provider_id='anthropic'
	)
	assert cost == float(expected.total_price) and usage['cache_write'] == 5000


def test_action_result_imports_from_its_0x_location():
	"""Fable r2-7: `from browser_use.agent.views import ActionResult` (0.x's canonical import) raised ImportError."""
	from browser_use.agent.views import ActionResult as Old

	assert Old is ActionResult


async def test_secrets_in_the_task_never_reach_the_model(fake_browser, tmp_path):
	"""Roast r3-2: Agent(f'Log in with {password}', sensitive_data=...) sent the password in the first request (0.x
	replaced it with the secret's name); follow-up tasks and extend_system_message too."""
	secret = 'hunter2-Zq9'
	model, seen = script(('finish', {'success': True, 'result': 'one'}), ('finish', {'success': True, 'result': 'two'}))
	agent = Agent(
		f'Log in with {secret}',
		model,
		browser=Browser(local=True),
		sensitive_data={'pw': secret},
		extend_system_message=f'The password is {secret}.',
		workspace=tmp_path,
	)
	await agent.run()
	agent.add_new_task(f'Again with {secret}')
	await agent.run()
	assert secret not in str(seen) and 'Log in with <secret:pw>' in str(seen[0]) and 'Again with <secret:pw>' in str(seen[1])
	assert 'The password is <secret:pw>.' in str(seen[0])


async def test_overlapping_runs_on_one_agent_are_rejected(fake_browser, tmp_path):
	"""Roast r3-6: two concurrent run() calls on one Agent each created a REPL (one never closed) and either could
	stop the other's browser."""
	import asyncio

	model, _ = script(('finish', {'success': True, 'result': 'one'}))
	agent = Agent('t', model, browser=Browser(local=True), workspace=tmp_path)
	first, second = await asyncio.gather(agent.run(), agent.run(), return_exceptions=True)
	assert isinstance(second, RuntimeError) and 'already running' in str(second)
	assert first.final_result() == 'one' and len(fake_browser) == 1  # only the first run started and stopped
	assert (await agent.run()).status == 'error'  # the next run is allowed again (the script has no third turn)


@pytest.mark.parametrize('task', [None, '', '   ', 123])
def test_a_task_that_is_not_text_raises_before_any_browser(task, no_browser):
	"""M10: Agent(None / '' / 123) was accepted, started Chrome, then failed (a raw TypeError on cloud)."""
	with pytest.raises((TypeError, ValueError), match='task'):
		Agent(task, script()[0], browser=Browser(local=True))
	agent = Agent('t', script()[0], browser=Browser(local=True))
	with pytest.raises((TypeError, ValueError), match='task'):
		agent.add_new_task(task)


async def test_run_sync_inside_a_running_loop_says_to_await_run(no_browser, recwarn):
	"""M11: run_sync() inside a running loop gave a raw asyncio error plus a "coroutine never awaited" warning."""
	agent = Agent('t', script()[0], browser=Browser(local=True))
	with pytest.raises(RuntimeError, match=r'await agent\.run\(\)'):
		agent.run_sync()
	assert not [w for w in recwarn if 'never awaited' in str(w.message)]


@pytest.mark.parametrize('reasoning', ['max', 'Medium', True])
def test_unknown_reasoning_raises_before_any_browser(reasoning, no_browser):
	"""Fable r3-2: reasoning was stored unchecked; a typo started (and billed) a cloud browser, then the first model
	request failed with a 400."""
	with pytest.raises(ValueError, match='reasoning'):
		Agent('t', 'test', reasoning=reasoning)


async def test_old_mcp_tool_names_return_the_removed_error():
	from mcp import types

	from browser_use.mcp import cli_mcp

	handler = cli_mcp.CLIMCPServer().server._request_handlers['tools/call'].handler
	for name in ('browser_navigate', 'browser_click', 'retry_with_browser_use_agent'):
		r = await handler(None, types.CallToolRequestParams(name=name, arguments={}))
		text = r.content[0].text  # type: ignore[union-attr]
		assert r.is_error and text.startswith(
			f'The MCP tool {name} (the 0.x browser-use --mcp server) was removed in browser-use 1.0.'
		)
		assert 'browser_exec runs Python' in text
	r = await handler(None, types.CallToolRequestParams(name='nope', arguments={}))
	assert r.content[0].text == 'Unknown tool: nope'  # type: ignore[union-attr]


async def test_browser_exec_output_is_capped_like_agent_cells():
	"""C45: browser_exec returned a 2MB print verbatim into the MCP client's context."""
	from pathlib import Path

	from mcp import types

	from browser_use.mcp import cli_mcp
	from browser_use.repl.session import MAX_OUTPUT_CHARS

	mcp = cli_mcp.CLIMCPServer()
	big = 'A' * 2_000_000
	mcp._execute = lambda code: (big, False)  # what print("A"*2_000_000) captures, without a browser
	handler = mcp.server._request_handlers['tools/call'].handler
	r = await handler(None, types.CallToolRequestParams(name='browser_exec', arguments={'code': 'print(1)'}))
	text = r.content[0].text  # type: ignore[union-attr]
	head, _, path = text.rpartition('\n[Truncated. Full captured output: ')
	assert not r.is_error and head == big[:MAX_OUTPUT_CHARS]
	full = Path(path.removesuffix(']'))
	assert full.read_text() == big
	full.unlink()
