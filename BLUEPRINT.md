# Browser-Use × Claude Code — Interactive Agent Blueprint

> Living design document. Last updated: 2026-05-30. Sessions: setup · UX design · API key · job search · onboarding guide · GitHub push · Udemy curriculum → deeptechx.xyz · job search v2 (Innovation Manager profile) · EWOR form fill (partial→full) · job search v3 (Nordic/Remote EU) · WorldMonitor RSS · **research module** · **EWOR submitted ✅ 2026-05-30** · resume-site deployed → vercel.

---

## 1. Setup Record

### What Was Installed

| Component | Location | Notes |
|-----------|----------|-------|
| `browser-use` CLI (global tool) | `C:\Users\nzengou\.local\bin\browser-use.exe` | Aliases: `bu`, `browser`, `browseruse` |
| `uv` package manager | `C:\Users\nzengou\AppData\Local\Programs\Python\Python313\Scripts\uv.exe` | Installed via Python 3.13 pip |
| Claude Code skill | `~/.claude/skills/browser-use/SKILL.md` | Copied from `skills/browser-use/SKILL.md` |
| Project venv | `.venv/` (Python 3.12 via uv) | Run via `uv run browser-use ...` from project root |
| PATH update | `~/.local\bin` added via `uv tool update-shell` | Requires shell restart |

### Health Check

```bash
PYTHONIOENCODING=utf-8 browser-use doctor
```

**Current status (2026-05-21):** 4/5 checks pass.
- ✓ Chromium available
- ✓ Network OK
- ✓ `BROWSER_USE_API_KEY` set — cloud browser + `ChatBrowserUse()` active
- ○ `cloudflared` — install for tunnel support
- ○ `profile-use` — install for Chrome profile sync

### Windows Encoding Fix

The CLI outputs Unicode symbols (✓ ○) that crash in Windows cp1252 terminals.
Always prefix with `PYTHONIOENCODING=utf-8` or set it in the session env.

---

## 2. UX Design: The Interactive Agent-Browsing Model

### Core Philosophy

> The user states an intent. The assistant owns the execution — narrating, checkpointing, and adapting — until the task is done or the user takes the wheel.

The user never types CLI commands. They describe goals in plain language. Claude translates intent → browser actions → narrated results, pausing only when a human decision is genuinely required.

**Three failure modes to eliminate:**
1. Silent execution — user doesn't know what's happening
2. Blind submission — assistant fills and submits forms without user review
3. Dead ends — assistant gets stuck and just says "I can't do that"

---

### 2.1 Interaction Phases

Every browser task moves through five phases:

```
INTENT → PLAN → EXECUTE → REVIEW → HANDOFF
```

#### Phase 1: INTENT
Clarify what's wanted before touching the browser.

Ask at most **2 clarifying questions** — no interrogation. Defaults are fine for most things.

Minimum to collect:
- Target URL or site (if not obvious)
- Login needed? If yes — Chrome profile, existing session, or provide credentials?
- Any specific data to use (form values, search terms, etc.)
- Expected output (screenshot, extracted data, just "do the thing"?)

**Example opener:**
```
I'll take care of that. A couple of quick things before I start:
1. [most important ambiguity]
2. [second ambiguity, if truly needed]
Or just say "go for it" and I'll use sensible defaults.
```

---

#### Phase 2: PLAN
Present the steps before executing. Keep it to 3–6 bullet points.

```
Here's what I'll do:
• Open [URL]
• [Step 2]
• [Step 3]
• Screenshot before submitting / extracting / downloading

Anything to change, or should I start?
```

Skip this phase for simple single-step tasks ("take a screenshot of X", "what's on this page").

---

#### Phase 3: EXECUTE
Run with live narration. Each meaningful action gets one line.

**Narration cadence:**
```
Opening example.com...
Found the search field (element 12). Typing "your query"...
Search returned 8 results. Looking for the best match...
Clicking result 3 — "Title that matches"...
Page loaded: [page title]
```

**Three tiers of action:**

| Tier | Examples | Behavior |
|------|---------|---------|
| **Autonomous** | Navigate, scroll, read, wait | Just do it — no commentary needed |
| **Narrated** | Click, type, select, hover | One-line narration before/after |
| **Confirmed** | Submit form, download file, create account, delete, purchase | Screenshot + explicit user confirmation |

**Checkpoint triggers** (pause and ask):
- Login/auth wall encountered
- CAPTCHA encountered
- Multiple valid options with no clear winner
- Form pre-filled with user data, ready to submit
- Unexpected page / error page
- Action would send a message, post content, or charge money

**Checkpoint format:**
```
[Screenshot if available]
I'm at [description of current state]. 
[What I found / what's ambiguous]
Should I [option A] or [option B]?
```

---

#### Phase 4: REVIEW
After completing the task, surface the result clearly.

**For data extraction:**
Present data inline, formatted. Offer to save to file if non-trivial.

**For form submission / actions taken:**
Screenshot of the confirmation/result page. One-sentence summary.

**For navigation tasks:**
State the final URL and page title. Screenshot if visual confirmation matters.

**Closing prompt** (always):
```
Done. [One-line result summary.]
Want to do anything else from here, or should I close the browser?
```

