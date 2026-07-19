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


def test_serializer_decodes_data_url_image():
	"""Test that base64 data URL images are decoded into inline bytes."""
	import base64

	from browser_use.llm.google.serializer import GoogleMessageSerializer
	from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, UserMessage

	raw_bytes = b'fake-png-bytes'
	data_url = 'data:image/png;base64,' + base64.b64encode(raw_bytes).decode()
	message = UserMessage(
		content=[
			ContentPartTextParam(text='What is in this image?'),
			ContentPartImageParam(image_url=ImageURL(url=data_url, media_type='image/png')),
		]
	)

	contents, _ = GoogleMessageSerializer.serialize_messages([message])
	parts = contents[0].parts

	assert parts[0].text == 'What is in this image?'
	assert parts[1].inline_data is not None
	assert parts[1].inline_data.data == raw_bytes
	assert parts[1].inline_data.mime_type == 'image/png'


def test_serializer_passes_through_remote_image_url():
	"""Test that a plain https image URL is passed through instead of being base64-decoded."""
	from browser_use.llm.google.serializer import GoogleMessageSerializer
	from browser_use.llm.messages import ContentPartImageParam, ImageURL, UserMessage

	url = 'https://example.com/images/photo.png'
	message = UserMessage(content=[ContentPartImageParam(image_url=ImageURL(url=url, media_type='image/png'))])

	# Used to raise ValueError because the serializer assumed every image URL is a data: URL
	contents, _ = GoogleMessageSerializer.serialize_messages([message])
	part = contents[0].parts[0]

	assert part.file_data is not None
	assert part.file_data.file_uri == url
	assert part.file_data.mime_type == 'image/png'
