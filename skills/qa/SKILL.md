---
name: qa
description: QA-test a website or web app and return a 1-5 quality score (5 = flawless, 1 = broken) with evidence. Use when the user wants to test, QA, evaluate, score, or "check how good" a site, page, flow, or app — including a local dev server (e.g. "qa test localhost:5173", "does the checkout work?", "rate this landing page"). Drives a real Browser Use cloud browser, tunneling localhost automatically.
allowed-tools: Bash, Read, Task
---

# QA

Drive a website with a real browser, judge how well it does the thing the user asked about, and return a **score from 1 (broken) to 5 (excellent)** with evidence. The deliverable is a verdict, not a screenshot dump.

## Inputs

From the user's invocation (the text after `/qa`, or their message):
- **Target** — a URL (`https://…`) or a local dev server (`localhost:5173`, `:3000`, "the app on 5173"). **Required** — if absent, ask for it before doing anything else.
- **What to test** (optional) — a flow or focus ("the signup", "search + filters"). If omitted, test the most obvious happy path and say so in the report.

## Can you see images? (decide this first)

This skill's verdict is **visual** — you judge the app by looking at screenshots. So before anything else, check whether *you* — the agent running this skill — can actually see images:

- **You have vision (multimodal / image input)** → you can judge screenshots yourself. Continue to "Single flow vs. fan-out" below and choose by scale.
- **You have no vision (text-only model, no image support)** → you **cannot** judge screenshots, and neither can same-model subagents you'd spawn. You **must** hand the visual judgment to **Browser Use v2 cloud agents**, whose own LLM looks at the page server-side and returns a text verdict (`judge` pass/fail + a 1–5 `structuredOutput`). Use v2 for **every** flow — even a single one — per `references/browser-use-v2.md`. Do **not** drive `browser-harness` yourself to read screenshots, and do **not** fan out to your own (equally blind) subagents. The single-flow-vs-fan-out choice below does not apply to you — it's v2 either way.

If you're unsure whether you can see images, assume you can't and use v2.

## Single flow vs. fan-out (only if you can see images)

**Scale the approach to the ask:**

- **Testing one flow / one thing?** Don't bother with subagents — **drive `browser-harness` directly** yourself, following `references/methodology.md`. That's the right, lowest-overhead tool for a single test, and it's how the rest of this skill works.
- **Testing many flows / a lot at once?** **Fan out to subagents — one per flow — so they run in parallel.** Here the user has a choice of subagent type (ask if unclear; **recommend v2**):
  - **Browser Use v2 cloud agents — recommended.** Each flow becomes an autonomous v2 task with **`judge`** (pass/fail) + **`structuredOutput`** (1–5 score), running server-side and **in parallel**, returning step-by-step screenshot evidence. **Spends Browser Use credits** (~$0.01/task + ~$0.006/step + $0.02/hr browser). Per-task flow + how to fan out: `references/browser-use-v2.md`.
  - **Your harness's built-in subagents** — spawn Claude Code subagents (the Agent tool), each driving `browser-harness` through `references/methodology.md`. No Browser Use *task* credits; uses your agent's own usage.

Rule of thumb (**vision agents only** — text-only agents use v2 for everything, see above): **one flow → browser-harness directly; many flows → subagents (v2 recommended).** Either way `browser-harness` is required — as the direct driver, the subagent driver, the v2 key store, and the localhost tunnel.

## Dependency: browser-harness (required — install it yourself)

This skill runs the test through **browser-harness** — a separate tool you install once. It is not optional; QA must run on a real Browser Use cloud browser, never the user's local Chrome.

**Before anything else, verify it's available:**

```bash
command -v browser-harness && browser-harness <<'PY'
print("browser-harness OK")
PY
```

