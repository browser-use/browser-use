"""
Blueprint service for managing dynamic action discovery and registration.

Handles blueprint caching, domain tracking, and dynamic tool registration.
"""

import json
import logging
import os
from urllib.parse import urlparse

from pydantic import BaseModel, create_model

from browser_use.agent.views import ActionResult
from browser_use.blueprints.client import BlueprintClient
from browser_use.blueprints.views import Blueprint
from browser_use.tools.service import Tools

logger = logging.getLogger(__name__)


class BlueprintService:
	"""
	Service for managing dynamic blueprint actions.

	Responsibilities:
	- Track current domain and detect changes
	- Cache blueprints per domain
	- Dynamically register/unregister actions in Tools registry
	- Execute blueprints via BlueprintClient
	"""

	def __init__(
		self,
		client: BlueprintClient | None = None,
		base_url: str = 'https://blueprint-production-cdc8.up.railway.app',
		api_key: str | None = None,
	):
		"""
		Initialize the blueprint service.

		Args:
		    client: Optional BlueprintClient instance (creates one if not provided)
		    base_url: Base URL for blueprint backend (default: https://blueprint-production-cdc8.up.railway.app)
		    api_key: API key for authentication (reads from BROWSER_USE_API_KEY env var if not provided)

		Raises:
		    ValueError: If BROWSER_USE_API_KEY is not set and no api_key provided
		"""
		# Check for API key if client not provided
		if client is None:
			resolved_api_key = api_key or os.getenv('BROWSER_USE_API_KEY')
			if not resolved_api_key:
				raise ValueError(
					'BROWSER_USE_API_KEY environment variable not set. '
					'Blueprint service requires authentication. '
					'Get your API key at https://cloud.browser-use.com/new-api-key'
				)
			self.client = BlueprintClient(base_url=base_url, api_key=resolved_api_key)
		else:
			self.client = client

		self._blueprint_cache: dict[str, list[Blueprint]] = {}
		self._current_domain: str | None = None
		self._registered_actions: set[str] = set()

	async def close(self) -> None:
		"""Close the client connection."""
		await self.client.close()

	def _extract_domain(self, url: str | None) -> str | None:
		"""
		Extract full hostname from URL (including subdomains).

		The backend's blueprint matching is smart enough to match subdomains,
		so we pass the full hostname (e.g., 'dockertransport.dispatchtrack.com').

		Args:
		    url: Full URL or None

		Returns:
		    Full hostname with subdomains (e.g., 'dockertransport.dispatchtrack.com') or None
		"""
		if not url:
			return None

		try:
			parsed = urlparse(url)
			hostname = parsed.hostname
			if not hostname:
				return None

			logger.debug(f'Extracted hostname: {hostname}')
			return hostname
		except Exception as e:
			logger.debug(f'Failed to extract hostname from {url}: {e}')
			return None

	async def update_blueprints_for_url(self, url: str | None, tools: Tools) -> None:
		"""
		Update available blueprints based on current URL.

		If domain has changed, unregister old blueprints and register new ones.
		Uses caching to avoid redundant API calls.

		Args:
		    url: Current page URL
		    tools: Tools instance to register actions with
		"""
		domain = self._extract_domain(url)

		# If no domain or same domain, nothing to do
		if domain == self._current_domain:
			return

		logger.debug(f'📘 Domain changed: {self._current_domain} -> {domain}')

		# Unregister old blueprints if we had any
		if self._current_domain and self._registered_actions:
			await self._unregister_domain_blueprints(tools)

		# Update current domain
		self._current_domain = domain

		# If no domain (e.g., about:blank), stop here
		if not domain:
			return

		# Fetch and register blueprints for new domain
		await self._fetch_and_register_blueprints(domain, tools)

		# Log summary of available blueprint actions
		if self._registered_actions:
			logger.info(f'📘 Blueprint actions now available: {", ".join(self._registered_actions)}')

	async def _fetch_and_register_blueprints(self, domain: str, tools: Tools) -> None:
		"""
		Fetch blueprints for domain (from cache or API) and register them.

		Args:
		    domain: Domain to fetch blueprints for
		    tools: Tools instance to register actions with
		"""
		# Check cache first
		if domain in self._blueprint_cache:
			blueprints = self._blueprint_cache[domain]
			logger.debug(f'📘 Using {len(blueprints)} cached blueprints for {domain}')
		else:
			# Fetch from API
			blueprints = await self.client.list_blueprints(domain)
			self._blueprint_cache[domain] = blueprints

			if blueprints:
				logger.info(f'📘 Discovered {len(blueprints)} blueprints for {domain}')

		# Register each blueprint as an action
		for blueprint in blueprints:
			await self._register_blueprint_action(blueprint, tools)

	async def _register_blueprint_action(self, blueprint: Blueprint, tools: Tools) -> None:
		"""
		Register a blueprint as a dynamic action in the Tools registry.

		Args:
		    blueprint: Blueprint to register
		    tools: Tools instance to register with
		"""
		action_name = blueprint.metadata.blueprint_id

		# Extract group and endpoint from blueprint_id (format: group_endpoint)
		parts = action_name.split('_', 1)
		if len(parts) == 2:
			group, endpoint = parts
		else:
			# Fallback: try to parse from blueprint_endpoint URL
			# Format: http://localhost:8080/group/endpoint
			endpoint_url = blueprint.metadata.blueprint_endpoint
			url_parts = endpoint_url.rstrip('/').split('/')
			if len(url_parts) >= 2:
				group = url_parts[-2]
				endpoint = url_parts[-1]
			else:
				logger.warning(f'Cannot parse group/endpoint from {action_name}, skipping')
				return

		# Skip if already registered
		if action_name in self._registered_actions:
			logger.debug(f'Blueprint {action_name} already registered, skipping')
			return

		# Build parameter model from blueprint schema
		param_model = self._create_param_model(blueprint)

		# Create action wrapper function that follows the Tools pattern
		# The function accepts a params object of the param_model type
		async def blueprint_action_wrapper(params: BaseModel) -> ActionResult:
			"""Wrapper that executes the blueprint via the backend."""
			# Convert params model to dict (filter out None values)
			params_dict = {k: v for k, v in params.model_dump().items() if v is not None}

			print(f'\n{"=" * 60}')
			print(f'📘 Executing Blueprint: {action_name}')
			print(f'{"=" * 60}')
			print('Parameters:')
			for key, value in params_dict.items():
				print(f'  {key}: {value}')
			print(f'{"=" * 60}\n')

			logger.debug(f'Executing blueprint {action_name} with params: {list(params_dict.keys())}')

			# Execute via client
			response = await self.client.execute_blueprint(
				group=group, endpoint=endpoint, parameters=params_dict, blueprint_id=action_name
			)

			print(f'\n{"=" * 60}')
			print(f'📘 Blueprint Response: {action_name}')
			print(f'{"=" * 60}')
			print(f'Success: {response.success}')
			if response.success:
				print('Data:')
				try:
					print(json.dumps(response.data, indent=2, ensure_ascii=False))
				except Exception:
					print(f'  {response.data}')
			else:
				error_msg = response.error.message if response.error else 'Unknown error'
				print(f'Error: {error_msg}')
				if response.error and response.error.missing_parameters:
					print(f'Missing parameters: {response.error.missing_parameters}')
			print(f'{"=" * 60}\n')

			# Convert response to ActionResult
			if response.success:
				# Format data as JSON string for extracted_content
				if response.data:
					try:
						data_str = json.dumps(response.data, indent=2, ensure_ascii=False)
						extracted_content = f'Blueprint {action_name} result:\n{data_str}'
						# For long_term_memory, create a shorter summary if data is large
						if len(data_str) > 500:
							# Truncate for memory
							memory = f'Executed blueprint {action_name}:\n{data_str[:500]}...'
						else:
							memory = f'Executed blueprint {action_name}:\n{data_str}'
					except Exception:
						extracted_content = f'Blueprint {action_name} result: {response.data}'
						memory = f'Executed blueprint {action_name}: {response.data}'
				else:
					extracted_content = f'Blueprint {action_name} completed successfully'
					memory = f'Executed blueprint {action_name} successfully'

				return ActionResult(
					extracted_content=extracted_content,
					long_term_memory=memory,
				)
			else:
				error_msg = response.error.message if response.error else 'Unknown error'
				logger.warning(f'Blueprint {action_name} failed: {error_msg}')
				return ActionResult(error=f'Blueprint execution failed: {error_msg}')

		# Set the function name to match the blueprint ID
		# This is crucial because the registry uses the function's __name__ as the action name
		blueprint_action_wrapper.__name__ = action_name

		# Get domains from blueprint metadata and add wildcard patterns
		domains = blueprint.metadata.domains if blueprint.metadata.domains else None
		if domains:
			# Add wildcard patterns for each domain (e.g., 'github.com' -> ['github.com', '*.github.com'])
			expanded_domains = []
			for domain in domains:
				expanded_domains.append(domain)
				if not domain.startswith('*.'):
					expanded_domains.append(f'*.{domain}')
			domains = expanded_domains

		# Register the action with domain filtering
		try:
			tools.registry.action(
				description=blueprint.description,
				param_model=param_model,
				domains=domains,
			)(blueprint_action_wrapper)

			self._registered_actions.add(action_name)
			logger.info(f'📘 ✅ Registered blueprint action: {action_name}')
			logger.info(f'   Description: {blueprint.description[:150]}...')
			logger.info(f'   Parameters: {list(param_model.model_fields.keys())}')
			logger.info(f'   Domains: {domains}')
		except Exception as e:
			logger.error(f'Failed to register blueprint {action_name}: {e}')

	def _create_param_model(self, blueprint: Blueprint) -> type[BaseModel]:
		"""
		Create a Pydantic model for blueprint parameters.

		Args:
		    blueprint: Blueprint with input schema

		Returns:
		    Pydantic model class
		"""
		schema = blueprint.inputSchema
		fields = {}

		for prop_name, prop_def in schema.properties.items():
			# Determine Python type from JSON schema type
			python_type = self._json_type_to_python(prop_def.get('type', 'string'))

			# Make field optional if not required
			is_required = prop_name in schema.required
			if is_required:
				fields[prop_name] = (python_type, ...)
			else:
				fields[prop_name] = (python_type | None, None)

		# Create dynamic model
		model_name = f'{blueprint.metadata.blueprint_id}_Params'
		return create_model(model_name, **fields)

	def _json_type_to_python(self, json_type: str) -> type:
		"""
		Convert JSON schema type to Python type.

		Args:
		    json_type: JSON schema type string

		Returns:
		    Python type
		"""
		type_mapping = {
			'string': str,
			'number': float,
			'integer': int,
			'boolean': bool,
			'object': dict,
			'array': list,
		}
		return type_mapping.get(json_type, str)

	async def _unregister_domain_blueprints(self, tools: Tools) -> None:
		"""
		Unregister all blueprints registered for the current domain.

		Args:
		    tools: Tools instance to unregister from
		"""
		if not self._registered_actions:
			return

		logger.debug(f'📘 Unregistering {len(self._registered_actions)} blueprint actions')

		for action_name in list(self._registered_actions):
			try:
				tools.registry.unregister_action(action_name)
				logger.debug(f'Unregistered blueprint action: {action_name}')
			except Exception as e:
				logger.debug(f'Failed to unregister {action_name}: {e}')

		self._registered_actions.clear()

	async def __aenter__(self):
		"""Context manager entry."""
		return self

	async def __aexit__(self, exc_type, exc_val, exc_tb):
		"""Context manager exit."""
		await self.close()
