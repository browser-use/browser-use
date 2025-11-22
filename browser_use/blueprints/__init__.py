"""
Blueprint integration package for Browser-Use.

Provides dynamic action discovery and execution from the Blueprint backend.
"""

from browser_use.blueprints.client import BlueprintClient
from browser_use.blueprints.service import BlueprintService
from browser_use.blueprints.views import (
	Blueprint,
	BlueprintExecutionRequest,
	BlueprintExecutionResponse,
	BlueprintListResponse,
)

__all__ = [
	'BlueprintClient',
	'BlueprintService',
	'Blueprint',
	'BlueprintListResponse',
	'BlueprintExecutionRequest',
	'BlueprintExecutionResponse',
]
