# Browser-Use × Claude Code — Interactive Agent Blueprint

> Living design document. Last updated: 2026-05-21. Sessions: setup · UX design · API key · job search · onboarding guide · GitHub push.

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
- [ ] Review full JDs for A1, A2, A4, B1, B3
- [ ] Tailor CV to highlight: startup experience · engineering background · innovation frameworks · sector (space OR blockchain)
- [ ] Check for newer listings — space sector roles turn over fast

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
