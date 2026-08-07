from browser_use.agent.views import ActionResult
from browser_use.tools.registry.service import Registry
from browser_use.tools.service import Tools


def test_registry_action_accepts_governance_metadata():
	"""Custom actions can expose governance metadata for CI audit checks."""
	registry = Registry()

	@registry.action(
		'Dangerous write action',
		risk_tags=('browser_interaction', 'data_entry'),
		requires_human_review=True,
	)
	async def dangerous_write(text: str):
		return ActionResult(extracted_content=text)

	action = registry.registry.actions['dangerous_write']
	assert action.risk_tags == ('browser_interaction', 'data_entry')
	assert action.requires_human_review is True


def test_builtin_sensitive_actions_expose_governance_metadata():
	"""Built-in browser actions keep a CI-checkable governance contract."""
	registry = Tools().registry.registry.actions

	expected_tags = {
		'search': {'navigation', 'network'},
		'navigate': {'navigation', 'network'},
		'go_back': {'navigation', 'browser_state'},
		'click': {'browser_interaction'},
		'input': {'browser_interaction', 'data_entry'},
		'upload_file': {'browser_interaction', 'file_upload', 'data_exfiltration'},
		'switch': {'tab_management', 'browser_state'},
		'close': {'tab_management', 'browser_state'},
		'extract': {'data_capture'},
		'search_page': {'page_inspection'},
		'find_elements': {'page_inspection'},
		'scroll': {'browser_interaction'},
		'send_keys': {'browser_interaction', 'keyboard_input'},
		'find_text': {'browser_interaction', 'page_inspection'},
		'screenshot': {'data_capture'},
		'save_as_pdf': {'data_capture', 'file_write'},
		'dropdown_options': {'page_inspection'},
		'select_dropdown': {'browser_interaction', 'data_entry'},
		'write_file': {'file_write'},
		'replace_file': {'file_write'},
		'read_file': {'file_read', 'data_capture'},
		'evaluate': {'browser_interaction', 'script_execution'},
	}
	unclassified_low_risk_actions = {'done', 'wait'}
	allowed_tags = {tag for tags in expected_tags.values() for tag in tags}

	assert set(registry) - unclassified_low_risk_actions == set(expected_tags)

	for action_name, required_tags in expected_tags.items():
		action = registry[action_name]
		assert required_tags.issubset(set(action.risk_tags)), action_name
		assert set(action.risk_tags).issubset(allowed_tags), action_name


def test_high_risk_builtin_actions_are_marked_for_human_review():
	"""High-risk built-ins are discoverable by CI before runtime policies exist."""
	registry = Tools().registry.registry.actions

	assert registry['upload_file'].requires_human_review is True
	assert registry['evaluate'].requires_human_review is True