---

#### Phase 5: HANDOFF
Two modes:

**Keep open** — if the user says "stay on this page" or follow-up is likely:
```bash
browser-use state   # report current elements so user knows what's available
```

**Close cleanly:**
```bash
browser-use close
```

Never leave a dangling session without telling the user.

---

### 2.2 Session Modes

#### Default: Step-by-Step Guided
Full INTENT → PLAN → EXECUTE → REVIEW → HANDOFF flow. User is in the loop at every checkpoint.

#### Fast Mode
User says: "just do it" / "no confirmations" / "run it straight through"
- Skip PLAN phase
- Collapse narration to one status line per major step
- Only hard-stop at auth walls and destructive actions
- Screenshot at the end

#### Supervised Autonomous
User gives a multi-step task list upfront. Assistant works through all items, collecting a log, then presents the full summary at the end. Useful for research/extraction tasks where the user doesn't want to babysit each click.

---

### 2.3 Browser Mode Selection

Present this choice when a login-required site is the target:

```
This site needs a login. How do you want to handle it?

A) Use your existing Chrome profile (already logged in)
   → browser-use --profile "Default" open [url]

B) Use headless Chromium — I'll fill credentials you provide
   → browser-use open [url]  (then fill login form)

C) Use a cloud browser (zero local setup, stealth fingerprinting)
   → Requires BROWSER_USE_API_KEY
```

For non-login tasks, default to headless Chromium — fastest startup, no setup.

---

### 2.4 Error Recovery Protocol

| What happened | Response |
|---------------|---------|
| Element not found | Scroll down, re-run `state`, try again. If still missing → screenshot + ask |
| Page didn't load | Wait 2s, retry once. Then report error + current URL |
| Login wall (unexpected) | Report, offer auth options (§2.3) |
| CAPTCHA | Screenshot, tell user, wait for "I've solved it, continue" |
| Unexpected redirect | Report new URL and page title, ask if this is expected |
| JS error / broken page | `browser-use get html` to inspect, report, offer `--headed` debug mode |
| Stuck for >3 attempts | Stop, screenshot, describe exactly what's visible, ask for direction |

**Never:** retry indefinitely, guess credentials, click through warnings silently, or claim success when the page shows an error.

---

### 2.5 Screenshot Strategy

Take a screenshot at these moments — always:
1. After every `open` when the task is non-trivial
2. Before any form submission, file download, or account action
3. When the task is complete (the "done" confirmation)
4. Whenever reporting an error or unexpected state
5. When the user asks "what does it look like?"

Use `browser-use screenshot` (base64 to terminal) for quick checks, or `browser-use screenshot path.png` when saving for the user.

---

## 3. Command Reference (Quick Sheet)

```bash
# Session lifecycle
browser-use open <url>              # Start / navigate
browser-use state                   # See all interactive elements with indices
browser-use screenshot [file.png]   # Capture current view
browser-use close                   # End session

# Interaction
browser-use click <index>           # Click by index from state
browser-use input <index> "text"    # Clear + type into field
browser-use keys "Enter"            # Keyboard (Tab, Escape, Control+a, etc.)
browser-use select <index> "opt"    # Dropdown selection
browser-use scroll down             # Scroll (up/down, --amount N px)

# Data
browser-use get text <index>        # Read element text
browser-use get html                # Full page HTML
browser-use eval "js"               # Run JavaScript

# Auth / profiles
browser-use --profile "Default" open <url>   # Use real Chrome profile
browser-use connect                           # Connect to running Chrome (CDP)

# Wait
browser-use wait selector "css"     # Wait for element
browser-use wait text "text"        # Wait for text to appear
```

---

## 4. Skill Architecture

The Claude Code skill (`~/.claude/skills/browser-use/SKILL.md`) gates all browser-use tooling behind the `Bash(browser-use:*)` permission. When invoked, Claude follows the interactive protocol defined in §2 of this blueprint.

**Skill trigger phrases** (non-exhaustive):
- "go to / open / navigate to [url]"
- "fill in / submit [form]"
- "find / search / look up [thing] on [site]"
- "take a screenshot of [page]"
- "extract / scrape [data] from [site]"
- "log in to [site] and [do thing]"
- "automate [task] on [site]"

**References bundled with the skill:**
- `references/cdp-python.md` — advanced CDP control from Python
- `references/multi-session.md` — running parallel browser sessions

---

## 5. Extending the Agent

### Adding Custom Tools

```python
from browser_use import Agent, Tools, Browser

tools = Tools()

@tools.action(description='Describe what this does for the LLM.')
def my_action(param: str) -> str:
    return f"result: {param}"

agent = Agent(task="...", llm=llm, browser=Browser(), tools=tools)
```

### Choosing an LLM

| Provider | Import | Best for |
|----------|--------|---------|
| Browser-Use hosted | `ChatBrowserUse()` | Best accuracy/speed on browser tasks |
| Anthropic | `ChatAnthropic(model='claude-sonnet-4-6')` | Complex reasoning, long tasks |
| Google | `ChatGoogle(model='gemini-2.5-flash')` | Fast + cheap |
| Local | `ChatOllama(model='llama3.2')` | Offline / privacy |

