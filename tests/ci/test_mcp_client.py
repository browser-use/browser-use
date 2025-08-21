"""Tests for MCP (Model Context Protocol) client integration with real MCP server."""

import json
import sys
import tempfile
from pathlib import Path

# Import MCP SDK for creating test server
import mcp.server.stdio
import mcp.types as types
import pytest
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pytest_httpserver import HTTPServer

from browser_use import ActionResult, Agent, BrowserProfile, BrowserSession, Controller
from browser_use.mcp.client import MCPClient


class MockMCPServer:
	"""A minimal MCP server for testing."""

	def __init__(self):
		self.server = Server('test-mcp-server')
		self.call_history = []  # Track all tool calls
		self._setup_handlers()

	def _setup_handlers(self):
		"""Setup MCP server handlers."""

		@self.server.list_tools()
		async def handle_list_tools() -> list[types.Tool]:
			"""List available test tools."""
			return [
				types.Tool(
					name='count_to_n',
					description='Count from 1 to n and return the numbers',
					inputSchema={
						'type': 'object',
						'properties': {'n': {'type': 'integer', 'description': 'Number to count to'}},
						'required': ['n'],
					},
				),
				types.Tool(
					name='echo_message',
					description='Echo back a message with a prefix',
					inputSchema={
						'type': 'object',
						'properties': {
							'message': {'type': 'string', 'description': 'Message to echo'},
							'prefix': {'type': 'string', 'description': 'Prefix to add', 'default': 'Echo:'},
						},
						'required': ['message'],
					},
				),
				types.Tool(
					name='get_test_data',
					description='Get some test data as JSON',
					inputSchema={'type': 'object', 'properties': {}},
				),
				types.Tool(
					name='process_trace_update',
					description='Process a cognitive trace update with nested object parameter',
					inputSchema={
						'type': 'object',
						'properties': {
							'trace': {
								'type': 'object',
								'properties': {
									'recent_actions': {
										'type': 'array',
										'items': {'type': 'string'},
										'description': 'List of recent action names',
									},
									'current_context': {
										'type': 'string',
										'description': 'Current environment context or state',
									},
									'goal': {
										'type': 'string',
										'description': 'Current goal being pursued',
									},
								},
								'required': ['recent_actions', 'goal'],
								'additionalProperties': False,
							},
							'window_size': {
								'type': 'number',
								'description': 'Size of the monitoring window',
								'default': 10,
							},
						},
						'required': ['trace'],
						'additionalProperties': False,
					},
				),
				types.Tool(
					name='process_array_data',
					description='Process various array types',
					inputSchema={
						'type': 'object',
						'properties': {
							'string_list': {
								'type': 'array',
								'items': {'type': 'string'},
								'description': 'List of strings',
							},
							'number_list': {
								'type': 'array',
								'items': {'type': 'number'},
								'description': 'List of numbers',
							},
							'config_list': {
								'type': 'array',
								'items': {
									'type': 'object',
									'properties': {
										'name': {'type': 'string'},
										'value': {'type': 'integer'},
										'enabled': {'type': 'boolean', 'default': True},
									},
									'required': ['name', 'value'],
								},
								'description': 'List of configuration objects',
							},
							'simple_array': {
								'type': 'array',
								'description': 'Array without item type specified',
							},
						},
						'required': ['string_list'],
					},
				),
			]

		@self.server.call_tool()
		async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
			"""Handle tool execution."""
			# Record the call
			self.call_history.append({'tool': name, 'arguments': arguments or {}})

			if name == 'count_to_n':
				assert arguments is not None
				n = arguments.get('n', 5)
				numbers = ', '.join(str(i) for i in range(1, n + 1))
				result = f'Counted to {n}: {numbers}'

			elif name == 'echo_message':
				assert arguments is not None
				message = arguments.get('message', '')
				prefix = arguments.get('prefix', 'Echo:')
				result = f'{prefix} {message}'

			elif name == 'get_test_data':
				data = {'status': 'success', 'items': ['apple', 'banana', 'cherry'], 'count': 3}
				result = json.dumps(data, indent=2)

			elif name == 'process_trace_update':
				assert arguments is not None
				trace = arguments.get('trace', {})
				window_size = arguments.get('window_size', 10)

				recent_actions = trace.get('recent_actions', [])
				current_context = trace.get('current_context', 'unknown')
				goal = trace.get('goal', 'no goal')

				result = f'Processed trace update: {len(recent_actions)} actions, goal: {goal}, context: {current_context}, window: {window_size}'

			elif name == 'process_array_data':
				assert arguments is not None
				string_list = arguments.get('string_list', [])
				number_list = arguments.get('number_list', [])
				config_list = arguments.get('config_list', [])
				simple_array = arguments.get('simple_array', [])

				config_summary = f'{len(config_list)} configs' if config_list else 'no configs'
				result = f'Processed arrays: strings={len(string_list)}, numbers={len(number_list)}, {config_summary}, simple={len(simple_array)}'

			else:
				result = f'Unknown tool: {name}'

			return [types.TextContent(type='text', text=result)]

	async def run(self):
		"""Run the MCP server."""
		async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
			await self.server.run(
				read_stream,
				write_stream,
				InitializationOptions(
					server_name='test-mcp-server',
					server_version='0.1.0',
					capabilities=self.server.get_capabilities(
						notification_options=NotificationOptions(),
						experimental_capabilities={},
					),
				),
			)


