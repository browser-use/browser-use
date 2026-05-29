# simulator

A small, transparent harness for running [WebVoyager](https://github.com/MinorJerry/WebVoyager)
and GAIA-web tasks with browser-use at scale: run many tasks **in parallel** (each
in its own headed window) with **batched LLM inference**, **capture** full per-step
trajectories, and **evaluate** them offline.

LLM: Alibaba DashScope / Qwen via the `ChatDashScope` provider (`qwen-max` to run,
`qwen-vl-max` as the multimodal success judge). Set `DASHSCOPE_API_KEY`.

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
  scripts/       standalone experiments
    analysis.py    WebArena vs WebVoyager context-length study
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

# capture full trajectories (reference answer baked into each task's meta.json)
python -m simulator capture --task-num 9 --batch-size 3 --out-dir simulator/runs/my_run

# did each task COMPLETE CORRECTLY? WebVoyager judge, grounded in the reference answer
python -m simulator eval simulator/runs/my_run                # --model qwen-vl-max --k 2

# can the recorded context reproduce each step's action offline?
python -m simulator eval simulator/runs/my_run --mode replay  # --model qwen-max

# context-length experiment
python -m simulator.scripts.analysis structure | measure | compare
```

The `success` judge sees the task + the agent's answer + the **reference answer**
(ground truth) + the last `k` screenshots and returns SUCCESS / NOT SUCCESS
(temperature 0). Both eval modes read only captured files; neither opens a browser.

## Tests

```bash
uv run pytest -vxs simulator/tests
```
