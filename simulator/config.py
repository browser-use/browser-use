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
DEFAULT_MODEL = 'qwen3.5-omni-plus-2026-03-15'  # multimodal (text+image); fallback: 'qwen3-vl-plus'
DEFAULT_JUDGE_MODEL = 'qwen3.5-omni-plus-2026-03-15'  # multimodal, for the WebVoyager success judge
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
	max_steps: int = 20
	task_timeout: float = 300.0  # heavy sites under several headed browsers run ~30-50s/step
	max_wait: float = 1.5  # how long to wait to fill a batch before dispatching a partial one (see note below)
	use_vision: bool = True  # send the screenshot to the model each step (multimodal)
	shuffle: bool = False
	seed: int = 0