# Create test server script that will run in subprocess
TEST_SERVER_CODE = """
import asyncio
import sys
sys.path.insert(0, "{project_root}")

from tests.ci.test_mcp_client import MockMCPServer

async def main():
	server = MockMCPServer()
	await server.run()

if __name__ == "__main__":
	asyncio.run(main())
"""


@pytest.fixture
async def test_mcp_server_script():
	"""Create a temporary script file for the test MCP server."""
	with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
		project_root = str(Path(__file__).parent.parent.parent)
		f.write(TEST_SERVER_CODE.format(project_root=project_root))
		script_path = f.name

	yield script_path

	Path(script_path).unlink(missing_ok=True)


async def test_mcp_client_basic_connection(test_mcp_server_script):
	"""Test basic MCP client connection and tool discovery."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		# Connect to server
		await mcp_client.connect()

		# Verify tools were discovered
		assert len(mcp_client._tools) == 5
		assert 'count_to_n' in mcp_client._tools
		assert 'echo_message' in mcp_client._tools
		assert 'get_test_data' in mcp_client._tools
		assert 'process_trace_update' in mcp_client._tools
		assert 'process_array_data' in mcp_client._tools

		# Register tools to controller
		await mcp_client.register_to_controller(controller)

		# Verify tools are registered as actions
		actions = controller.registry.registry.actions
		assert 'count_to_n' in actions
		assert 'echo_message' in actions
		assert 'get_test_data' in actions

		# Test executing a tool
		echo_action = actions['echo_message']
		# Need to create param model instance
		params = echo_action.param_model(message='Hello MCP', prefix='Test:')
		result = await echo_action.function(params=params)

		assert result.extracted_content == 'Test: Hello MCP'
		assert 'echo_message' in result.long_term_memory
		assert 'test-server' in result.long_term_memory

	finally:
		await mcp_client.disconnect()


async def test_mcp_tools_with_agent(test_mcp_server_script, httpserver: HTTPServer):
	"""Test that agent can discover and use MCP tools."""
	# Set up test webpage
	httpserver.expect_request('/').respond_with_data(
		"""
		<html>
		<body>
			<h1>Test Page</h1>
			<p>Count to 5 and echo a message</p>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None, keep_alive=True))
	await browser_session.start()
	controller = Controller()

	# Connect MCP client
	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()
		await mcp_client.register_to_controller(controller)

		# Import create_mock_llm from conftest
		from tests.ci.conftest import create_mock_llm

		# Create mock LLM with specific actions
		actions = [
			f'{{"thinking": null, "evaluation_previous_goal": "Starting", "memory": "Starting task", "next_goal": "Navigate to test page", "action": [{{"go_to_url": {{"url": "{httpserver.url_for("/")}", "new_tab": false}}}}]}}',
			'{"thinking": null, "evaluation_previous_goal": "Navigated", "memory": "On test page", "next_goal": "Count to 3", "action": [{"count_to_n": {"n": 3}}]}',
			'{"thinking": null, "evaluation_previous_goal": "Counted", "memory": "Counted to 3", "next_goal": "Echo message", "action": [{"echo_message": {"message": "MCP works!"}}]}',
			'{"thinking": null, "evaluation_previous_goal": "Echoed", "memory": "Message echoed", "next_goal": "Complete", "action": [{"done": {"text": "Completed MCP test", "success": true}}]}',
		]
		mock_llm = create_mock_llm(actions=actions)

		# Create agent
		agent = Agent(
			task=f"Go to {httpserver.url_for('/')} then use count_to_n to count to 3, and echo_message to say 'MCP works!'",
			llm=mock_llm,
			browser_session=browser_session,
			controller=controller,
		)

		# Run agent
		history = await agent.run(max_steps=10)

		# Verify the agent used MCP tools
		action_names = []
		for step in history.history:
			if step.model_output and step.model_output.action:
				for action in step.model_output.action:
					action_dict = action.model_dump(exclude_unset=True)
					action_names.extend(action_dict.keys())

		assert 'count_to_n' in action_names
		assert 'echo_message' in action_names

		# Check results
		results = []
		for step in history.history:
			if step.result:
				for r in step.result:
					if r.extracted_content:
						results.append(r.extracted_content)

		# Verify MCP tool outputs
		assert any('Counted to 3: 1, 2, 3' in r for r in results)
		assert any('Echo: MCP works!' in r for r in results)

	finally:
		await mcp_client.disconnect()
		await browser_session.kill()


