"""Extension pages in the agent's tab list and reconnect path."""

from browser_use.repl import Repl


async def test_extension_pages_are_hidden_from_agent_tabs_unless_requested(tmp_path):
	"""An extension side panel is not offered as a normal tab, but stays explicitly accessible."""
	repl = Repl(tmp_path)
	try:
		code = (
			'import browser_harness.helpers as h\n'
			"h.cdp = lambda method: {'targetInfos': ["
			"{'type':'page','targetId':'page','url':'https://example.com'}, "
			"{'type':'page','targetId':'blank','url':'about:blank'}, "
			"{'type':'page','targetId':'extension','url':'chrome-extension://example/sidepanel.html'}]}\n"
			"print([tab['targetId'] for tab in list_tabs()])"
		)
		result = await repl.call('exec', code, 30)
		assert result['error'] is None, result
		assert result['output'].strip() == "['page', 'blank']"
		result = await repl.call('exec', "print([tab['targetId'] for tab in list_tabs(include_extensions=True)])", 30)
		assert result['error'] is None, result
		assert result['output'].strip() == "['page', 'blank', 'extension']"
	finally:
		await repl.close()


def test_reconnect_restores_an_explicit_extension_tab(monkeypatch):
	"""A tab the agent explicitly selected is restored by ID even when its URL is an extension page."""
	from browser_harness import helpers

	from browser_use.repl import worker

	seen = []
	monkeypatch.setattr(worker, 'AGENT_TAB', {'id': 'extension', 'lost': True})
	monkeypatch.setattr(helpers, 'current_tab', lambda: {'targetId': 'page', 'url': 'https://example.com'})
	monkeypatch.setattr(helpers, 'switch_tab', lambda target: seen.append(target))
	worker._back_to_agent_tab()
	assert seen == ['extension']
