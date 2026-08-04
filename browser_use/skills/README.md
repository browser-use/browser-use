# Skills Module

Two things live here:

1. **`SkillService`** — fetch and execute Browser Use API skills.
2. **`SkillFitnessTracker`** — Dempster-Shafer per-skill fitness accumulator. Zero deps beyond stdlib. Powers the EvoMetaClaw / EvoForge / SkillOpt selection loop.

## SkillService — API-backed skills

```python
import asyncio
from browser_use.skills import SkillService

async def main():
    service = SkillService(skill_ids=['skill-id-1', 'skill-id-2'], api_key='your-api-key')
    skills = await service.get_all_skills()  # auto-inits on first call
    result = await service.execute_skill(skill_id='skill-id-1', parameters={'param1': 'value1'})
    if result.success:
        print(f'Result: {result.result}')

    # Every execute_skill call also folds its (success, latency_ms, error)
    # into a per-skill mass function — no wiring needed.
    print(service.ranked_by_fitness(mode='belief'))

    await service.close()

asyncio.run(main())
```

## SkillFitnessTracker — Dempster-Shafer accumulator

Every skill invocation becomes a `MassFunction` over `{LOW, MID, HIGH}`. Repeated invocations combine via Dempster's rule of combination, giving each skill a belief / plausibility interval rather than a point estimate. Selection can be:

| Mode | Meaning | Use for |
|---|---|---|
| `belief` | Lower probability bound. Conservative — avoids unproven skills. | Production, default. |
| `plausibility` | Upper probability bound. Exploratory — tries promising-but-noisy skills. | Warm-up, exploration budgets. |
| `expected` | Pignistic collapse. Bayesian-ish point estimate. | When you need a single scalar. |

### Standalone (no browser, no LLM, no SDK)

```python
from browser_use.skills.fitness import SkillFitnessTracker

tracker = SkillFitnessTracker()
tracker.record('login_flow', success=True, latency_ms=220)
tracker.record('login_flow', success=True, latency_ms=180)
tracker.record('login_flow', success=False, error='captcha')
print(tracker.ranked('belief'))  # [('login_flow', 0.93)]
print(tracker.fitness('login_flow').plausibility())  # 0.99
```

Cold-import for `browser_use.skills.fitness` is ~370ms — no `browser_use_sdk` / `pydantic` chain pulled in. CI guards this (`test_fitness_import_does_not_load_sdk`).

### JSON round-trip (cross-process, cross-language)

```python
import json

blob = json.dumps(tracker.to_dict())
# {"fitness": {"login_flow": {"HIGH": 0.93, "HIGH,LOW,MID": 0.07}}, "invocations": {"login_flow": 3}}
restored = SkillFitnessTracker.from_dict(json.loads(blob))
```

Frozenset keys serialise as sorted-comma-joined strings — trivial to reimplement in JS/Go/Rust.

### CLI (Unix pipeline / KafCade `kc E` steps)

```bash
# Read JSONL from stdin, print rankings
$ cat runs.jsonl | python -m browser_use.skills.fitness --mode belief --top 10
0.9975  3  login_flow
0.9500  1  submit_form
0.4314  2  scrape_catalog

# Persist state across sessions — feed the next EvoMetaClaw epoch
$ python -m browser_use.skills.fitness --state prior.json --save next.json < new.jsonl
```

### HTTP surface (webapp / dashboard / cross-language client)

```bash
$ python -m browser_use.skills.fitness --serve 8765 --save /var/lib/fitness.json
skill-fitness serving on http://127.0.0.1:8765 (persist=/var/lib/fitness.json)
```

```
GET  /health                     → {"status": "ok"}
POST /record                     → body = {skill_id, success, latency_ms?, error?}
GET  /ranked?mode=..&top=..      → [[skill_id, score], ...] best-first
GET  /fitness/<skill_id>         → MassFunction dict or 404
GET  /state                      → full snapshot
POST /state                      → replace snapshot
POST /reset                      → wipe
```

Stdlib `http.server` + `ThreadingHTTPServer` + `Lock` — concurrent-safe, zero new deps. Bind defaults to `127.0.0.1`; pass `--host 0.0.0.0` explicitly to expose off-box. Wrap in ASGI (FastAPI, Starlette) for production TLS / auth / rate-limiting.

### Agent-side (close the flywheel)

Pass a tracker to the `Agent` constructor and every action outcome records automatically:

```python
from browser_use import Agent
from browser_use.skills.fitness import SkillFitnessTracker

tracker = SkillFitnessTracker()
agent = Agent(task='...', llm=llm, action_fitness_tracker=tracker)
await agent.run()

# Actions with the highest belief in HIGH-fitness — safe defaults for next run
print(tracker.ranked('belief')[:5])
```

Default is `None` → zero cost, no recording. Only recorded when set.

### Composition with EvoMetaClaw / EvoForge / KafCade

- **KafCade `kc E`** — pipe each per-project audit finding as one JSONL record; `--state kc-fitness.json --save kc-fitness.json` for durable per-project rankings.
- **EvoForge epoch loop** — every `BioEvolutionReport.best_fitness` becomes one `POST /record`; the accumulated `MassFunction` per genome-id feeds the next `REPLICATOR` step.
- **EvoMetaClaw `EVALUATE_FITNESS`** — read `GET /state`, hand the mass functions to your selection policy (belief/plausibility/expected), write mutations back via `POST /record`.
- **RRSS gates** — every axis of the R²S² discipline gets its own skill_id, so a single fitness call gives you eight-dimensional confidence per artifact.

The wire format is the contract — anything that speaks JSON participates.