If `browser-harness` is **not** on `PATH`, **install it yourself — don't make the user do it.** QA runs on a *cloud* browser, so the CLI is all you need: **none** of browser-harness's local-browser setup (`chrome://inspect`, `--remote-debugging-port`, the "Allow remote debugging" popup) applies here — skip all of it. The install is one-time (~30s), no clone:

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh   # the uv installer, only if missing
uv tool install "git+https://github.com/browser-use/browser-harness"
command -v browser-harness                                         # verify it's on PATH now
```

(No `uv` and can't `curl | sh`? Install uv per https://docs.astral.sh/uv/getting-started/installation/ then re-run the `uv tool install` line — or `pipx install "git+https://github.com/browser-use/browser-harness"`.)

The only other thing a run needs is a `BROWSER_USE_API_KEY`, and that **also** auto-resolves with no human — see `references/methodology.md` step 0 (it can self-sign-up for a free key). So a fresh machine goes from "just installed `qa`" to a working test without the user doing any setup.

**Last resort only** — if you genuinely can't install it (no network, no Python): stop and have the user open **https://www.browser-harness.com/** and paste its **"prompt for LLMs"** into an agent:

> Set up https://github.com/browser-use/browser-harness for me. Read `install.md` first to install and connect this repo to my real browser. Then read `SKILL.md` for normal usage. Always read `helpers.py` because that is where the functions are. When you open a setup or verification tab, activate it so I can see the active browser tab. After it is installed, open this repository in my browser and, if I am logged in to GitHub, ask me whether you should star it for me as a quick demo that the interaction works — only click the star if I say yes. If I am not logged in, just go to browser-use.com.

Re-run `command -v browser-harness` and don't continue until it succeeds. Never fall back to the user's local Chrome.

Do not attempt to QA with anything other than browser-harness + a cloud browser.

## Procedure

1. **Confirm the target is reachable** (`curl -s -o /dev/null -w "%{http_code}" <url>`), and identify what the app is (title, README) so you can frame a sensible test task.
2. **Run it** — first apply the vision gate from "Can you see images?" above:
   - **No vision (text-only)?** → use **v2 cloud agents for every flow** (one v2 task per flow, each with `judge` + a 1–5 `structuredOutput`), per `references/browser-use-v2.md`. Skip the single-flow/subagent split below — it's v2 regardless of scale. Tunnel a `localhost` target and pass the public `startUrl`.
   - **Vision, one flow** → drive **browser-harness directly** per `references/methodology.md`: resolve the key, tunnel localhost, and run the test loop with the field-tested gotchas (host-header rewrite, proxy-off, per-tab interstitial header, CORS-pinned APIs).
   - **Vision, many flows → fan out, one subagent per flow:**
     - **v2 agents (recommended)** → per `references/browser-use-v2.md`, create one task per flow (each with `judge` + a 1–5 `structuredOutput` schema), poll them all, and collect the verdicts. A `localhost` target still needs a tunnel (the cloud agent can't reach localhost) — tunnel it and pass the public `startUrl`.
     - **Claude subagents** → spawn one Agent per flow, each following `references/methodology.md` on browser-harness.

   *Whenever you use the v2 backend (either the no-vision case or the recommended fan-out): as each task is created, open its dashboard thread `https://cloud.browser-use.com/thread/{sessionId}` (the **session id** from the create response — not the task id) in the user's local Chrome so they can watch the agent run — the reference's `open_local(...)` helper does this. Always print the URL too.*
3. **Tear down** what you started — stop **everything you opened**, on every path:
   - **Tunnel** — if you tunneled a `localhost` target, kill the tunnel process. This applies to **every** path that tunnels, **v2 included** (a v2 run against localhost still starts a tunnel) — don't leave it orphaned.
   - **Cloud browser** — the one-flow / Claude paths drive a browser-harness cloud browser; stop it.
   - A v2 task against a **public** URL has nothing to tear down (its one-off session auto-closes); a v2 task against **localhost** still leaves the tunnel, so close that.
4. **Return the verdict**: lead with `Score: N/5`, then task, result, what worked, issues (tagged), edge cases, and evidence — per the rubric and output format in `references/methodology.md`. **Fanning out?** Give a per-flow `Score: N/5` line and an **overall score that reflects the weakest critical path** (don't average a broken flow up because others passed).

Scale effort to the ask: a quick "does X work?" is a few interactions and one score; "thoroughly QA this" warrants more flows and edge cases. Keep the verdict honest, specific, and reproducible.