### Running as MCP Server

```bash
browser-use --mcp    # Exposes browser tools to Claude Desktop / other MCP clients
```

---

## 6. Roadmap / Open Items

- [x] Set `BROWSER_USE_API_KEY`
- [x] Git repo initialised
- [x] `ONBOARDING.md` written
- [x] Pushed to GitHub — `dnzengou/browser-use` · branch `workspace`
- [x] **Research module implemented** — `browser_use.research` (CitationTracker · ParallelResearchOrchestrator · StreamingReasoningTracer) — 19 CI tests all green · 2026-05-26
- [x] Pushed to `dnzengou/browser-use-reverse-engineered` — branch `workspace` · 2026-05-26
- [ ] Run `browser-use profile update` to enable Chrome profile sync
- [ ] Install `cloudflared` for tunnel support (`winget install cloudflare.cloudflared`)
- [x] **LLM-powered synthesis injection** — `make_llm_synthesize_fn(llm)` factory; async `synthesize_fn` support via `_call_synthesize`; 2 new CI tests · 2026-05-29
- [x] **FastAPI SSE demo** — `examples/research_streaming_sse.py`; `/stream` SSE + `/traces` JSON endpoints · 2026-05-29

---

## 11. Research Module — Competitive-Parity Browser-Agent Innovations (2026-05-26)

Three capabilities reverse-engineered from Kimi / Perplexity / Grok patterns, implemented as `browser_use.research`:

### 11.1 CitationTracker (Perplexity-style)

Every data point extracted from the web carries provenance metadata:
- Source URL, page title, extraction timestamp
- SHA-256[:12] content fingerprint for cheap deduplication
- Heuristic confidence ∈ [0.1, 1.0] (length + element specificity)

```python
from browser_use.research import CitationTracker

tracker = CitationTracker()
cited = tracker.cite(
    content="OpenAI was founded in 2015.",
    url="https://en.wikipedia.org/wiki/OpenAI",
    page_title="OpenAI",
    element_ref="#firstHeading",
)
print(cited.as_markdown())
# [1] <https://en.wikipedia.org/wiki/OpenAI> — *OpenAI* (2026-05-26 19:00 UTC, conf=0.73)
```

### 11.2 ParallelResearchOrchestrator (Kimi-style)

Spawns N async agent tasks concurrently (one per URL or query variant), collects `CitedResult`s from each, synthesizes into a `ResearchReport`:

```python
from browser_use.research import ParallelResearchOrchestrator

async def my_research_fn(query: str, url: str) -> str:
    agent = Agent(task=f"{query} at {url}", llm=llm, browser=Browser())
    result = await agent.run()
    return result.final_result() or ''

orch = ParallelResearchOrchestrator(research_fn=my_research_fn, max_concurrency=4)
report = await orch.run(
    research_question="Latest AI agent benchmarks?",
    urls=["https://arxiv.org", "https://paperswithcode.com"],
)
print(report.as_markdown())
```

The synthesizer is injectable — pass `synthesize_fn=your_llm_fn` for LLM-powered synthesis.

### 11.3 StreamingReasoningTracer (Grok-style)

Emits structured `ReasoningTrace` events during the agent loop. Three consumer patterns:
- **Async generator** → FastAPI `StreamingResponse` / SSE endpoints
- **Callback sinks** → CLI logging, Slack alerts, observability pipelines
- **In-memory accumulation** → test assertions, post-run replay

```python
from browser_use.research import StreamingReasoningTracer

tracer = StreamingReasoningTracer()
tracer.add_sink(lambda t: print(t.to_json_line()))  # live console output

# Wire callbacks into agent (hook points: on_step_start, on_step_end, etc.)
tracer.on_step_start(step=1)
tracer.on_action(step=1, action_name='navigate', params={'url': '...'})

# FastAPI SSE endpoint:
async def event_stream():
    async for trace in tracer.stream():
        yield trace.to_sse()
```

### 11.4 File Manifest

| File | Role |
|------|------|
| `browser_use/research/__init__.py` | Public API exports |
| `browser_use/research/views.py` | Pydantic models: Citation, CitedResult, TabResult, ResearchReport, ReasoningTrace |
| `browser_use/research/citation.py` | CitationTracker implementation |
| `browser_use/research/orchestrator.py` | ParallelResearchOrchestrator |
| `browser_use/research/streaming.py` | StreamingReasoningTracer |
| `tests/ci/test_research_module.py` | 19 CI tests (all pass, real objects, pytest-httpserver) |
| `conftest.py` | Root conftest: ensures local source wins in shared-venv setups |

### 11.5 Innovation Recipe

| Pattern source | What was taken | Implementation |
|----------------|---------------|----------------|
| Perplexity Code | Citation provenance per claim | `CitationTracker` + `Citation` model |
| Kimi Code | Multi-tab concurrent research | `ParallelResearchOrchestrator` + asyncio.Semaphore |
| Grok Build | Live chain-of-thought stream | `StreamingReasoningTracer` + SSE/NDJSON emitters |

**Scaling axis:** `max_concurrency` parameter governs parallelism; `synthesize_fn` injection makes the orchestrator LLM-agnostic for arbitrary scale-out.

