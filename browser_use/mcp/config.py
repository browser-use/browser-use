"""Configuration helpers for the browser-use MCP server."""

from typing import Any


def build_mcp_config_overrides(kwargs: dict[str, Any]) -> dict[str, Any]:
	"""Build transient MCP config overrides from top-level CLI options.

	The MCP server uses the newer ``browser_profile``/``llm`` config shape,
	while the interactive CLI stores options under ``browser``/``model``.
	Do not persist these overrides: MCP launch arguments such as ``--cdp-url``
	are runtime connection details and should only affect this server process.
	"""
	overrides: dict[str, Any] = {}
	browser_profile: dict[str, Any] = {}
	llm: dict[str, Any] = {}

	if kwargs.get('model'):
		llm['model'] = kwargs['model']

	if kwargs.get('headless') is not None:
		browser_profile['headless'] = kwargs['headless']
	if kwargs.get('user_data_dir'):
		browser_profile['user_data_dir'] = kwargs['user_data_dir']
	if kwargs.get('profile_directory'):
		browser_profile['profile_directory'] = kwargs['profile_directory']
	if kwargs.get('cdp_url'):
		browser_profile['cdp_url'] = kwargs['cdp_url']

	window_width = kwargs.get('window_width')
	window_height = kwargs.get('window_height')
	if window_width or window_height:
		browser_profile['window_size'] = {
			'width': window_width or 1920,
			'height': window_height or 1080,
		}

	proxy: dict[str, str] = {}
	if kwargs.get('proxy_url'):
		proxy['server'] = kwargs['proxy_url']
	if kwargs.get('no_proxy'):
		proxy['bypass'] = ','.join([p.strip() for p in kwargs['no_proxy'].split(',') if p.strip()])
	if kwargs.get('proxy_username'):
		proxy['username'] = kwargs['proxy_username']
	if kwargs.get('proxy_password'):
		proxy['password'] = kwargs['proxy_password']
	if proxy:
		browser_profile['proxy'] = proxy

	if browser_profile:
		overrides['browser_profile'] = browser_profile
	if llm:
		overrides['llm'] = llm

	return overrides


def merge_nested_config(base: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
	"""Return ``base`` with MCP runtime overrides applied recursively."""
	if not overrides:
		return base

	merged = dict(base)
	for key, value in overrides.items():
		if isinstance(value, dict) and isinstance(merged.get(key), dict):
			merged[key] = merge_nested_config(merged[key], value)
		else:
			merged[key] = value
	return merged
