# Skills Module

Two things live here:

1. **`SkillService`** — fetch and execute Browser Use API skills.
2. **`SkillFitnessTracker`** — a Dempster-Shafer per-skill fitness accumulator that turns per-invocation outcomes into a belief/plausibility interval. Zero third-party dependencies, distributable as its own standalone service.

## Install as a standalone tool (no Python integration needed)

The tracker + HTTP surface + CLI ship as a console script named `skill-fitness`. You do not need to touch any Python code to run it — pick any of these.

### pipx — user-level install (recommended)

```bash
pipx install browser-use
skill-fitness --serve 8765
```

Provides `skill-fitness` on `PATH` under an isolated venv. Available on Linux, macOS, Windows.

### uvx — zero-install, runs on demand

```bash
uvx --from browser-use skill-fitness --serve 8765
```

Downloads to a shared cache, no venv management, works with `uv >= 0.5`.

### pip — inside an existing environment

```bash
pip install browser-use
skill-fitness --help
```

### Docker — reproducible, single artifact

The core module has zero third-party deps and works with the default `python:3.12-slim`. From this repo:

```bash
docker build -f Dockerfile -t browser-use:local .
docker run --rm -p 8765:8765 -v $(pwd)/state:/state \
  browser-use:local \
  python -m browser_use.skills.fitness --serve 8765 --host 0.0.0.0 --save /state/fitness.json
```

For a smaller image, a minimal Dockerfile is a two-liner:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir browser-use
ENTRYPOINT ["skill-fitness"]
```

### systemd — supervised on Linux

`/etc/systemd/system/skill-fitness.service`:

```ini
[Unit]
Description=Skill fitness accumulator
After=network.target

[Service]
Type=simple
User=fitness
Group=fitness
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/local/bin/skill-fitness --serve 8765 --host 127.0.0.1 --save /var/lib/skill-fitness/state.json
Restart=on-failure
RestartSec=2
# Sandboxing — nothing on the box needs to be writable except the state dir.
ProtectSystem=strict
ReadWritePaths=/var/lib/skill-fitness
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /usr/sbin/nologin fitness
sudo mkdir -p /var/lib/skill-fitness && sudo chown fitness:fitness /var/lib/skill-fitness
sudo systemctl daemon-reload && sudo systemctl enable --now skill-fitness
sudo systemctl status skill-fitness
```

Graceful shutdown on `systemctl stop` — the service handles SIGTERM.

### launchd — supervised on macOS

`~/Library/LaunchAgents/dev.skillfitness.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>dev.skillfitness</string>
    <key>ProgramArguments</key>
    <array>
      <string>/opt/homebrew/bin/skill-fitness</string>
      <string>--serve</string><string>8765</string>
      <string>--save</string><string>/Users/you/Library/Application Support/skill-fitness/state.json</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
  </dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/dev.skillfitness.plist
```

### Windows service — via NSSM

```powershell
pipx install browser-use
nssm install SkillFitness "$(pipx environment --value PIPX_BIN_DIR)\skill-fitness.exe"
nssm set SkillFitness AppParameters --serve 8765 --save C:\ProgramData\skill-fitness\state.json
nssm start SkillFitness
```

### Health check probe (any deploy target)

```bash
curl -fsS http://127.0.0.1:8765/health && echo up
curl -fsS http://127.0.0.1:8765/ready && echo ready
```

## SkillService — API-backed skills

```python
import asyncio
from browser_use.skills import SkillService

async def main():
    service = SkillService(skill_ids=['skill-id-1', 'skill-id-2'], api_key='your-api-key')
    skills = await service.get_all_skills()
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

Every skill invocation becomes a `MassFunction` over `{LOW, MID, HIGH}`. Repeated invocations combine via Dempster's rule of combination (Dempster 1967, Shafer 1976), giving each skill a belief / plausibility interval rather than a point estimate.

| Mode | Meaning | Use for |
|---|---|---|
| `belief` | Lower probability bound. Conservative — avoids unproven skills. | Production, default. |
| `plausibility` | Upper probability bound. Exploratory — tries promising-but-noisy skills. | Warm-up, exploration budgets. |
| `expected` | Pignistic collapse. Bayesian-ish point estimate. | When you need a single scalar. |

### Standalone Python (no browser, no LLM, no SDK)

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

Cold-import for `browser_use.skills.fitness` is ~370ms — no SDK / pydantic chain pulled in. CI guards this (`test_fitness_import_does_not_load_sdk`).

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
$ cat runs.jsonl | skill-fitness --mode belief --top 10
0.9975  3  login_flow
0.9500  1  submit_form
0.4314  2  scrape_catalog

