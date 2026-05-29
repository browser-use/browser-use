"""Shared configuration: paths, constants, and the RunConfig dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --- paths ---------------------------------------------------------------- #
PKG_DIR = Path(__file__).parent
DATA_DIR = PKG_DIR / 'data'
RUNS_DIR = PKG_DIR / 'runs'
WEBVOYAGER_JSONL = DATA_DIR / 'webvoyager_data.jsonl'
GAIA_JSONL = DATA_DIR / 'gaia_web.jsonl'
REFERENCE_JSON = DATA_DIR / 'reference_answer.json'
WEBARENA_JSON = DATA_DIR / 'webarena_test.raw.json'

# --- provider ------------------------------------------------------------- #
DEFAULT_MODEL = 'qwen-max'
DEFAULT_JUDGE_MODEL = 'qwen-vl-max'  # multimodal, for the WebVoyager success judge
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# Appended to every agent's system prompt so it routes around CAPTCHAs itself
# instead of stalling (we intentionally do not pause-and-wait in the simulator).
CAPTCHA_NUDGE = (
	'If you encounter a CAPTCHA, reCAPTCHA, bot-detection, or a "verify you are human" wall, '
	'do NOT stop and do NOT repeatedly wait for it to clear. Immediately try an alternative '
	"approach to accomplish the task: a different navigation path, the site's own search, a "
	'different section of the site, or an alternative reputable source. Keep making progress.'
)


@dataclass(slots=True)
class RunConfig:
	"""Everything the run/capture flows need to execute a batch of tasks."""

	task_num: int = 2
	batch_size: int = 2
	source: str = 'both'  # 'webvoyager' | 'gaia' | 'both'
	model: str = DEFAULT_MODEL
	max_steps: int = 15
	task_timeout: float = 180.0
	max_wait: float = 8.0  # max seconds the batch coordinator waits to fill a batch
	use_vision: bool = False  # qwen-max is text-only
	shuffle: bool = False
	seed: int = 0
