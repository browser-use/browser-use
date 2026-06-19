# simulator

A small, transparent harness for running [WebVoyager](https://github.com/MinorJerry/WebVoyager)
and GAIA-web tasks with browser-use at scale: run many tasks **in parallel** (each
in its own headed window) with **batched LLM inference**, **capture** full per-step
trajectories, and **evaluate** them offline.

**LLM backend** (pick one):

- **TreeSparseAttention server** (default, `USE_TSA=1`) — a local OpenAI-compatible
  server (`TreeSparseAttention/serve.py`) serving **Qwen3-VL-30B-A3B-Instruct** with
  either **tree-sparse** (`--top-k 32`) or **full/dense** (`--top-k 100000`) attention.
  Attention is the *only* variable between the sparse and dense runs — this is what the
  sparse-vs-dense accuracy comparison rests on. See **Server setup** below.
- **DashScope / Qwen** (`USE_TSA=0`) — the `ChatDashScope` provider (`qwen3.5-omni`,
  `qwen-vl-max` as the multimodal judge). Set `DASHSCOPE_API_KEY`.

## Layout

```
simulator/
  config.py      constants + RunConfig + USE_TSA / TSA_* server settings
  tasks.py       WebVoyager + GAIA loaders + reference answers
  core/          the run engine
    batching.py    BatchCoordinator (the batch barrier) + BatchLLMProxy
    recorder.py    TrajectoryRecorder + RecordingProxy
    runner.py      worker pool + run_batch + run_capture
  eval/          offline evaluation
    success.py     WebVoyager multimodal judge (reference-aware) -> SUCCESS/NOT SUCCESS
    replay.py      action-replay fidelity
    common.py      shared client + task-dir discovery
  __main__.py    CLI
  data/          datasets + reference answers     runs/  generated output (gitignored)
  tests/         unit tests (no network)
```

## Server setup — TreeSparseAttention (top-k 32 sparse / dense)

The agent **and** the success judge talk to a TreeSparseAttention `serve.py` instance
(OpenAI-compatible). Sparsity is a single knob: `--top-k 32` (tree-sparse decode) vs
`--top-k 100000` (the selector picks all chunks ⇒ full/dense attention).

**1. Serving env** (on the GPU box / container). Use the TreeSparseAttention repo on
branch `shiqihe/dev/simulator`, which adds the two fixes needed to serve Qwen3-VL-30B
for agentic use, then install the two extra deps:

```bash
pip install accelerate xgrammar
```

- `device_map="cuda"` in the loader — streams shards directly to GPU, avoiding the
  ~2× (CPU + GPU) memory peak that OOMs a 30B on unified memory.
- `mm_token_type_ids` threaded through prefill — transformers ≥5.x requires it for
  Qwen3-VL multimodal M-RoPE; without it every screenshot request 500s.

**2. Launch the server** — sparse (top-k 32):

```bash
python3 serve.py \
  --model-path /path/to/Qwen3-VL-30B-A3B-Instruct \
  --host 0.0.0.0 --port 10000 \
  --top-k 32 --page-size 64 \
  --max-decode-tokens 4096 --max-batch-size 8 --batch-collect-ms 150 \
  --tree-parse-mode webarena --served-model-name tree-sparse
# dense baseline: identical command, but --top-k 100000
# xgrammar constrained decoding is ON by default (--disable-xgrammar to turn off)
```

**3. Tunnel** (if the simulator runs on a different machine than the server):

```bash
ssh -N -L 10000:<server-or-container-ip>:10000 user@gpu-host
```

**4. Point the simulator at it** (env; these are the defaults):

```bash
export USE_TSA=1
export TSA_BASE_URL=http://localhost:10000/v1
export TSA_MODEL=tree-sparse
```

Each step the simulator sends an OpenAI `response_format` JSON schema; the server's
**xgrammar** grammar-constrains decoding to it, so the agent emits a valid action even
under aggressive sparsity. (Top-k 32 *without* grammar degenerates into malformed JSON
— grammar is what keeps the sparse run functional.)

## Datasets (both included)

- `data/webvoyager_data.jsonl` — 643 tasks, 15 live sites. Reference answers in
  `data/reference_answer.json` (per-site, types `golden`/`possible`).
- `data/gaia_web.jsonl` — 90 GAIA web tasks, each with an inline ground-truth answer.

`--source {both,webvoyager,gaia}` selects which to draw from (default `both`).

## Usage

```bash
# full WebVoyager + GAIA capture (sparse run), headed + vision on, resumable:
python -m simulator capture --task-num 999 --source both \
    --batch-size 3 --max-steps 12 --task-timeout 1800 \
    --out-dir simulator/runs/WebVoyager-GAIA-sparse-topk32

# success eval — judge is the served Qwen3-VL in FULL attention,
# so restart the server at --top-k 100000 first, then:
USE_TSA=1 python -m simulator eval simulator/runs/WebVoyager-GAIA-sparse-topk32 --mode success

# action-replay fidelity (can the recorded context reproduce each step offline?):
python -m simulator eval simulator/runs/<run> --mode replay
```

The `success` judge sees the task + the agent's answer + the **reference answer**
(ground truth) + the last `k` screenshots and returns SUCCESS / NOT SUCCESS
(temperature 0, grammar-constrained verdict). Both eval modes read only captured files;
neither opens a browser.

Notes:
- Each step re-prefills the full prompt and **prefill is dense for both arms** — tree-sparse
  only sparsifies *decode* attention, so the end-to-end speedup lives in decode and grows
  with batch size and context length.
- `simulator/runs/` is gitignored — generated trajectories / results are not source.

## Tests

```bash
uv run pytest -vxs simulator/tests
```
