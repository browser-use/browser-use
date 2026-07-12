"""Test Google model button click."""

from browser_use.llm.google.chat import ChatGoogle
from tests.ci.models.model_test_helper import run_model_button_click_test


async def test_google_gemini_3_flash_preview(httpserver):
	"""Test Google gemini-3-flash-preview can click a button."""
	await run_model_button_click_test(
		model_class=ChatGoogle,
		model_name='gemini-3-flash-preview',
		api_key_env='GOOGLE_API_KEY',
		extra_kwargs={},
		httpserver=httpserver,
	)


def test_x_goog_api_client_header_is_set():
	"""Test that the x-goog-api-client header is correctly set in the HTTP options."""
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake')

	# Generate the params used for genai.Client
	params = chat._get_client_params()

	# Extract the header
	http_options = params.get('http_options', {})
	headers = http_options.get('headers', {})

	assert 'x-goog-api-client' in headers, 'x-goog-api-client header missing'
	assert 'browser-use/' in headers['x-goog-api-client'], 'browser-use not found in x-goog-api-client header'


def test_x_goog_api_client_header_with_none_http_options():
	"""Test setting header when http_options is None."""
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake', http_options=None)
	params = chat._get_client_params()
	http_opts = params.get('http_options', {})
	assert http_opts.get('headers', {}).get('x-goog-api-client', '').startswith('browser-use/')


def test_x_goog_api_client_header_with_pydantic_http_options():
	"""Test setting header when http_options is a types.HttpOptions Pydantic model."""
	from google.genai import types

	pydantic_opts = types.HttpOptions(timeout=30, headers={'custom-header': 'value'})
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake', http_options=pydantic_opts)
	params = chat._get_client_params()
	http_opts = params.get('http_options', {})

	# Verify it extracts and preserves timeout and custom-header
	assert http_opts.get('timeout') == 30
	assert http_opts.get('headers', {}).get('custom-header') == 'value'
	assert http_opts.get('headers', {}).get('x-goog-api-client', '').startswith('browser-use/')


def test_x_goog_api_client_header_with_dict_http_options():
	"""Test setting header when http_options is a dictionary (types.HttpOptionsDict)."""
	from google.genai import types

	dict_opts: types.HttpOptionsDict = {
		'timeout': 45,
		'headers': {'another-header': 'another-value'},
	}
	chat = ChatGoogle(model='gemini-flash-latest', api_key='fake', http_options=dict_opts)
	params = chat._get_client_params()
	http_opts = params.get('http_options', {})

	# Verify it preserves dictionary values and appends the tracking header
	assert http_opts.get('timeout') == 45
	assert http_opts.get('headers', {}).get('another-header') == 'another-value'
	assert http_opts.get('headers', {}).get('x-goog-api-client', '').startswith('browser-use/')
