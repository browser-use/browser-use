"""rrss-arm — Adaptive Rate Management for async Python.

Exports:
        HostCircuitBreaker  — per-host async circuit breaker (closed/open/half_open)
        CircuitOpenError    — raised when a host's circuit is open
        kafca_timeout       — concise async timeout decorator
        kafca_retry         — exponential-backoff async retry decorator

RRSS — Robust, Reliable, Solid, Systematic.
"""

from rrss_arm.circuit import CircuitOpenError, CircuitState, HostCircuitBreaker
from rrss_arm.kafca import kafca_retry, kafca_timeout

__version__ = '0.1.0'

__all__ = [
	'CircuitOpenError',
	'CircuitState',
	'HostCircuitBreaker',
	'kafca_retry',
	'kafca_timeout',
	'__version__',
]
