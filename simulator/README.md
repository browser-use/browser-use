# simulator

A small, transparent harness for running [WebVoyager](https://github.com/MinorJerry/WebVoyager)
and GAIA-web tasks with browser-use at scale: run many tasks **in parallel** (each
in its own headed window) with **batched LLM inference**, **capture** full per-step
trajectories, and **evaluate** them offline.

LLM: Alibaba DashScope / Qwen via the `ChatDashScope` provider. Default model
`qwen3.5-omni-plus-2026-03-15` (multimodal) — used both to drive the agent with
vision on and as the success judge. Structured output is parsed leniently
(markdown ` ``` ` fences and single-element array wrappers are unwrapped). Set
`DASHSCOPE_API_KEY`.

## Layout

```
simulator/
  config.py      constants + RunConfig
  tasks.py       WebVoyager + GAIA loaders + reference answers
  core/          the run engine
    batching.py    BatchCoordinator (the batch barrier) + BatchLLMProxy
    recorder.py    TrajectoryRecorder + RecordingProxy
    runner.py      worker pool + run_batch + run_capture
  eval/          offline evaluation
    success.py     WebVoyager multimodal judge (reference-aware) -> SUCCESS/NOT SUCCESS
    replay.py      action-replay fidelity
    common.py      shared client + task-dir discovery
  scripts/       standalone experiments / tooling
    download_data.py     fetch the third-party datasets
    analysis.py          WebArena vs WebVoyager context-length study
    trajectory_stats.py  context/output token-length stats over a captured run
    merge_runs.py        success-preferring merge of two runs (+ optional HF upload)
  __main__.py    CLI
  data/          datasets + reference answers     runs/  generated output (gitignored)
  tests/         unit tests (no network)
```

Two sub-packages (`core`, `eval`) group genuinely cohesive code; everything else
stays top-level. Not one giant file, not a sub-package per module.

## Datasets (both included)

- `data/webvoyager_data.jsonl` — 643 tasks, 15 live sites. Reference answers in
  `data/reference_answer.json` (per-site, types `golden`/`possible`).
- `data/gaia_web.jsonl` — 90 GAIA web tasks, each with an inline ground-truth answer.

`--source {both,webvoyager,gaia}` selects which to draw from (default `both`).

## Usage

```bash
# one-time: fetch the datasets (they are third-party + gitignored)
python -m simulator.scripts.download_data

# run in parallel (no recording)
python -m simulator run --task-num 9 --batch-size 3 --source both

# capture full trajectories (resumable: re-running skips tasks already captured)
python -m simulator capture --task-num 9 --batch-size 3 --out-dir simulator/runs/my_run

# did each task COMPLETE CORRECTLY? WebVoyager judge, grounded in the reference answer
# (resumable: reuses existing webvoyager_eval.json verdicts; judge defaults to the omni model)
python -m simulator eval simulator/runs/my_run                # --k 2

# can the recorded context reproduce each step's action offline?
python -m simulator eval simulator/runs/my_run --mode replay

# token-length stats over a captured run (text only; per domain / overall / by step)
python -m simulator.scripts.trajectory_stats context simulator/runs/my_run
python -m simulator.scripts.trajectory_stats output  simulator/runs/my_run

# success-preferring merge of another run into this one (+ optional HF upload)
python -m simulator.scripts.merge_runs simulator/runs/my_run simulator/runs/other_run

# WebArena vs WebVoyager context-length experiment
python -m simulator.scripts.analysis structure | measure | compare
```

The `success` judge sees the task + the agent's answer + the **reference answer**
(ground truth) + the last `k` screenshots and returns SUCCESS / NOT SUCCESS
(temperature 0). Both eval modes read only captured files; neither opens a browser.

## Agent prompt & robustness

During `run`/`capture` the agent's system prompt is extended (see `config.py`) with a
**CAPTCHA/anti-bot nudge** (try one recovery action, else switch strategy — never stall
or punt to the user) and a **thinking nudge** (fill the JSON `thinking` with 2–4
deliberate sentences, then emit exactly one JSON object). Per-call LLM latency is bounded
by `--llm-timeout` (default 150 s). The success judge is instructed to put its
`SUCCESS`/`NOT SUCCESS` verdict on the first line for reliable parsing.

## Tests

```bash
uv run pytest -vxs simulator/tests
```