async def test_mcp_tool_parameter_validation(test_mcp_server_script):
	"""Test that MCP tool parameters are properly validated."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()
		await mcp_client.register_to_controller(controller)

		# Get the count_to_n action
		count_action = controller.registry.registry.actions['count_to_n']

		# Test with valid parameter
		params = count_action.param_model(n=7)
		result = await count_action.function(params=params)
		assert 'Counted to 7' in result.extracted_content

		# Test parameter model validation
		param_model = count_action.param_model
		assert param_model is not None

		# Verify required fields
		assert 'n' in param_model.model_fields
		assert param_model.model_fields['n'].is_required()

		# Test echo_message with optional parameter
		echo_action = controller.registry.registry.actions['echo_message']

		# With default prefix
		params = echo_action.param_model(message='Test')
		result = await echo_action.function(params=params)
		assert result.extracted_content == 'Echo: Test'

		# With custom prefix
		params = echo_action.param_model(message='Test', prefix='Custom:')
		result = await echo_action.function(params=params)
		assert result.extracted_content == 'Custom: Test'

	finally:
		await mcp_client.disconnect()


async def test_mcp_client_prefix_and_filtering(test_mcp_server_script):
	"""Test tool filtering and prefixing."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()

		# Register only specific tools with prefix
		await mcp_client.register_to_controller(controller, tool_filter=['count_to_n', 'echo_message'], prefix='mcp_')

		# Verify registration
		actions = controller.registry.registry.actions
		assert 'mcp_count_to_n' in actions
		assert 'mcp_echo_message' in actions
		assert 'mcp_get_test_data' not in actions  # Filtered out
		assert 'get_test_data' not in actions  # Not registered without prefix

		# Test prefixed action works
		action = actions['mcp_count_to_n']
		params = action.param_model(n=2)
		result = await action.function(params=params)
		assert 'Counted to 2: 1, 2' in result.extracted_content

	finally:
		await mcp_client.disconnect()


async def test_mcp_tool_error_handling(test_mcp_server_script):
	"""Test error handling in MCP tools."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()
		await mcp_client.register_to_controller(controller)

		# Disconnect to simulate connection loss
		await mcp_client.disconnect()

		# Try to use tool after disconnect
		echo_action = controller.registry.registry.actions['echo_message']
		params = echo_action.param_model(message='Test')
		result: ActionResult = await echo_action.function(params=params)

		# Should handle error gracefully
		assert result.error is not None

	finally:
		# Already disconnected
		pass


async def test_mcp_client_context_manager(test_mcp_server_script):
	"""Test using MCP client as context manager."""
	controller = Controller()

	# Use as context manager
	async with MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script]) as mcp_client:
		# Should auto-connect
		assert mcp_client.session is not None

		await mcp_client.register_to_controller(controller)

		# Test tool works
		action = controller.registry.registry.actions['get_test_data']
		# get_test_data has no parameters
		result = await action.function()
		assert 'apple' in result.extracted_content
		assert 'banana' in result.extracted_content

	# Should auto-disconnect
	assert mcp_client.session is None


async def test_multiple_mcp_servers(test_mcp_server_script):
	"""Test connecting multiple MCP servers to the same controller."""
	controller = Controller()

	# First MCP server with prefix
	mcp1 = MCPClient(server_name='server1', command=sys.executable, args=[test_mcp_server_script])

	# Second MCP server with different prefix
	mcp2 = MCPClient(server_name='server2', command=sys.executable, args=[test_mcp_server_script])

	try:
		# Connect and register both
		await mcp1.connect()
		await mcp1.register_to_controller(controller, prefix='s1_')

		await mcp2.connect()
		await mcp2.register_to_controller(controller, prefix='s2_')

		# Verify both sets of tools are available
		actions = controller.registry.registry.actions
		assert 's1_count_to_n' in actions
		assert 's2_count_to_n' in actions

		# Test both work independently
		action1 = actions['s1_echo_message']
		params1 = action1.param_model(message='Server 1')
		result1 = await action1.function(params=params1)

		action2 = actions['s2_echo_message']
		params2 = action2.param_model(message='Server 2')
		result2 = await action2.function(params=params2)

		assert result1.extracted_content == 'Echo: Server 1'
		assert result2.extracted_content == 'Echo: Server 2'

		# Verify results show correct server
		assert 'server1' in result1.long_term_memory
		assert 'server2' in result2.long_term_memory

	finally:
		await mcp1.disconnect()
		await mcp2.disconnect()


async def test_mcp_result_formatting(test_mcp_server_script):
	"""Test that different MCP result formats are handled correctly."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()
		await mcp_client.register_to_controller(controller)

		# Test JSON result formatting
		action = controller.registry.registry.actions['get_test_data']
		result = await action.function()

		# Should contain formatted JSON
		assert '"status": "success"' in result.extracted_content
		assert '"items"' in result.extracted_content
		assert '"count": 3' in result.extracted_content

	finally:
		await mcp_client.disconnect()


