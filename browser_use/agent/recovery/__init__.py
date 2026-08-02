"""Recovery framework — deterministic failure repair before LLM escalation.

The public surface mirrors the layering used by the engine:

- ``base``: contracts (``RecoveryStrategy``) and data models
  (``RecoveryContext``, ``RecoveryResult``, enums).
- ``engine``: dispatch (``RecoveryEngine``) and the execution stage
  (``RecoveryStage``).
- ``strategies``: concrete repairs + composite chains.
- ``stats``: telemetry (``RecoveryStats``).
"""

from browser_use.agent.recovery.base import (
	ActionKind,
	RecoveryContext,
	RecoveryCost,
	RecoveryOutcome,
	RecoveryPhase,
	RecoveryResult,
	RecoveryStrategy,
	infer_action_kind,
)
from browser_use.agent.recovery.engine import RecoveryEngine, RecoveryStage
from browser_use.agent.recovery.stats import RecoveryStats
from browser_use.agent.recovery.strategies import (
	BrowserCrashRecovery,
	CompositeRecovery,
	NavigationRecovery,
	OverlayRecovery,
	RelocateRecovery,
	RetryRecovery,
	ScrollRecovery,
	TimeoutRecovery,
	WaitRecovery,
	default_composite,
	default_strategies,
)

__all__ = [
	'ActionKind',
	'BrowserCrashRecovery',
	'CompositeRecovery',
	'NavigationRecovery',
	'OverlayRecovery',
	'RecoveryContext',
	'RecoveryCost',
	'RecoveryEngine',
	'RecoveryOutcome',
	'RecoveryPhase',
	'RecoveryResult',
	'RecoveryStage',
	'RecoveryStats',
	'RecoveryStrategy',
	'RelocateRecovery',
	'RetryRecovery',
	'ScrollRecovery',
	'TimeoutRecovery',
	'WaitRecovery',
	'default_composite',
	'default_strategies',
	'infer_action_kind',
]