---



- [x] Set `BROWSER_USE_API_KEY` — saved in `.env` + `~/.browser-use/config.json` via `browser-use cloud login`
- [x] Git repo initialised — `git init` + identity set (`desire.yavro@gmail.com`)
- [x] `ONBOARDING.md` quick intro guide written (see §8)
- [x] Pushed to GitHub — `dnzengou/browser-use` · branch `workspace` · commit `cf90cf6`
  - Repo: https://github.com/dnzengou/browser-use/tree/workspace
  - Auth: `gh` CLI v2.92.0 (portable), device-flow login as `dnzengou`
  - Note: pushed to `workspace` branch (not `main`) to preserve fork history
- [ ] Run `browser-use profile update` to enable Chrome profile sync
- [ ] Install `cloudflared` for tunnel support (`winget install cloudflare.cloudflared`)
- [ ] Restart shell to get `browser-use` in PATH (currently needs full path or `PYTHONIOENCODING=utf-8 browser-use ...`)
- [ ] Consider pinning `PYTHONIOENCODING=utf-8` in shell profile (~/.bashrc or ~/.zshrc)

---

## 7. Job Search — Remote Europe (2026-05-21)

**Profile:** Space & deep tech business innovation manager · blockchain business developer · startup experience · engineering background · innovation toolbox

**Sources searched:** LinkedIn (4 targeted queries), web3.career, cryptojobslist.com, startup niche boards
**Method:** Cloud browser (stealth), iterative query refinement from broad → sector-specific keywords

---

### 🛰️ Track A — Space & Deep Tech: Business Innovation / Development