$ skill-fitness --state prior.json --save next.json < new.jsonl
```

### HTTP surface — modern-service defaults

Every route also aliased under `/v1/...` for stable API versioning across future breaking changes.

```
GET  /health                        → liveness probe                    {"status":"ok"}
GET  /ready                         → readiness probe                   {"status":"ready"}
GET  /metrics                       → Prometheus text/plain              (counters + gauges per skill)
GET  /openapi.json                  → OpenAPI 3.1 schema of this API
POST /record                        → body = {skill_id, success, latency_ms?, error?}
GET  /ranked?mode=..&top=..         → [[skill_id, score], ...] best-first
GET  /top_k?mode=..&k=..            → [skill_id, ...] best-first, capped at k
GET  /fitness/<skill_id>            → MassFunction dict or 404
GET  /state                         → full snapshot
POST /state                         → replace snapshot
POST /reset                         → wipe
POST /recommend                     → {candidates:[str], mode?, min_score?, include_unseen?} → filtered [str]
OPTIONS <any>                       → CORS preflight (Access-Control-Allow-*)
```

Implementation details worth flagging:
- **Concurrent-safe**: `ThreadingHTTPServer` + shared `Lock` — no state races.
- **Persistence**: every mutating request atomically writes `--save` path if provided.
- **CORS**: GET endpoints send `Access-Control-Allow-Origin: *` for browser dashboards. Preflight OPTIONS returns 204 with allowed methods.
- **Access logs**: one JSON line per mutating request to stderr (`{ts_ns, method, path, status, remote}`) — pipe to your log collector as-is.
- **Prometheus metrics** (`/metrics`): `skill_fitness_records_total` (counter), `skill_fitness_tracked_skills` (gauge), `skill_fitness_invocations{skill=...}` (per-skill counter), `skill_fitness_belief_high{skill=...}` (per-skill gauge). Scrape from any Prometheus/Grafana/OpenTelemetry collector.
- **OpenAPI schema** (`/openapi.json`): OpenAPI 3.1 — import into Postman/Insomnia/openapi-generator to auto-generate typed clients for any language.
- **Graceful shutdown**: SIGTERM (from `systemctl stop`, `docker stop`, `kubectl delete`) triggers `server.shutdown()`; in-flight requests complete before exit.
- **Bind default `127.0.0.1`**: nothing exposed off-box without an explicit `--host 0.0.0.0`. Wrap in nginx/Caddy/Traefik for TLS + auth + rate-limiting in production.

### Agent-side (close the flywheel)

Pass a tracker to the `Agent` constructor and every action outcome records automatically:

```python
from browser_use import Agent
from browser_use.skills.fitness import SkillFitnessTracker

tracker = SkillFitnessTracker()
agent = Agent(task='...', llm=llm, action_fitness_tracker=tracker)
await agent.run()
print(tracker.top_k(5, mode='belief'))
```

Default is `None` → zero cost, no recording.

## Use cases with the fastest payoff

Ordered cheapest-to-adopt first. All work without any code changes on the consumer side beyond a `POST /record` call per outcome.

### 1. Auto-demote flaky actions to cut LLM token spend

An agent exposing 20 tools burns tokens every time the LLM tries an action that reliably fails (rate-limited API, cookie-expired flow, captcha-guarded button). Record every outcome for a week. Prune actions with `belief < 0.2` and `invocations > 10` from the next deployment's registry.

**Payoff**: direct reduction in LLM tokens per successful task. Applies to any agent that exposes more tools than each task typically needs.

```python
tracker = SkillFitnessTracker.from_dict(json.load(open('production_state.json')))
degenerate = [name for name, score in tracker.ranked('plausibility') if score < 0.2]
```

### 2. A/B two implementations, ship the winner

Two ways to accomplish the same job (form-fill login vs. OAuth redirect). Both registered, both tracked under distinct skill IDs. After N runs, `belief` tells you which one to keep. Cheaper and faster than a full experimentation framework because the signal is already the outcome you care about.

**Payoff**: one decision per feature. Faster than manual comparison; avoids confirmation bias.

### 3. Per-tenant / per-site skill portfolios

Same skills, different fitness under different tenants. Site A's `scrape_price` might be `belief 0.95`; site B's the same skill at `belief 0.3` because that site rate-limits. Persist one tracker per tenant (`--save tenant-abc.json`) and selection adapts automatically.

**Payoff**: one codebase, per-tenant reliability. Every new skill scales its own value across the tenant fleet.

### 4. Regression alarm before customers complain

Belief interval widens (plausibility − belief grows) when a previously-stable skill starts producing mixed outcomes. Wire `/metrics` into your Prometheus/Grafana stack — a threshold alert on the widening interval fires on *loss of confidence* before outright failure, which binary success/fail alerting cannot see.

**Payoff**: ticket volume prevention. Any SLA'd deployment.

### 5. Cost attribution when combined with token accounting

Multiply `latency_ms` (already tracked) by LLM-call-count-per-action (add your own map) to attribute cost per skill. Rank descending — the top of that list is your optimisation backlog.

**Payoff**: direct compute-cost reduction. The first $100/month you save funds a lot of engineering time.

### 6. Fleet-shared learning via the HTTP surface

Multiple agent workers pointing at one `--serve` instance share fitness across the fleet. Skills that succeed for worker 1's task inform worker 5's action selection without explicit coordination. `ThreadingHTTPServer` + `Lock` keeps it correct.

**Payoff**: learning rate scales with worker count instead of being per-worker linear. Meaningful once you have >3 concurrent agents.

### 7. Public-facing "trust score" for a skills marketplace

If you sell or share skills to third parties (browser-automation-as-a-service, an in-house skill store), publish the `belief` and `invocations` values as the skill's transparent trust score. Users pick between similar skills on real observed reliability, not vendor claims.

**Payoff**: better sorting for consumers of your catalog; visible quality pressure on skill authors.

## Design notes

- **No external ML dependency.** DS is pure Python arithmetic; the algorithm is public-domain mathematics (Dempster 1967, Shafer 1976) and is not patent-encumbered. Implementation is original and ships under browser-use's existing MIT license.
- **Selection modes matter.** Default `belief` in production. `plausibility` for warm-up / exploration budgets. `expected` when you need a single scalar and can accept losing the interval.
- **Wire format is the contract.** JSON in and out — anything that speaks JSON participates. `openapi.json` gives you a machine-readable spec to generate clients from.
- **Not a substitute for a full experimentation framework.** For power-analyzed A/B tests with multi-arm bandits and CUPED variance reduction, use a dedicated platform. The tracker is for *operational* decisions on live systems.
