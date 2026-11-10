"""Anonymized telemetry for Browser Use: counts and names only; ANONYMIZED_TELEMETRY=false turns it off."""

from typing import TYPE_CHECKING

# Type stubs for lazy imports
if TYPE_CHECKING:
	from browser_use.telemetry.service import ProductTelemetry
	from browser_use.telemetry.views import AgentTelemetryEvent, BaseTelemetryEvent

# Lazy imports mapping
_LAZY_IMPORTS = {
	'ProductTelemetry': ('browser_use.telemetry.service', 'ProductTelemetry'),
	'BaseTelemetryEvent': ('browser_use.telemetry.views', 'BaseTelemetryEvent'),
	'AgentTelemetryEvent': ('browser_use.telemetry.views', 'AgentTelemetryEvent'),
}


def __getattr__(name: str):
	"""Lazy import mechanism for telemetry components."""
	if name in _LAZY_IMPORTS:
		module_path, attr_name = _LAZY_IMPORTS[name]
		try:
			from importlib import import_module

			module = import_module(module_path)
			attr = getattr(module, attr_name)
			# Cache the imported attribute in the module's globals
			globals()[name] = attr
			return attr
		except ImportError as e:
			raise ImportError(f'Failed to import {name} from {module_path}: {e}') from e
	from browser_use.legacy import removed_name

	raise removed_name(__name__, name)  # 0.x names: the removed error naming the 1.0 answer


__all__ = ['AgentTelemetryEvent', 'BaseTelemetryEvent', 'ProductTelemetry']
