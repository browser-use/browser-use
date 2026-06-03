import json

from pydantic import BaseModel

from browser_use.agent.views import ActionResult, AgentHistory, AgentHistoryList, AgentOutput, BrowserStateHistory, StepMetadata
from browser_use.tools.registry.views import ActionModel


class ClickParams(BaseModel):
	index: int
	text: str


class InputParams(BaseModel):
	index: int
	text: str


class TraceAction(ActionModel):
	click: ClickParams | None = None
	input: InputParams | None = None


def test_to_run_trace_exports_action_level_debug_fields():
	model_output = AgentOutput(
		evaluation_previous_goal='Found the login form',
		memory='Need to fill username next',
		next_goal='Type into username field',
		action=[
			TraceAction(click=ClickParams(index=3, text='Sign in')),
			TraceAction(input=InputParams(index=4, text='ritwij@example.com')),
		],
	)
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=model_output,
				result=[
					ActionResult(long_term_memory='Clicked sign in'),
					ActionResult(error='Element detached'),
				],
				state=BrowserStateHistory(
					url='https://example.com/login',
					title='Login',
					tabs=[],
					interacted_element=[None, None],
					screenshot_path='/tmp/browser-use/step_1.png',
				),
				metadata=StepMetadata(step_number=7, step_start_time=100.0, step_end_time=102.5),
			)
		]
	)

	trace = history.to_run_trace()

	assert trace.total_duration_seconds == 2.5
	assert trace.is_done is False
	assert len(trace.steps) == 2
	assert trace.steps[0].step_index == 7
	assert trace.steps[0].action_index == 0
	assert trace.steps[0].action_type == 'click'
	assert trace.steps[0].action_payload == {'index': 3, 'text': 'Sign in'}
	assert trace.steps[0].llm_thought == {
		'evaluation_previous_goal': 'Found the login form',
		'memory': 'Need to fill username next',
		'next_goal': 'Type into username field',
	}
	assert trace.steps[0].screenshot_ref == '/tmp/browser-use/step_1.png'
	assert trace.steps[0].step_outcome == 'success'
	assert trace.steps[1].action_type == 'input'
	assert trace.steps[1].step_outcome == 'error'
	assert trace.steps[1].error == 'Element detached'


def test_save_trace_to_file_writes_compact_json(tmp_path):
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[ActionResult(extracted_content='Finished', is_done=True, success=True)],
				state=BrowserStateHistory(url='https://example.com', title='Done', tabs=[], interacted_element=[]),
				metadata=StepMetadata(step_number=1, step_start_time=10.0, step_end_time=11.0),
			)
		]
	)
	trace_path = tmp_path / 'run.trace.json'

	history.save_trace_to_file(trace_path)

	data = json.loads(trace_path.read_text())
	assert data['final_result'] == 'Finished'
	assert data['is_done'] is True
	assert data['success'] is True
	assert data['steps'][0]['step_outcome'] == 'done'
	assert data['steps'][0]['url'] == 'https://example.com'


def test_to_run_trace_redacts_sensitive_data_from_shareable_fields():
	secret_email = 'ritwij@example.com'
	model_output = AgentOutput(
		evaluation_previous_goal=f'Opened account for {secret_email}',
		memory=f'Need to verify {secret_email}',
		next_goal='Submit the form',
		action=[TraceAction(input=InputParams(index=4, text=secret_email))],
	)
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=model_output,
				result=[
					ActionResult(
						long_term_memory=f'Confirmation page showed {secret_email}',
						error=f'Validation mentioned {secret_email}',
					)
				],
				state=BrowserStateHistory(
					url=f'https://example.com/users/{secret_email}',
					title=f'Profile for {secret_email}',
					tabs=[],
					interacted_element=[None],
				),
				metadata=StepMetadata(step_number=1, step_start_time=10.0, step_end_time=11.0),
			)
		]
	)

	trace = history.to_run_trace(sensitive_data={'email': secret_email})
	trace_json = json.dumps(trace.model_dump(mode='json'))

	assert secret_email not in trace_json
	assert '<secret>email</secret>' in trace_json


def test_save_trace_viewer_writes_redacted_html(tmp_path):
	secret_email = 'ritwij@example.com'
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=AgentOutput(
					evaluation_previous_goal='Reached checkout',
					memory=f'Need to avoid exposing {secret_email}',
					next_goal='Stop before payment',
					action=[TraceAction(input=InputParams(index=4, text=secret_email))],
				),
				result=[ActionResult(error=f'Payment form rejected {secret_email}')],
				state=BrowserStateHistory(
					url=f'https://example.com/pay?email={secret_email}',
					title='Checkout <danger>',
					tabs=[],
					interacted_element=[None],
				),
				metadata=StepMetadata(step_number=3, step_start_time=10.0, step_end_time=10.25),
			)
		]
	)
	viewer_path = tmp_path / 'trace.html'

	history.save_trace_viewer(viewer_path, sensitive_data={'email': secret_email})

	html = viewer_path.read_text()
	assert 'Agent run trace' in html
	assert 'Step 3 action 0: input' in html
	assert '250ms' in html
	assert 'Payment form rejected &lt;secret&gt;email&lt;/secret&gt;' in html
	assert 'Checkout &lt;danger&gt;' in html
	assert secret_email not in html


def test_trace_redacts_final_result_from_json_and_html(tmp_path):
	secret_email = 'ritwij@example.com'
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[ActionResult(extracted_content=f'Final answer sent to {secret_email}', is_done=True, success=True)],
				state=BrowserStateHistory(url='https://example.com/done', title='Done', tabs=[], interacted_element=[]),
				metadata=StepMetadata(step_number=1, step_start_time=10.0, step_end_time=11.0),
			)
		]
	)
	trace_path = tmp_path / 'run.trace.json'
	viewer_path = tmp_path / 'trace.html'

	history.save_trace_to_file(trace_path, sensitive_data={'email': secret_email})
	history.save_trace_viewer(viewer_path, sensitive_data={'email': secret_email})

	trace_json = trace_path.read_text()
	html = viewer_path.read_text()
	assert secret_email not in trace_json
	assert secret_email not in html
	assert '<secret>email</secret>' in trace_json
	assert '&lt;secret&gt;email&lt;/secret&gt;' in html


def test_trace_viewer_can_embed_screenshots(tmp_path):
	screenshot_path = tmp_path / 'step.png'
	screenshot_path.write_bytes(b'\x89PNG\r\n\x1a\n')
	history = AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[ActionResult(long_term_memory='Loaded page')],
				state=BrowserStateHistory(
					url='https://example.com',
					title='Example',
					tabs=[],
					interacted_element=[],
					screenshot_path=str(screenshot_path),
				),
				metadata=StepMetadata(step_number=1, step_start_time=10.0, step_end_time=11.0),
			)
		]
	)

	html = history.to_run_trace().to_html(embed_screenshots=True)

	assert 'data:image/png;base64,' in html
	assert str(screenshot_path) not in html
