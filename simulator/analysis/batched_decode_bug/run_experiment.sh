#!/usr/bin/env bash
# Exact commands used to diagnose the batched-decode corruption (2026-06-24).
# Faithful record — paths are for this machine; not meant to be a turnkey script.
# Local env chain to run the simulator / replay scripts:
#   source /opt/anaconda3/etc/profile.d/conda.sh && conda activate browse-use && source .venv/bin/activate
# Server: spark01 / docker priceless_tesla, TreeSparseAttention serve.py (branch shiqihe/dev/simulator).
set -euo pipefail
RUN=simulator/runs/WebVoyager-GAIA-topk32-32b-20260624   # the batch-3 capture under analysis
HERE=simulator/analysis/batched_decode_bug

# ── 0. Server: serve Qwen3-VL-32B-Instruct (dense) at top-k 32 ────────────────
#   (on the server, inside the container)
#   ssh shiqihe@spark01.eecs.umich.edu 'docker exec priceless_tesla bash -lc /models/start_server_32b.sh'
#   -> python3 serve.py --model-path /models/Qwen3-VL-32B-Instruct --host 0.0.0.0 --port 10000 \
#        --top-k 32 --page-size 64 --max-decode-tokens 4096 --max-batch-size 8 \
#        --batch-collect-ms 150 --tree-parse-mode webarena --served-model-name tree-sparse
# Tunnel (Mac -> container):
#   ssh -N -L 10000:172.17.0.2:10000 shiqihe@spark01.eecs.umich.edu

# ── 1. Characterize: dump the LIVE capture (batch 3) outputs ──────────────────
#   -> results/captured_batch3_garbage.txt   (hallucinated, drifting next_goals; bad indices)
#   Verified the INPUT context is correct (lasagna present, 'skillet' absent) — not contamination.

# ── 2. Controlled replay of the SAME contexts, BATCH 1 (sequential) ───────────
python "$HERE/replay_compare.py" topk32     0.0 1   # -> results/batch1_temp0.json     : 4/4 CORRECT
python "$HERE/replay_compare.py" topk32_t02 0.2 3   # -> results/batch1_temp0.2.json   : 12/12 CORRECT

# ── 3. Controlled replay, BATCH 4 (concurrent -> server batches into one forward) ─
python "$HERE/batched_test.py" 0.2                  # -> results/batch4_temp0.2.log : DEGRADED
python "$HERE/batched_test.py" 0.0                  # batch-4 greedy: HUNG (a seq rambled to the token cap)

# Conclusion: same input, batch 1 = correct, batch 4 = garbage => the server's batched
# decode path (_sync_run_multi) corrupts the output. See README.md.
