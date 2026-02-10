"""Structured logging and run directory management for multi-agent orchestration."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from multiagent.config import MultiAgentConfig

logger = logging.getLogger(__name__)


class RunLogger:
	"""Manages run directory creation, config snapshots, and per-step JSON logs."""

	def __init__(self, config: MultiAgentConfig, config_path: str | Path | None = None) -> None:
		self.config = config
		self.config_path = Path(config_path) if config_path else None

		timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
		experiment = config.logging.experiment_name
		self.run_dir = Path(config.logging.run_dir_base) / f'{timestamp}_{experiment}'
		self.steps_dir = self.run_dir / 'steps'
		self.artifacts_dir = self.run_dir / 'artifacts'

		self._setup_dirs()
		self._save_config_snapshot()
		self._setup_python_logging()

	def _setup_dirs(self) -> None:
		self.run_dir.mkdir(parents=True, exist_ok=True)
		self.steps_dir.mkdir(exist_ok=True)
		self.artifacts_dir.mkdir(exist_ok=True)

	def _save_config_snapshot(self) -> None:
		# Save the parsed config as JSON
		snapshot_path = self.run_dir / 'config_snapshot.json'
		snapshot_path.write_text(
			self.config.model_dump_json(indent=2),
			encoding='utf-8',
		)

		# Copy the original YAML if available
		if self.config_path and self.config_path.exists():
			shutil.copy2(self.config_path, self.run_dir / 'config.yaml')

	def _setup_python_logging(self) -> None:
		log_level = getattr(logging, self.config.logging.log_level.upper(), logging.INFO)
		log_file = self.run_dir / 'run.log'

		file_handler = logging.FileHandler(log_file)
		file_handler.setLevel(log_level)
		file_handler.setFormatter(
			logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s')
		)

		# Add to multiagent logger
		ma_logger = logging.getLogger('multiagent')
		ma_logger.setLevel(log_level)
		ma_logger.addHandler(file_handler)

	def log_step(
		self,
		step_number: int,
		agent_inputs: dict[str, Any] | None = None,
		agent_outputs: dict[str, Any] | None = None,
		chosen_action: dict[str, Any] | None = None,
		action_outcome: dict[str, Any] | None = None,
		loop_detected: bool = False,
		failure_signal: str | None = None,
		critic_verdict: str | None = None,
		searcher_used: bool = False,
	) -> None:
		"""Save a per-step JSON log."""
		step_data = {
			'step': step_number,
			'timestamp': datetime.now(timezone.utc).isoformat(),
			'agent_inputs': agent_inputs or {},
			'agent_outputs': agent_outputs or {},
			'chosen_action': chosen_action or {},
			'action_outcome': action_outcome or {},
			'loop_detected': loop_detected,
			'failure_signal': failure_signal,
			'critic_verdict': critic_verdict,
			'searcher_used': searcher_used,
		}

		step_file = self.steps_dir / f'step_{step_number:04d}.json'
		step_file.write_text(json.dumps(step_data, indent=2, default=str), encoding='utf-8')

	def save_artifact(self, name: str, data: str | bytes, step: int | None = None) -> Path:
		"""Save an artifact (screenshot, DOM snapshot, etc.)."""
		prefix = f'step_{step:04d}_' if step is not None else ''
		path = self.artifacts_dir / f'{prefix}{name}'
		if isinstance(data, bytes):
			path.write_bytes(data)
		else:
			path.write_text(data, encoding='utf-8')
		return path

	def log_summary(self, summary: dict[str, Any]) -> None:
		"""Save a final run summary."""
		path = self.run_dir / 'summary.json'
		path.write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
		logger.info(f'Run summary saved to {path}')
