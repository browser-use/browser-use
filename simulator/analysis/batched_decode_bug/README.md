# Batched-decode corruption in the TreeSparseAttention server

**Date:** 2026-06-24 · **Model:** Qwen3-VL-32B-Instruct (dense) · **Server:** TreeSparseAttention `serve.py`, top-k 32

## Symptom

In the live capture (`simulator/runs/WebVoyager-GAIA-topk32-32b-20260624`, run at `--batch-size 3`),
the agent **keeps re-planning but every action is wrong** — its `next_goal` jumps between completely
unrelated, memorized WebVoyager tasks and it emits degenerate clicks. E.g. for three *vegetarian-lasagna*
tasks the model's `next_goal`s were "top 10 most expensive cities for rent", "12-inch cast iron skillet",
"2023 Ford F-150 Raptor R", "Dell XPS 13 on Newegg", with actions like `click index 1` and out-of-range
indices (`7946`, `5931`). See `results/captured_batch3_garbage.txt`. Both the earlier 30B run (also
batch 3) and this 32B run scored ~0% for the same reason.

## Question

Is this a misconfiguration, or has **top-k 32 sparse attention** fundamentally broken the output?

## Method

Replay the **exact recorded contexts** of the failing steps back to the server (no browser) and vary one
factor at a time. Inputs were first verified correct (the lasagna task is present in the context, the
hallucinated nouns are not — so it is **not** context contamination). Scripts:

- `replay_compare.py LABEL TEMP NSAMP` — replays the chosen `(task, step)` contexts **one at a time
  (batch 1)** at temperature `TEMP`, `NSAMP` samples each; dumps `thinking / next_goal / action`.
- `batched_test.py TEMP` — replays the same contexts **concurrently** so the server batches them into a
  single `_sync_run_multi` forward (verified via the server's `Collected batch of N` log).

Run commands: see `run_experiment.sh`.

## Results (same 4 contexts, 32B, top-k 32)

| Configuration | Result |
|---|---|
| **batch 1 @ temp 0** (`results/batch1_temp0.json`) | **4/4 correct** — "search vegetarian lasagna" |
| **batch 1 @ temp 0.2** (`results/batch1_temp0.2.json`) | **12/12 correct** — "vegetarian lasagna **with zucchini**", "**under 600 calories**" |
| **batch 4 @ temp 0.2** (`results/batch4_temp0.2.log`) | **degraded** — `click index 1000000000`, `input "chocolate cake"` on a lasagna task, criteria drift |
| **batch 4 @ temp 0** | **hung** — a sequence rambled to the 1024-token cap (corruption symptom) |

The only variable that flips correct↔garbage is the **batch size**.

## Conclusion — it's the server's batched decode, not top-k / temperature / context / model

- ❌ Not **top-k 32**: batch 1 + top-k 32 is correct.
- ❌ Not **temperature 0.2**: batch 1 + temp 0.2 is correct (12/12).
- ❌ Not **context contamination**: inputs verified correct.
- ❌ Not the **model**: at batch 1 the 32B reads the task and acts sensibly.
- ✅ The **batched decode path** (`serve.py::_sync_run_multi`, used only when `batch_size > 1`) corrupts
  the output. The single-request path (`_sync_generate`, batch 1) is fine.

### Likely root cause (code)
`_sync_run_multi` prefills each request separately, concatenates the KV into one combined paged buffer,
and uses a `page_table` (logical→physical pages per request) plus per-sequence `select_pages_batched`.
The corruption (garbage indices like `1e9`, task drift, hallucination) is consistent with **wrong
per-sequence KV/page indexing in the combined buffer** — sequences attending to the wrong KV pages, so
attention degenerates and the model loses coherence. The fix lives in the combined-KV / `page_table` /
`select_pages_batched` / position handling of the batched path.

## Implications
- **All accuracy measured from batched captures is invalid** (corrupted by this bug). True model
  capability must be measured at **batch 1** (or with a fixed batched path).
- Latency benchmarks at batch > 1 still measured *latency* correctly — they never checked output validity.

## Reproduce
1. Serve Qwen3-VL-32B (or 30B-A3B) at top-k 32; open the tunnel (see `run_experiment.sh` step 0).
2. `python replay_compare.py topk32 0.2 3` → correct.
3. `python batched_test.py 0.2` → degraded.
   Same contexts, only batch size differs.
