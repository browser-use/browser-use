from urllib.parse import quote

import pytest

from browser_use.dom.markdown_extractor import extract_clean_markdown


@pytest.mark.parametrize(
	'style',
	[
		'display: none',
		'Display: None',
		'DISPLAY:\tNONE',
		'color: red; display : none !important',
	],
)
async def test_hidden_code_inline_style_is_case_insensitive(browser_session, style: str):
	html = f'<main>visible control</main><code id="snippet" style="{style}">hidden state payload</code>'
	await browser_session.navigate_to('data:text/html,' + quote(html))

	page = await browser_session.get_current_page()
	assert page is not None
	computed_display = await page.evaluate("() => getComputedStyle(document.querySelector('#snippet')).display")
	markdown, _ = await extract_clean_markdown(browser_session=browser_session)

	assert computed_display == 'none'
	assert 'visible control' in markdown
	assert 'hidden state payload' not in markdown
