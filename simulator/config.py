"""Shared configuration: paths, constants, and the RunConfig dataclass."""

from __future__ import annotations

import os
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

# --- TreeSparseAttention server (OpenAI-compatible, served on spark01) ----- #
# Point the agent LLM at the local TSA server instead of DashScope/Qwen. The TSA
# server has no server-side json_schema (xgrammar absent), so structured output is
# requested via the system prompt and parsed from the text (see core/runner.py).
# Reach it via an SSH tunnel, e.g.:
#   ssh -N -L 10000:<container-ip>:10000 shiqihe@spark01.eecs.umich.edu
USE_TSA = os.environ.get('USE_TSA', '1').lower() not in ('0', 'false', 'no')
TSA_BASE_URL = os.environ.get('TSA_BASE_URL', 'http://localhost:10000/v1')
TSA_MODEL = os.environ.get('TSA_MODEL', 'tree-sparse')
TSA_API_KEY = os.environ.get('TSA_API_KEY', 'EMPTY')  # TSA ignores auth

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