| # | Role | Company | Location | Fit signal | Link |
|---|------|---------|---------|-----------|------|
| A1 | **Co-founder & BD Lead – NewSpace** | Tandem – Les Deeptech | France | Purpose-built for startup + engineering + NewSpace BD profile. Co-founder framing. | [LinkedIn](https://fr.linkedin.com/jobs/view/co-founder-business-development-lead-%E2%80%93-newspace-at-tandem-les-deeptech-4410508779) |
| A2 | **VP, Business Development – EMEA** | Loft Orbital | Toulouse, France | In-orbit satellite services scale-up. VP-level commercial scope across EMEA. | [LinkedIn](https://fr.linkedin.com/jobs/view/vp-business-development-emea-at-loft-orbital-4354292799) |
| A3 | **Director, Strategic Initiatives – EMEA** | Loft Orbital | France | Strategy + partnerships at same NewSpace scale-up. Complements A2. | [LinkedIn](https://fr.linkedin.com/jobs/view/director-strategic-initiatives-emea-at-loft-orbital-4354292797) |
| A4 | **BDM – Quantum for Defence & Space** | Infleqtion UK | Kidlington, UK | Quantum-enabled deep tech for space/defence. Engineering background + BD explicitly required. | [LinkedIn](https://uk.linkedin.com/jobs/view/business-development-manager-quantum-for-defence-space-at-infleqtion-uk-4382359918) |
| A5 | **Business Developers in Deep Tech (R2B)** | Aalto University | Espoo, Finland | Research-to-Business track — exactly the innovation toolbox + startup ecosystem profile. | [LinkedIn](https://fi.linkedin.com/jobs/view/business-developers-in-deep-tech-r2b-at-aalto-university-4414764353) |
| A6 | **Sr. BDM – Connected Computing** | imec | Leuven, Belgium | World-class deep tech R&D hub. BDM bridging research → industry. | [LinkedIn](https://be.linkedin.com/jobs/view/senior-business-development-manager-for-connected-computing-sector-at-imec-in-vlaanderen-4412120066) |
| A7 | **Head of Market Entry & Strategic Growth – IoT** | Fraunhofer IIS | Nuremberg, Germany | Fraunhofer deep tech transfer office. Market entry + engineering context. | [LinkedIn](https://de.linkedin.com/jobs/view/head-of-market-entry-strategic-growth-%E2%80%93-iot-all-genders-at-fraunhofer-iis-4373561585) |
| A8 | **Business Development Manager** | TaiSan | Cambridge, UK | Cambridge deep tech startup — quantum sensing / space applications. | [LinkedIn](https://uk.linkedin.com/jobs/view/business-development-manager-at-taisan-4375293689) |

---

### ⛓️ Track B — Blockchain / Web3: Business Developer

| # | Role | Company | Location | Fit signal | Link |
|---|------|---------|---------|-----------|------|
| B1 | **Business Development Manager** | Wert.io | **Remote** ✓ | Crypto-native BD, fully remote, blockchain payment infrastructure startup. Pure match. | [cryptojobslist](https://cryptojobslist.com/jobs/business-development-manager-at-wert-io) |
| B2 | **BDM – Blockchain & DeFi Ecosystem** | Fireblocks | Remote / Europe | Leading institutional blockchain infra. DeFi ecosystem BD — engineering credibility valued. | [web3.career](https://web3.career/business-development-manager-blockchain-and-defi-ecosystem-fireblocks/149281) |
| B3 | **Account Executive, EMEA** | Chainlink Labs | Dublin / Remote | Oracle network — enterprise blockchain BD across EMEA. | [LinkedIn](https://ie.linkedin.com/jobs/view/account-executive-emea-at-chainlink-labs-4405638875) |
| B4 | **Strategy BD Associate** | Aave Labs | Remote | DeFi protocol, strategy-level BD. Engineering background valued. | [web3.career](https://web3.career/strategy-business-development-associate-aavelabs/149620) |
| B5 | **Director of Sales, EU** | Securitize | Spain | Tokenized securities / RWA — bridges traditional finance + blockchain. EU-focused. | [LinkedIn](https://es.linkedin.com/jobs/view/director-of-sales-eu-at-securitize-4342979508) |
| B6 | **Business Development Lead** | Pod Network | UK / Remote | Web3 infrastructure startup, BD lead level. | [LinkedIn](https://uk.linkedin.com/jobs/view/business-development-lead-at-pod-network-4318516275) |

---

### Priority ranking

**Top matches (all profile dimensions aligned):**
- A1 — Tandem NewSpace: startup + engineering + innovation toolbox + NewSpace BD, co-founder level
- A2 — Loft Orbital VP BD: senior, commercial, NewSpace scale-up
- A4 — Infleqtion Quantum/Space: engineering + deep tech + BD explicitly stated
- A5 — Aalto R2B: innovation toolbox + startup ecosystem exact fit
- B1 — Wert.io: remote, blockchain startup, BD lead

**Cross-track wildcard:** imec (A6) does blockchain/distributed systems research alongside hardware deep tech; Securitize (B5) is heavily engineering-weighted.

**Next actions:**
- [x] A1–A8 / B1–B6 identified (2026-05-21)
- [ ] Review full JDs for A1, A2, A4, B1, B3
- [ ] Tailor CV to highlight: startup experience · engineering background · innovation frameworks · sector (space OR blockchain)
- [ ] Check for newer listings — space sector roles turn over fast
- → *See §10 for the 2026-05-23 follow-up search targeting the Business Innovation Manager dimension*

---

## 8. Onboarding UX Design

### Reference: WorldMonitor (worldmonitor-core.vercel.app)

WorldMonitor was used as the UX benchmark. Studied via live browser session (2026-05-21).

**Key patterns extracted:**

| Pattern | WorldMonitor implementation | Applied to browser-use |
|---|---|---|
| **Category tag** | "LIVE INTELLIGENCE PLATFORM" pill | "AI BROWSER AGENT" label |
| **Single-viewport hero** | All critical info above the fold, zero scroll to CTA | Install command + objection killers fit one screen |
| **3-stat credibility bar** | 150+ data sources · <1s load · 24h horizon | 3 commands to install · ~50ms per action · 15+ LLM providers |
| **Single primary CTA** | Glowing "Get Started →" button | `pip install browser-use` as the one thing to do first |
| **Objection killers below CTA** | "No account required. Your data stays local." | "No account needed. Free and open source (MIT)." |
| **Dark minimal chrome** | No competing elements, all attention to value prop | Minimal prose, code-block-first, scannable headers |
| **Personalization signal** | "personalized to you" in headline | "Tell it what to do. Watch it go." — outcome-focused |

### Design decisions in `ONBOARDING.md`

**1. Hero block first, not a README dump**
Opens with what it does (one sentence), proof stats, and the install command — not installation prerequisites or architecture diagrams.

**2. Copy-paste task before explanation**
The first code block is a complete, runnable task example. User sees the output model before reading how it works. Show > tell.

**3. Three-path selector** (CLI / Python Agent / Cloud)
Mirrors the "personalized to you" WorldMonitor pattern. Each path has a clear "best for" so users self-select instead of reading everything. Reduces cognitive load for the majority who only need one path.

**4. Friction FAQ as a first-class section**
Five targeted objections killed directly: account requirement, LLM choice, Windows compatibility, form-submission safety, stopping mid-run. Each answer is ≤2 sentences. Zero waffle.

**5. "What's next" as a routing table**
Intent-based rows ("You want to…" → link) rather than a flat list of docs. Copies the outcome-oriented framing of the WorldMonitor hero.

**6. Progressive disclosure throughout**
Custom tools, cloud auth, LLM provider table — all deferred to later sections. The 60-second path doesn't require reading any of them.

### File location

`ONBOARDING.md` — project root, alongside `BLUEPRINT.md` and `README.md`.

Referenced from `BLUEPRINT.md §8` (this section).
Intended audience: new users arriving at the GitHub repo for the first time.

### UX gaps to address in future iterations

- [ ] Add an animated GIF or short screen-recording of the agent completing a real task (equivalent to WorldMonitor's live stat counters)
- [ ] Add a "time to first result" benchmark (e.g., "median 47 seconds from install to first completed task")
- [ ] Localise the Windows friction section — add a one-liner to permanently fix the `PYTHONIOENCODING` issue in PowerShell profile
- [ ] Add a copy button to all code blocks (if hosting as a web doc)

---

## 9. Udemy Curriculum → deeptechx.xyz (2026-05-22)

### Task
Fetch module/lecture outlines from Udemy instructor course and populate the curriculum on deeptechx.xyz.

- **Udemy course:** https://www.udemy.com/instructor/course/7092157/manage/curriculum/
  - Course title: *DeepTechX Launchpad — From Vision to Execution Framework*
- **Target site:** http://deeptechx.xyz (hosted at https://deeptechx.vercel.app, source: https://github.com/dnzengou/deeptechx)

### How Cloudflare Was Bypassed
Headless Chromium and Chrome profile modes both hit Cloudflare's "Just a moment…" check.  
Solution: `browser-use cloud connect` provisions a stealth cloud browser via `BROWSER_USE_API_KEY`.  
User authenticated via the live browser URL: `https://live.browser-use.com/?wss=...`

### Udemy Curriculum Extracted (12 sections)

| # | Section | Key Lectures |
|---|---------|-------------|
| 1 | EO Space Data Commercialization | The Earth Observation Startup Playbook (Parts 1 & 2) |
| 2 | AI Agency Launchpad | Local AI Automation Agency (The "Digital Operator") |
| 3 | Tokenomics & Real-World Assets Tokenization | Tokenomics and RWAs Tokenization Presentation |
| 4 | Stratégie Financière Africaine: Réserves de Bitcoin | Reserve de bitcoin strategie nationale |
| 5 | Post-Quantum Cryptography & Quantum-Safe Systems | PQC & Systems, The Crypto Agility Manifesto |
| 6 | The AI-Powered Consulting Revolution | Consulting Productization Training — Productize Yourself! |
| 7 | Human-Centered Design for Deep Tech Innovation | The Commercial Velocity Playbook |
| 8 | Deep Tech Venture Launchpad — From Scientist to Scalable Startup | The Expert Trap & The 5-Steps Framework |
| 9 | Space Technology in Healthcare | EGNSS In Healthcare |
| 10 | Space & Gaming | Why Space Tech-Enabled Gaming is More than a Game |
| 11 | Boardroom Statecraft 2026 | Navigating the Global Drift |
| 12 | Bridging Space Technology with User Needs on Earth | EGNSS+EO Data for Mobility, Health, Logistics, Climate |

### What Was Updated in deeptechx.xyz
Site is a **Vite + React + TypeScript SPA** (Bolt.new origin, code-path attributes in DOM).  
Source at `dnzengou/deeptechx` → `src/App.tsx`.

Changes to `src/App.tsx` (commit `c0d67b3`):
1. Added `description` field to every module object (specific, non-generic)
2. Added `lectures: string[]` field mapping Udemy section/lecture titles to each module:
   - M01 ← Human-Centered Design
   - M02 ← Deep Tech Venture Launchpad (5-Steps Framework)
   - M04 ← Tokenomics + Bitcoin Reserves (FR)
   - M05 ← AI Agency / Digital Operator
   - M06 ← PQC + Crypto Agility Manifesto
   - M08 ← 6 lectures across EO, Space/Health, Space/Gaming, EGNSS
   - M09 ← Boardroom Statecraft 2026
   - M14 ← Consulting Productization
3. Updated dialog popup rendering: replaces generic filler copy with `module.description` and renders `module.lectures` as a `Play`-icon bullet list under a **"UDEMY LECTURES"** heading

### Deployment
- Push to `main` → Vercel auto-deployed in ~2 seconds
- Deployment ID: `4787620260`, status: `success`
- Live at: https://deeptechx.vercel.app / http://deeptechx.xyz

---

## 10. Job Search v2 — Business Innovation Manager Profile (2026-05-23)

**Session method:** "caveman + karpathy + fixclaude" — strip the search to first principles, no fancy aggregation, direct signal over noise.

**Profile pivot from §7:** This search targets the *Business Innovation Manager* dimension of the profile (GeoVille, EUSPA CASSINI, Antler) rather than the BD/blockchain angle. Key differentiators being leveraged: 15 yrs deep tech breadth (space EO + AI/ML + quantum + blockchain), EU institutional network, startup coaching/acceleration, curriculum development, international profile (EU/Africa/Americas).

**Sources attempted vs. accessible:**

| Board | Result |
|-------|--------|
| LinkedIn Jobs | Login wall — partial scrape only (4 cards visible) |
| RemoteOK | Premium paywall |
| Google Jobs | Cloudflare CAPTCHA |
| Indeed | Cloudflare block |
| WeWorkRemotely | 0 results for the query |
| Remotive | 404 on search URL |
| Wellfound | Bot detection block |
| Space-Career.com | ESET antivirus block (local) |
| **ESA jobs.esa.int** | ✅ Clean access — 15 results |
| **Bing Jobs** | ✅ Clean access — 7 unique listings |

**Anti-bot lesson:** All major boards (LinkedIn, Indeed, Google, Wellfound) block headless Chromium via Cloudflare or fingerprinting. ESA and Bing are the most open aggregators for this use case without login.

---

### 🚀 Track C — Innovation / Deep Tech Founder & Analyst Roles (Remote)

| # | Role | Company | Type | Location | Fit signal | Apply |
|---|------|---------|------|----------|-----------|-------|
| C1 | **Space Tech Co-Founder / CMO** | EWOR | Full-time | 100% Remote (EU/Americas) | ⭐⭐⭐⭐⭐ Build your own space tech startup; salary + up to €500k funding; 1:1 with unicorn founders (Adjust €1.2B, SumUp €8B). Perfect for serial builder profile. | [Jobrapido](https://www.jobrapido.com) / [LinkedIn](https://linkedin.com) |
| C2 | **AI Co-Founder / CCO** | EWOR | Full-time | 100% Remote (EU/Americas) | ⭐⭐⭐⭐⭐ Same EWOR programme, AI-focused. CCO angle covers customer/commercialisation — matches the coaching + ML deployment background. | [LinkedIn](https://linkedin.com) |
| C3 | **Senior Director, Analyst — Strategic Innovation Insights** | Gartner | Full-time | Remote Europe | ⭐⭐⭐⭐⭐ "Innovate the innovation process" for CIOs. 12+ yrs tech/business, emerging tech (AI, quantum, autonomous), consulting background, executive presence. JD reads as a direct description of the profile. Job ID: 108490 | [Gartner Careers](https://jobs.gartner.com) / LinkedIn |
| C4 | **Earth Observation Service Manager** | ESA | 4-yr contract | Frascati, Italy (on-site) | ⭐⭐⭐ Strong EO/satellite background via GeoVille. Not remote; requires relocation. Closes 12 June 2026. | [jobs.esa.int](https://jobs.esa.int) |
| C5 | **COSMIC Project Manager** | ESA | 4-yr contract | Darmstadt, Germany (on-site) | ⭐⭐ TPM background (Google). Not remote. Closes 29 May 2026. | [jobs.esa.int](https://jobs.esa.int) |

---

### EWOR Programme Detail (C1 + C2)

- Salary while building your startup, OR up to €500k in equity funding (founder's choice)
- Weekly 1:1 with unicorn founders
- Network: top 0.1% founders + 50,000+ professionals for hiring
- Average EWOR fellow raises >€2M after Grand Pitch (12-month target)
- Record: €12M pre-seed by a first-time founder
- Requirement: based in Europe or Americas, or willing to relocate; full ownership of startup

### Gartner Senior Director Detail (C3)

- Audience: C-level clients (CIOs, CTOs) of enterprise organisations globally
- Content area: Innovation and Emerging Technologies — AI (including Physical AI), quantum, autonomous systems, digital sovereignty, cybersecurity
- Output: "must-have" research notes, predictions, keynotes at Gartner events
- Key differentiator asked for: *re-engineer the innovation pipeline* away from "innovation theater" → practical, tech-driven, agentic
- Travel: up to 25%
- Hands-on GenAI literacy required (Gemini, ChatGPT, Copilot, agentic tools)

---

### Priority Ranking (§7 + §10 combined)

**Tier 1 — Exact profile fit, apply immediately:**
1. **C1 / C2** — EWOR Space Tech / AI Co-Founder: serial builder profile + space + AI + remote = perfect vector
2. **C3** — Gartner Senior Director: the JD is a word-for-word description of what this profile does
3. **A1** — Tandem NewSpace Co-founder BD (§7): engineering + startup + NewSpace combo

**Tier 2 — Strong fit with one gap (location or narrow scope):**
4. **A4** — Infleqtion Quantum/Space BDM
5. **A2** — Loft Orbital VP BD EMEA
6. **B1** — Wert.io remote blockchain BD
7. **C4** — ESA EO Service Manager (if open to Frascati relocation)

**Tier 3 — Good signal, worth monitoring:**
8. **A5** — Aalto R2B Business Developer
9. **A6** — imec Senior BDM
10. **B3** — Chainlink EMEA AE

---

### Next Actions (§10 — updated 2026-05-30)

- [x] **EWOR Fellowship application SUBMITTED ✅** — 2026-05-30. Confirmation: `https://www.ewor.com/thank-you`. "Application successfully submitted. We review on a rolling basis."
- [x] Gartner Job 108490 closed → replaced by Job 110514 (Sr Director Analyst - Innovation & Emerging Tech, Remote EU) — Workday page open
- [x] Bing Jobs alert saved (SAVED SEARCHES 1) — login with `desire.yavro@gmail.com` to activate email alerts
- [ ] Provide EWOR 1-min pitch video URL (Loom/YouTube/LinkedIn) to unblock form submission
- [ ] Upload pitch deck PDF to EWOR form at `https://form.ewor.com/t/sn9FZVeJWkus`
- [ ] Apply to Gartner 110514 via Workday (Apply button at element [45])
- [ ] See §11 for new Nordic/Remote EU innovation leads (EIT Health, SMRT Copenhagen)

---

## §11. Job Search v3 — Nordic & Remote EU Innovation Roles (2026-05-28)

> Methodology: Himalayas.app, ESA Jobs, Bing Jobs, LinkedIn public, Remotive, Vinnova direct check. IP 81.223.72.186 blocked by Google/Indeed/Wellfound. Results file: `C:\Users\nzengou\Documents\Perso\job_search_innovation_2026-05-28.md` (local only, not committed).

### New Tier 1 Leads (additive to §10)

| ID | Title | Company | Location | Deadline | Match |
|----|-------|---------|----------|----------|-------|
| D1 | **Innovation to Market Manager** (m/f/d) | EIT Health | Remote FR/DE/PL/ES | **28 Jun 2026** | ⭐⭐⭐⭐ EU programme management, 5+ yrs, exact EUSPA pattern |
| D2 | **Sr Director Analyst — Innovation & Emerging Tech** | Gartner BTI | Remote UK/Europe | Open | ⭐⭐⭐⭐ Replaces closed C3 (Job 108490); digital assets + blockchain |
| D3 | **Innovation Manager, Project & Engineering** | SMRT Corporation | Copenhagen, DK | Open | ⭐⭐⭐ Nordic base (DK), metro infrastructure + engineering PM |

### Nordic Career Pages to Monitor

| Company | Type | Why |
|---------|------|-----|
| Ericsson | Deep tech / 5G / AI | Stockholm HQ; innovation strategy roles |
| Saab AB | Defence / space | Space/EO, Swedish, innovation labs |
| RISE Research Institutes | Swedish public R&D | Programme management, Govt-adjacent |
| Business Sweden | Innovation export | Africa/APAC cross-sector focus matches profile |
| EIT Digital | EU digital innovation | Same DNA as D1 (EIT Health), digital-first |
| Innovation Norway | Nordic public body | Cross-sector mandate, Nordic ecosystem |

### WorldMonitor RSS Feeds Curated (2026-05-28)

Platform: `worldmonitor-core.vercel.app` — fuses GDELT + ADS-B + AIS + RSS. Feed list curated to match profile domains (space, AI, EU policy, Africa, startup/VC):

```
# SPACE & EARTH OBSERVATION
https://spacenews.com/feed/
https://www.space.com/feeds/all
https://www.esa.int/rssfeed/Our_Activities/Space_Engineering_Technology/rss20.xml

# AI & DEEP TECH
https://techcrunch.com/category/artificial-intelligence/feed/
https://venturebeat.com/category/ai/feed/
https://feeds.feedburner.com/mit-technology-review/

# EU INNOVATION & POLICY
https://eic.ec.europa.eu/news/rss.xml
https://www.politico.eu/section/tech/feed/

# AFRICA & EMERGING MARKETS
https://african.business/feed/
https://techcabal.com/feed/
https://disrupt-africa.com/feed/

# STARTUP / VC
https://news.crunchbase.com/feed/
https://sifted.eu/feed/

# GEOPOLITICS
https://feeds.reuters.com/reuters/worldNews
https://rss.nytimes.com/services/xml/rss/nyt/World.xml
```

- [ ] Set a Bing Jobs alert for: "innovation manager deep tech space AI senior remote"

---

## §12. Resume Site & GitHub Portfolio (2026-05-30)

### Live Resume Site

**URL:** `https://resume-site-zeta-sepia.vercel.app`

- Source: `C:/Users/nzengou/Documents/programming/test_programming/resume-site/`
- Deployed via Vercel (project: `dnzengous-projects/resume-site`)
- 3 resume tabs: **BD/Space Tech · Tech/Product · Startup/Innovation**
- Content sourced from 3 master CVs in `C:/Users/nzengou/Documents/Perso/`:
  - `CV_Nzengou_BD_SpaceTech_2026.pdf` (379KB)
  - `CV_Nzengou_TechProduct_2026.pdf` (356KB)
  - `CV_Nzengou_StartupInnovation_2026.pdf` (954KB)
- Each tab has a per-tab PDF download button (PDFs served from same domain)
- Dark mode + print-to-PDF per tab
- ATS-safe layout, no tables

### GitHub Portfolio Items Extracted (dnzengou)

| Repo | Domain | Stack | Highlight |
|------|--------|-------|-----------|
| worldmonitor | AI/Geospatial | TypeScript | Real-time GDELT+AIS+ADS-B intelligence dashboard |
| wm-agents-claude | AI Agents | TypeScript | Multi-agent Claude API pipeline |
| cas_dashboard | CAS/Space | Python | Complex Adaptive Systems for space policy |
| carbon-credit-backed-stablecoin | Blockchain/Climate | Solidity | Climate DeFi instrument |
| quantum-computing-w-qiskit | Quantum | Jupyter | Quantum circuit optimisation |
| AutoResearchClaw | Research AI | — | Autonomous idea→paper pipeline |
| deeptechx | Startup | TypeScript | Deep-tech founder launchpad |
| graphify | AI Tooling | — | Code→knowledge graph for RAG |
| worldmodel-geosim | Geospatial | Python | World-model geospatial simulation |
| Universal_Agentic_Advisory_Platform | Advisory | TypeScript | Strategic decision framework |
| bmc | BD Tools | HTML | Interactive Business Model Canvas |
| jobs-for-ai-agents | HR Tech | — | AI job-search Claude Code tool |

### Next Actions §12
- [ ] Add custom domain (e.g. `cv.desiredsolutions.me`) via Vercel DNS settings
- [ ] Enrich with LinkedIn-scraped experience bullets (requires manual review)
- [ ] Generate PDF versions per tab for email attachments
- [ ] Apply `deeptechx.xyz` or `desiredsolutions.me` subdomain

