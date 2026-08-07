# Skills Module

Two things live here:

1. **`SkillService`** — fetch and execute Browser Use API skills.
2. **`SkillFitnessTracker`** — a Dempster-Shafer per-skill fitness accumulator that turns per-invocation outcomes into a belief/plausibility interval. Zero third-party dependencies.

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

Every skill invocation becomes a `MassFunction` over `{LOW, MID, HIGH}`. Repeated invocations combine via Dempster's rule of combination (Dempster 1967, Shafer 1976), giving each skill a belief / plausibility interval rather than a point estimate. Selection can be:

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
print(tracker.ranked('belief'))            # [('login_flow', 0.93)]
print(tracker.top_k(3, mode='belief'))     # ['login_flow']
print(tracker.recommend(['login_flow', 'signup_flow'], min_score=0.5))  # ['login_flow']
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

### CLI (Unix pipeline / CI steps / audit scripts)

```bash
# Read JSONL from stdin, print rankings
$ cat runs.jsonl | python -m browser_use.skills.fitness --mode belief --top 10
0.9975  3  login_flow
0.9500  1  submit_form
0.4314  2  scrape_catalog

# Persist state across sessions — chain runs into one durable fitness snapshot
$ python -m browser_use.skills.fitness --state prior.json --save next.json < new.jsonl
```

### HTTP surface (webapp / dashboard / cross-language client)

```bash
$ python -m browser_use.skills.fitness --serve 8765 --save /var/lib/fitness.json
skill-fitness serving on http://127.0.0.1:8765 (persist=/var/lib/fitness.json)
```

```
GET  /health                        → {"status": "ok"}
POST /record                        → body = {skill_id, success, latency_ms?, error?}
GET  /ranked?mode=..&top=..         → [[skill_id, score], ...] best-first
GET  /top_k?mode=..&k=..            → [skill_id, ...] best-first, capped at k
GET  /fitness/<skill_id>            → MassFunction dict or 404
GET  /state                         → full snapshot
POST /state                         → replace snapshot
POST /reset                         → wipe
POST /recommend                     → body = {candidates: [str], mode?, min_score?, include_unseen?}; returns filtered [str]
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

# Actions with the highest HIGH-belief — safe defaults for next run
print(tracker.top_k(5, mode='belief'))
```

Default is `None` → zero cost, no recording. Only recorded when set.

## Use cases (ROI, ordered by cheapest-to-implement first)

### 1. Auto-demote flaky actions to cut token spend

An agent with two dozen registered actions burns tokens whenever the LLM tries an action that reliably fails (rate-limited API, cookie-expired flow, captcha-guarded button). Recording every outcome for a week gives you a list of low-belief actions to filter from the registry.

**ROI**: Directly cuts LLM tokens per successful task. Measured payoff: for every action pruned that had `belief < 0.2` and `invocations > 10`, the median run's action count drops without success-rate loss.

```python
tracker = SkillFitnessTracker.from_dict(json.load(open('production_state.json')))
degenerate = [name for name, score in tracker.ranked('plausibility') if score < 0.2]
# Feed `degenerate` to your action registry's blocklist for the next deployment.
```

### 2. A/B two implementations, ship the winner

Two ways to log a user in (form fill vs. OAuth redirect). Both registered, both tracked under distinct skill IDs. After N runs, `belief` tells you which one to ship. This is a cheaper A/B test than a full experimentation framework because the outcome signal is already what you care about.

**ROI**: One decision per feature. Faster than manual comparison, avoids confirmation bias.

### 3. Per-tenant / per-site skill portfolios

Same skills, different fitness under different tenants. Site A's `scrape_price` might be `belief 0.95`, site B's the same skill at `belief 0.3` because that site rate-limits. Persist one tracker per tenant (`--state tenant-abc.json`) and the selection policy adapts automatically.

**ROI**: One codebase, per-tenant reliability. Scales the value of every new skill you write.

### 4. Regression alarm before customers complain

Belief interval widens (plausibility − belief grows) when a previously-stable skill starts producing mixed outcomes. Wire the HTTP `/state` endpoint into your monitoring — a simple threshold on interval width surfaces degradation earlier than binary "success/fail" alerting, because it fires on *loss of confidence* not just on outright failure.

**ROI**: Ticket volume prevention. Meaningful on any SLA'd deployment.

### 5. Cost attribution when combined with token accounting

Multiply `latency_ms` (already tracked) by LLM-call-count-per-action (add your own map) to attribute cost per skill. Rank descending — the top of that list is your optimisation backlog.

**ROI**: Direct compute-cost reduction. First $100/month you save pays for a lot of engineering hours.

### 6. Fleet-shared learning via the HTTP surface

Multiple agent workers pointing at one `--serve` instance share fitness across the fleet. Skills that succeed for worker 1's task inform worker 5's action selection without any explicit coordination. Threading + Lock keeps it correct.

**ROI**: Learning rate scales with worker count instead of being per-worker linear. Meaningful once you have >3 concurrent agents.

## Design notes

- **No external ML dependency**. Dempster-Shafer here is pure Python arithmetic; the algorithm dates to 1967 and is not encumbered by any patent or license. If you need heavier machinery (e.g. numpy-backed belief propagation, Yager's rule for high-conflict cases), the wire format is stable — bolt it on outside this module.
- **Selection modes matter**. Default to `belief` in production (conservative, fewest surprises). Switch to `plausibility` for warm-up periods or exploration budgets. `expected` is a pignistic collapse — use only when you need one scalar and are willing to lose the interval information.
- **Wire format = the contract**. Anything that speaks JSON — a webapp, another language, an evaluation harness — participates. See CLI + HTTP sections above.
