"""Regression test for domain-restricted action filtering on an unknown URL.

`ActionRegistry._match_domains` returned True when the URL was empty (`not url`),
so a domain-restricted action was exposed on a blank/unknown page URL — even
though the `page_url is None` path correctly hides such actions. An empty
`page_url` is reachable (e.g. a freshly created about:blank target whose
`target.url` is ''), so this failed open for a security-relevant filter.
"""

from browser_use.tools.registry.service import Registry
from browser_use.tools.registry.views import ActionRegistry


def test_match_domains_fails_closed_on_empty_url():
	# Unrestricted action: always available.
	assert ActionRegistry._match_domains(None, '') is True
	assert ActionRegistry._match_domains(None, 'https://anything.com') is True

	# Domain-restricted action: hidden when the URL is unknown/empty...
	assert ActionRegistry._match_domains(['*.admin.example.com'], '') is False
	# ...matched only against a real, matching URL.
	assert ActionRegistry._match_domains(['*.admin.example.com'], 'https://panel.admin.example.com') is True
	assert ActionRegistry._match_domains(['*.admin.example.com'], 'https://evil.com') is False


def _registry_with_admin_action() -> Registry:
	registry = Registry()

	@registry.action('admin only', domains=['*.admin.example.com'])
	def admin_action():
		pass

	return registry


def test_domain_restricted_action_hidden_on_empty_url():
	registry = _registry_with_admin_action()

	# None (system prompt): restricted action excluded.
	assert 'admin_action' not in registry.get_prompt_description(page_url=None)
	# Empty URL: also excluded now (previously exposed).
	assert 'admin_action' not in registry.get_prompt_description(page_url='')
	# Matching URL: available.
	assert 'admin_action' in registry.get_prompt_description(page_url='https://panel.admin.example.com')


def test_create_action_model_excludes_restricted_action_on_empty_url():
	registry = _registry_with_admin_action()

	empty_url_model = registry.create_action_model(page_url='')
	assert 'admin_action' not in empty_url_model.model_fields

	matching_model = registry.create_action_model(page_url='https://panel.admin.example.com')
	assert 'admin_action' in matching_model.model_fields
