"""WebVoyager + GAIA parallel simulator.

A small, transparent harness for running web-agent tasks in parallel with batched
LLM inference, capturing full per-step trajectories, and evaluating them offline
(WebVoyager task-success judging with reference answers + action-replay fidelity).

  config     constants + RunConfig
  tasks      WebVoyager + GAIA loaders + reference answers
  core/      the run engine: batching, recorder, runner
  eval/      offline evaluation: success (WebVoyager judge) + replay
  scripts/   standalone experiments (analysis: context-length study)
"""

from simulator.config import RunConfig

__all__ = ['RunConfig']
