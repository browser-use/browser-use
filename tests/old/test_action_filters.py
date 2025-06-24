from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from browser_use.browser.types import Page
from browser_use.controller.registry.service import Registry
from browser_use.controller.registry.views import ActionRegistry, RegisteredAction


class EmptyParamModel(BaseModel):
	pass


class TestActionFilters:
	def test_get_prompt_description_no_filters(self):
		"""Test that system prompt only includes actions with no filters"""
		registry = ActionRegistry()

		# Add actions with and without filters
		no_filter_action = RegisteredAction(
			name='no_filter_action',
			description='Action with no filters',
			function=lambda: None,
			param_model=EmptyParamModel,
			domains=None,
			page_filter=None,
		)

		page_filter_action = RegisteredAction(
			name='page_filter_action',
			description='Action with page filter',
			function=lambda: None,
			param_model=EmptyParamModel,
			domains=None,
			page_filter=lambda page: True,
		)

		domain_filter_action = RegisteredAction(
			name='domain_filter_action',
			description='Action with domain filter',
			function=lambda: None,
			param_model=EmptyParamModel,
			domains=['example.com'],
			page_filter=None,
		)

		registry.actions = {
			'no_filter_action': no_filter_action,
			'page_filter_action': page_filter_action,
			'domain_filter_action': domain_filter_action,
		}

		# System prompt (no page) should only include actions with no filters
		system_description = registry.get_prompt_description()
		assert 'no_filter_action' in system_description
		assert 'page_filter_action' not in system_description
		assert 'domain_filter_action' not in system_description

	def test_page_filter_matching(self):
		"""Test that page filters work correctly"""
		registry = ActionRegistry()

		# Create a mock page
		mock_page = MagicMock(spec=Page)
		mock_page.url = 'https://example.com/page'

		# Create actions with different page filters
		matching_action = RegisteredAction(
			name='matching_action',
			description='Action with matching page filter',
			function=lambda: None,
			param_model=EmptyParamModel,
			domains=None,
			page_filter=lambda page: 'example.com' in page.url,
		)

		non_matching_action = RegisteredAction(
			name='non_matching_action',
			description='Action with non-matching page filter',
			function=lambda: None,
			param_model=EmptyParamModel,
			domains=None,
			page_filter=lambda page: 'other.com' in page.url,
		)

		registry.actions = {'matching_action': matching_action, 'non_matching_action': non_matching_action}

		# Page-specific description should only include matching actions
		page_description = registry.get_prompt_description(mock_page)
		assert 'matching_action' in page_description
		assert 'non_matching_action' not in page_description

	def test_domain_filter_matching(self):
		"""Test that domain filters work correctly with glob patterns"""
		registry = ActionRegistry()

		# Create actions with different domain patterns
		actions = {
			'exact_match': RegisteredAction(
				name='exact_match',
				description='Exact domain match',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['example.com'],
				page_filter=None,
			),
			'subdomain_match': RegisteredAction(
				name='subdomain_match',
				description='Subdomain wildcard match',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['*.example.com'],
				page_filter=None,
			),
			'prefix_match': RegisteredAction(
				name='prefix_match',
				description='Prefix wildcard match',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['example*'],
				page_filter=None,
			),
			'non_matching': RegisteredAction(
				name='non_matching',
				description='Non-matching domain',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['other.com'],
				page_filter=None,
			),
		}

		registry.actions = actions

		# Test exact domain match
		mock_page = MagicMock(spec=Page)
		mock_page.url = 'https://example.com/page'

		exact_match_description = registry.get_prompt_description(mock_page)
		assert 'exact_match' in exact_match_description
		assert 'non_matching' not in exact_match_description

		# Test subdomain match
		mock_page.url = 'https://sub.example.com/page'
		subdomain_match_description = registry.get_prompt_description(mock_page)
		assert 'subdomain_match' in subdomain_match_description
		assert 'exact_match' not in subdomain_match_description

		# Test prefix match
		mock_page.url = 'https://example123.org/page'
		prefix_match_description = registry.get_prompt_description(mock_page)
		assert 'prefix_match' in prefix_match_description

	def test_domain_and_page_filter_together(self):
		"""Test that actions can be filtered by both domain and page filter"""
		registry = ActionRegistry()

		# Create a mock page
		mock_page = MagicMock(spec=Page)
		mock_page.url = 'https://example.com/admin'

		# Actions with different combinations of filters
		actions = {
			'domain_only': RegisteredAction(
				name='domain_only',
				description='Domain filter only',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['example.com'],
				page_filter=None,
			),
			'page_only': RegisteredAction(
				name='page_only',
				description='Page filter only',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=None,
				page_filter=lambda page: 'admin' in page.url,
			),
			'both_matching': RegisteredAction(
				name='both_matching',
				description='Both filters matching',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['example.com'],
				page_filter=lambda page: 'admin' in page.url,
			),
			'both_one_fail': RegisteredAction(
				name='both_one_fail',
				description='One filter fails',
				function=lambda: None,
				param_model=EmptyParamModel,
				domains=['other.com'],
				page_filter=lambda page: 'admin' in page.url,
			),
		}

		registry.actions = actions

		# Check that only actions with matching filters are included
		description = registry.get_prompt_description(mock_page)
		assert 'domain_only' in description  # Domain matches
		assert 'page_only' in description  # Page filter matches
		assert 'both_matching' in description  # Both filters match
		assert 'both_one_fail' not in description  # Domain filter fails

		# Test with different URL where page filter fails
		mock_page.url = 'https://example.com/dashboard'
		description = registry.get_prompt_description(mock_page)
		assert 'domain_only' in description  # Domain matches
		assert 'page_only' not in description  # Page filter fails
		assert 'both_matching' not in description  # Page filter fails
		assert 'both_one_fail' not in description  # Domain filter fails

	@pytest.mark.asyncio
	async def test_registry_action_decorator(self):
		"""Test the action decorator with filters"""
		registry = Registry()

		# Define actions with different filters
		@registry.action(
			description='No filter action',
		)
		def no_filter_action():
			pass

		@registry.action(description='Domain filter action', domains=['example.com'])
		def domain_filter_action():
			pass

		@registry.action(description='Page filter action', page_filter=lambda page: 'admin' in page.url)
		def page_filter_action():
			pass

		# Check that system prompt only includes the no_filter_action
		system_description = registry.get_prompt_description()
		assert 'No filter action' in system_description
		assert 'Domain filter action' not in system_description
		assert 'Page filter action' not in system_description

		# Check that page-specific prompt includes the right actions
		mock_page = MagicMock(spec=Page)
		mock_page.url = 'https://example.com/admin'

		page_description = registry.get_prompt_description(mock_page)
		assert 'Domain filter action' in page_description
		assert 'Page filter action' in page_description

	@pytest.mark.asyncio
	async def test_action_model_creation(self):
		"""Test that action models are created correctly with filters"""
		registry = Registry()

		# Define actions with different filters
		@registry.action(
			description='No filter action',
		)
		def no_filter_action():
			pass

		@registry.action(description='Domain filter action', domains=['example.com'])
		def domain_filter_action():
			pass

		@registry.action(description='Page filter action', page_filter=lambda page: 'admin' in page.url)
		def page_filter_action():
			pass

		@registry.action(description='Both filters action', domains=['example.com'], page_filter=lambda page: 'admin' in page.url)
		def both_filters_action():
			pass

		# Initial action model should only include no_filter_action
		initial_model = registry.create_action_model()
		assert 'no_filter_action' in initial_model.model_fields
		assert 'domain_filter_action' not in initial_model.model_fields
		assert 'page_filter_action' not in initial_model.model_fields
		assert 'both_filters_action' not in initial_model.model_fields

		# Action model with matching page should include all matching actions
		mock_page = MagicMock(spec=Page)
		mock_page.url = 'https://example.com/admin'

		page_model = registry.create_action_model(page=mock_page)
		assert 'no_filter_action' in page_model.model_fields
		assert 'domain_filter_action' in page_model.model_fields
		assert 'page_filter_action' in page_model.model_fields
		assert 'both_filters_action' in page_model.model_fields

		# Action model with non-matching domain should exclude domain-filtered actions
		mock_page.url = 'https://other.com/admin'
		non_matching_domain_model = registry.create_action_model(page=mock_page)
		assert 'no_filter_action' in non_matching_domain_model.model_fields
		assert 'domain_filter_action' not in non_matching_domain_model.model_fields
		assert 'page_filter_action' in non_matching_domain_model.model_fields
		assert 'both_filters_action' not in non_matching_domain_model.model_fields

		# Action model with non-matching page filter should exclude page-filtered actions
		mock_page.url = 'https://example.com/dashboard'
		non_matching_page_model = registry.create_action_model(page=mock_page)
		assert 'no_filter_action' in non_matching_page_model.model_fields
		assert 'domain_filter_action' in non_matching_page_model.model_fields
		assert 'page_filter_action' not in non_matching_page_model.model_fields
		assert 'both_filters_action' not in non_matching_page_model.model_fields