async def test_agent_with_multiple_mcp_servers(test_mcp_server_script, httpserver: HTTPServer):
	"""Test agent using tools from multiple MCP servers in a single task."""
	# Set up test webpage
	httpserver.expect_request('/').respond_with_data(
		"""
		<html>
		<body>
			<h1>Multi-MCP Test</h1>
			<p>Use tools from both servers</p>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	browser_session = BrowserSession(browser_profile=BrowserProfile(headless=True, user_data_dir=None))
	await browser_session.start()
	controller = Controller()

	# Connect two MCP servers with different prefixes
	mcp_server1 = MCPClient(server_name='math-server', command=sys.executable, args=[test_mcp_server_script])
	mcp_server2 = MCPClient(server_name='data-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		# Connect and register both servers
		await mcp_server1.connect()
		await mcp_server1.register_to_controller(controller, prefix='math_', tool_filter=['count_to_n'])

		await mcp_server2.connect()
		await mcp_server2.register_to_controller(controller, prefix='data_', tool_filter=['echo_message', 'get_test_data'])

		# Import create_mock_llm from conftest
		from tests.ci.conftest import create_mock_llm

		# Create mock LLM with actions using tools from both servers
		actions = [
			f'{{"thinking": null, "evaluation_previous_goal": "Starting", "memory": "Starting multi-MCP task", "next_goal": "Navigate to test page", "action": [{{"go_to_url": {{"url": "{httpserver.url_for("/")}"}}}}]}}',
			'{"thinking": null, "evaluation_previous_goal": "Navigated", "memory": "On test page", "next_goal": "Use math server to count", "action": [{"math_count_to_n": {"n": 5}}]}',
			'{"thinking": null, "evaluation_previous_goal": "Counted with math server", "memory": "Used math_count_to_n", "next_goal": "Use data server to echo", "action": [{"data_echo_message": {"message": "Counted successfully", "prefix": "Result:"}}]}',
			'{"thinking": null, "evaluation_previous_goal": "Echoed with data server", "memory": "Used data_echo_message", "next_goal": "Get test data from data server", "action": [{"data_get_test_data": {}}]}',
			'{"thinking": null, "evaluation_previous_goal": "Got test data", "memory": "Retrieved JSON data", "next_goal": "Complete", "action": [{"done": {"text": "Used tools from both MCP servers successfully", "success": true}}]}',
		]
		mock_llm = create_mock_llm(actions=actions)

		# Create agent with extended system message
		agent = Agent(
			task=f'Go to {httpserver.url_for("/")}, use math_count_to_n to count to 5, then use data_echo_message and data_get_test_data',
			llm=mock_llm,
			browser_session=browser_session,
			controller=controller,
			extend_system_message="""You have access to tools from two MCP servers:
- math server: Provides math_count_to_n for counting
- data server: Provides data_echo_message for echoing and data_get_test_data for JSON data

Use tools from both servers to complete the task.""",
		)

		# Run agent
		history = await agent.run(max_steps=10)

		# Verify the agent used tools from both servers
		action_names = []
		for step in history.history:
			if step.model_output and step.model_output.action:
				for action in step.model_output.action:
					action_dict = action.model_dump(exclude_unset=True)
					action_names.extend(action_dict.keys())

		# Should have used tools from both servers
		assert 'math_count_to_n' in action_names
		assert 'data_echo_message' in action_names
		assert 'data_get_test_data' in action_names

		# Check results contain outputs from both servers
		results = []
		memory_entries = []
		for step in history.history:
			if step.result:
				for r in step.result:
					if r.extracted_content:
						results.append(r.extracted_content)
					if r.long_term_memory:
						memory_entries.append(r.long_term_memory)

		# Verify outputs from both servers
		assert any('Counted to 5: 1, 2, 3, 4, 5' in r for r in results)
		assert any('Result: Counted successfully' in r for r in results)
		assert any('"status": "success"' in r for r in results)

		# Verify both server names appear in memory
		all_memory = ' '.join(memory_entries)
		assert 'math-server' in all_memory
		assert 'data-server' in all_memory

	finally:
		await mcp_server1.disconnect()
		await mcp_server2.disconnect()
		await browser_session.kill()


async def test_mcp_nested_object_parameters(test_mcp_server_script):
	"""Test that MCP tools with nested object parameters are properly handled."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()
		await mcp_client.register_to_controller(controller)

		# Get the process_trace_update action
		trace_action = controller.registry.registry.actions['process_trace_update']

		# Verify the parameter model has nested structure
		param_model = trace_action.param_model
		assert param_model is not None

		# Verify the main parameters exist
		assert 'trace' in param_model.model_fields
		assert 'window_size' in param_model.model_fields

		# Verify trace is required and window_size is optional
		assert param_model.model_fields['trace'].is_required()
		assert not param_model.model_fields['window_size'].is_required()

		# Verify window_size has a default value of 10
		assert param_model.model_fields['window_size'].default == 10

		# Verify the trace parameter has nested structure
		trace_field = param_model.model_fields['trace']
		trace_annotation = trace_field.annotation

		# Should be a nested pydantic model, not just dict
		assert trace_annotation is not dict
		assert trace_annotation is not None

		# Verify nested model has the expected fields
		nested_model = trace_annotation
		assert hasattr(nested_model, 'model_fields')
		nested_fields = nested_model.model_fields
		assert 'recent_actions' in nested_fields
		assert 'current_context' in nested_fields
		assert 'goal' in nested_fields

		# Verify field requirements in nested model
		assert nested_fields['recent_actions'].is_required()
		assert nested_fields['goal'].is_required()
		assert not nested_fields['current_context'].is_required()

		# Test creating an instance with nested parameters
		assert callable(nested_model)
		trace_data = nested_model(recent_actions=['click', 'type', 'navigate'], current_context='web page', goal='complete form')

		# Test the full parameter model
		assert callable(param_model)
		params = param_model(trace=trace_data, window_size=5)

		# Verify the parameter structure
		assert hasattr(params, 'trace') and hasattr(params, 'window_size')
		trace_obj = getattr(params, 'trace')
		assert trace_obj.recent_actions == ['click', 'type', 'navigate']
		assert trace_obj.current_context == 'web page'
		assert trace_obj.goal == 'complete form'
		assert getattr(params, 'window_size') == 5

		# Test calling the tool with nested parameters
		result = await trace_action.function(params=params)

		# Verify the result contains the nested data
		assert result.success is not False
		assert 'Processed trace update' in result.extracted_content
		assert '3 actions' in result.extracted_content
		assert 'goal: complete form' in result.extracted_content
		assert 'context: web page' in result.extracted_content
		assert 'window: 5' in result.extracted_content

		# Test with default window_size
		params_default = param_model(trace=trace_data)
		result_default = await trace_action.function(params=params_default)
		assert 'window: 10' in result_default.extracted_content

		# Test with minimal required parameters
		minimal_trace = nested_model(recent_actions=['action1', 'action2'], goal='test goal')
		params_minimal = param_model(trace=minimal_trace)
		result_minimal = await trace_action.function(params=params_minimal)
		assert 'goal: test goal' in result_minimal.extracted_content
		assert 'context: unknown' in result_minimal.extracted_content  # Default from handler

	finally:
		await mcp_client.disconnect()


async def test_mcp_array_type_inference(test_mcp_server_script):
	"""Test that MCP tools with array parameters have proper type inference."""
	controller = Controller()

	mcp_client = MCPClient(server_name='test-server', command=sys.executable, args=[test_mcp_server_script])

	try:
		await mcp_client.connect()
		await mcp_client.register_to_controller(controller)

		# Get the process_array_data action
		array_action = controller.registry.registry.actions['process_array_data']

		# Verify the parameter model has array types
		param_model = array_action.param_model
		assert param_model is not None

		# Verify the main parameters exist
		assert 'string_list' in param_model.model_fields
		assert 'number_list' in param_model.model_fields
		assert 'config_list' in param_model.model_fields
		assert 'simple_array' in param_model.model_fields

		# Verify string_list is required and others are optional
		assert param_model.model_fields['string_list'].is_required()
		assert not param_model.model_fields['number_list'].is_required()
		assert not param_model.model_fields['config_list'].is_required()
		assert not param_model.model_fields['simple_array'].is_required()

		# Check array type annotations
		string_list_field = param_model.model_fields['string_list']
		number_list_field = param_model.model_fields['number_list']
		config_list_field = param_model.model_fields['config_list']
		simple_array_field = param_model.model_fields['simple_array']

		# Import typing_extensions for better type inspection
		import typing
		from typing import get_args, get_origin

		# Check string_list is list[str]
		string_list_type = string_list_field.annotation
		assert get_origin(string_list_type) is list
		assert get_args(string_list_type) == (str,)

		# Check number_list is list[float] | None (since it's optional)
		number_list_type = number_list_field.annotation
		# For optional fields, the type is Union[list[float], None]
		assert get_origin(number_list_type) in (typing.Union, type(list[float] | None))
		union_args = get_args(number_list_type)
		assert type(None) in union_args
		# Find the list type in the union
		list_type = next((arg for arg in union_args if get_origin(arg) is list), None)
		assert list_type is not None
		assert get_args(list_type) == (float,)

		# Check config_list is list[ConfigModel] | None
		config_list_type = config_list_field.annotation
		assert get_origin(config_list_type) in (typing.Union, type(list[object] | None))
		union_args = get_args(config_list_type)
		assert type(None) in union_args
		# Find the list type in the union
		list_type = next((arg for arg in union_args if get_origin(arg) is list), None)
		assert list_type is not None
		# The item type should be a Pydantic model with the expected fields
		config_item_type = get_args(list_type)[0]
		assert hasattr(config_item_type, 'model_fields')
		config_fields = config_item_type.model_fields
		assert 'name' in config_fields
		assert 'value' in config_fields
		assert 'enabled' in config_fields
		assert config_fields['name'].is_required()
		assert config_fields['value'].is_required()
		assert not config_fields['enabled'].is_required()
		assert config_fields['enabled'].default is True

		# Check simple_array is just list | None (no item type)
		simple_array_type = simple_array_field.annotation
		assert get_origin(simple_array_type) in (typing.Union, type(list | None))
		union_args = get_args(simple_array_type)
		assert type(None) in union_args
		# Should have plain list without type args
		assert list in union_args

		# Test creating instances with proper types
		config_item_model = config_item_type
		config1 = config_item_model(name='setting1', value=42)
		config2 = config_item_model(name='setting2', value=100, enabled=False)

		# Create full parameter instance
		params = param_model(
			string_list=['hello', 'world'],
			number_list=[1.5, 2.7, 3.14],
			config_list=[config1, config2],
			simple_array=['mixed', 123, True],
		)

		# Verify the parameter structure
		assert getattr(params, 'string_list') == ['hello', 'world']
		assert getattr(params, 'number_list') == [1.5, 2.7, 3.14]
		config_list = getattr(params, 'config_list')
		assert len(config_list) == 2
		assert getattr(config_list[0], 'name') == 'setting1'
		assert getattr(config_list[0], 'value') == 42
		assert getattr(config_list[0], 'enabled') is True  # default
		assert getattr(config_list[1], 'name') == 'setting2'
		assert getattr(config_list[1], 'value') == 100
		assert getattr(config_list[1], 'enabled') is False
		assert getattr(params, 'simple_array') == ['mixed', 123, True]

		# Test calling the tool
		result = await array_action.function(params=params)
		assert result.success is not False
		assert 'Processed arrays: strings=2, numbers=3, 2 configs, simple=3' in result.extracted_content

		# Test with minimal parameters (only required string_list)
		minimal_params = param_model(string_list=['test'])
		result_minimal = await array_action.function(params=minimal_params)
		assert 'Processed arrays: strings=1, numbers=0, no configs, simple=0' in result_minimal.extracted_content

	finally:
		await mcp_client.disconnect()
