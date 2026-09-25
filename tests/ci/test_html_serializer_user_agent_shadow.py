from urllib.parse import quote

from browser_use.dom.markdown_extractor import extract_clean_markdown


async def test_select_options_are_not_duplicated_by_user_agent_shadow_roots(browser_session):
	html = '<p>Plan</p><select id="plan"><option>Basic</option><option>Pro</option><option>Enterprise</option></select>'
	await browser_session.navigate_to('data:text/html,' + quote(html))

	markdown, _ = await extract_clean_markdown(browser_session=browser_session)

	assert 'BasicBasic' not in markdown
	assert 'ProPro' not in markdown
	assert 'EnterpriseEnterprise' not in markdown
	for option in ('Basic', 'Pro', 'Enterprise'):
		assert markdown.count(option) == 1, f'{option!r} should appear once in: {markdown!r}'


async def test_author_open_shadow_root_content_is_still_extracted(browser_session):
	html = (
		'<p>Support</p><support-badge></support-badge>'
		'<script>customElements.define("support-badge", class extends HTMLElement {'
		' constructor() { super(); this.attachShadow({mode: "open"}).innerHTML = "<button>Chat with support</button>"; }'
		'});</script>'
	)
	await browser_session.navigate_to('data:text/html,' + quote(html))

	markdown, _ = await extract_clean_markdown(browser_session=browser_session)

	assert 'Chat with support' in markdown
