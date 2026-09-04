import pytest

from browser_use.dom.serializer.html_serializer import HTMLSerializer
from browser_use.dom.views import EnhancedDOMTreeNode, NodeType


def _create_element_node(
	tag_name: str, attributes: dict[str, str] | None = None, children: list[EnhancedDOMTreeNode] | None = None
) -> EnhancedDOMTreeNode:
	node = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name=tag_name.upper(),
		node_value='',
		attributes=attributes or {},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=children or [],
		ax_node=None,
		snapshot_node=None,
	)
	for child in node.children:
		child.parent_node = node
	return node


def _create_text_node(text: str) -> EnhancedDOMTreeNode:
	return EnhancedDOMTreeNode(
		node_id=2,
		backend_node_id=2,
		node_type=NodeType.TEXT_NODE,
		node_name='#text',
		node_value=text,
		attributes={},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=[],
		ax_node=None,
		snapshot_node=None,
	)


def test_html_serializer_filters_hidden_code_case_insensitively():
	serializer = HTMLSerializer()

	hidden_styles = [
		'display: none',
		'display:none',
		'Display: None',
		'DISPLAY:NONE',
		'Display: none;',
		'display : none ;',
		'display:\nnone',
		'display:\t none;',
		'color: red; display: none; font-size: 12px;',
		'COLOR: BLUE; DISPLAY: NONE;',
	]

	for style in hidden_styles:
		code_node = _create_element_node(
			tag_name='code',
			attributes={'style': style},
			children=[_create_text_node('hidden payload')],
		)
		result = serializer.serialize(code_node)
		assert result == '', f'Expected empty string for hidden code with style {style!r}, got: {result!r}'


def test_html_serializer_preserves_visible_code_elements():
	serializer = HTMLSerializer()

	visible_styles = [
		'display: block',
		'display: inline',
		'display: inline-block',
		'color: green;',
		'',
	]

	for style in visible_styles:
		attrs = {'style': style} if style else {}
		code_node = _create_element_node(
			tag_name='code',
			attributes=attrs,
			children=[_create_text_node('visible code content')],
		)
		result = serializer.serialize(code_node)
		assert 'visible code content' in result, f'Expected visible code content for style {style!r}, got: {result!r}'
		assert '<code' in result


from urllib.parse import quote

from browser_use import Browser, BrowserProfile
from browser_use.dom.markdown_extractor import extract_clean_markdown


@pytest.mark.asyncio
async def test_hidden_code_style_matching_is_case_insensitive_end_to_end():
	browser = Browser(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=False,
		)
	)

	try:
		await browser.start()
		observed = {}

		for style in ('display: none', 'Display: None'):
			html = f'<main>visible control</main><code id="snippet" style="{style}">hidden state payload</code>'
			await browser.navigate_to('data:text/html,' + quote(html))

			page = await browser.get_current_page()
			assert page is not None

			attribute = await page.evaluate("() => document.querySelector('#snippet').getAttribute('style')")
			computed = await page.evaluate("() => getComputedStyle(document.querySelector('#snippet')).display")
			markdown, _ = await extract_clean_markdown(browser_session=browser)
			observed[style] = markdown

			assert attribute == style
			assert computed == 'none'

		assert 'hidden state payload' not in observed['display: none']
		assert 'hidden state payload' not in observed['Display: None']
	finally:
		await browser.stop()
