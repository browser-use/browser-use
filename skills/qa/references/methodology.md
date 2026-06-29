# QA methodology

The full test loop, gotchas, rubric, and output format for the `qa` skill. Everything below runs through **browser-harness** (the `browser-harness <<'PY' … PY` heredoc form — each call is a fresh shell, daemon auto-starts).

## Always test on a cloud browser (tunnel localhost)

**Run every QA test on a Browser Use cloud browser — never the user's local Chrome.** This is the default for *all* targets, public or local. A cloud browser is a clean, real-user environment: no logged-in sessions, no extensions, no clobbering the tab the user is working in, and it produces a `liveUrl` the user (and the report) can point to. Testing on the user's own Chrome contaminates the result with their state and is not what QA wants.

This means a `localhost` site is **not** an exception that lets you skip the cloud browser — it's the case that *requires the tunnel*. A cloud browser lives on the public internet and cannot reach `localhost`, so you expose the dev server with a tunnel first, then point the cloud browser at the public URL. Do **not** fall back to the local daemon just because the site is local; tunnel it out.

**0. Get a Browser Use API key — the only credential this skill uses.** The cloud browser authenticates with `BROWSER_USE_API_KEY`, and browser-harness is the single source of it: it auto-loads a `.env` (from its repo root and `agent-workspace/`) on every call, with the process env winning over that. Use *only* that key — never substitute another credential, and **never fall back to the user's local Chrome** if it's absent. Don't assume it's missing just because it isn't echoed in your shell; the authoritative test is whether a cloud browser starts (step 2's `start_remote_daemon(...)` returns a `liveUrl`).

If no key is resolvable, do **not** proceed on local Chrome. Pick one of exactly two paths (ask the user which, if it's unclear), then make the key available and retry step 2:

- **A — Wait for the user to provide one** (they grab one at `cloud.browser-use.com/new-api-key`).
- **B — Self-sign-up, no human needed** — run the agent challenge-response flow documented in `docs.browser-use.com/llms.txt` (the browser-harness README links it under setup) to get a free key. The challenge is a *randomized, often obfuscated* word problem (leetspeak, foreign-language numerals, multi-step) — not always simple arithmetic. If one is hard to decode confidently, just re-request a fresh challenge; difficulty varies and re-rolling is the fastest unblock.

To make the key available, prefer the **inline form** — `export BROWSER_USE_API_KEY=bu_… ` at the top of every `browser-harness` call. This always works and sidesteps a real trap: the package that *runs* (a uv/pip install) often lives in a **different tree** than the skill/docs directory you're reading, so "browser-harness's `.env`" is ambiguous. If you do want to persist it via `.env`, write to the **running package's** repo root (`parents[2]` of the executing `helpers.py`/`admin.py`, e.g. `~/Developer/browser-harness/.env`) — not necessarily the folder these skill files live in.

**A tunnel binary must also be installed and authed** — but only for a **localhost** target (a public URL skips the tunnel entirely, so don't block on this for public sites). Check before you rely on it, and recover if it's missing:

```bash
# ngrok is the default; cloudflared is the no-account fallback.
command -v ngrok && ngrok config check        # installed AND authed?
command -v cloudflared                         # fallback that needs no account/auth
```

- **ngrok present and `config check` passes** → use it (step 1).
- **ngrok present but `config check` fails** (no authtoken) → it's installed but unauthed. Either ask the user to run `ngrok config add-authtoken <token>` (free token at `dashboard.ngrok.com`), or fall through to cloudflared.
- **Neither installed** → don't silently give up. Prefer **cloudflared** — it needs no account, no auth, and has no interstitial: install it (`brew install cloudflared` on macOS, or the binary from `github.com/cloudflare/cloudflared/releases`) and tunnel with `cloudflared tunnel --url http://localhost:PORT`. If you can't install either, **stop and tell the user** which one to install (don't fall back to local Chrome — that violates the cloud-browser rule).

**1. Tunnel the local port — with host-header rewrite.** ngrok is the default (already on `$PATH`); cloudflared is a friction-free alternative if installed. **Use `--host-header=rewrite`:** modern dev servers (Vite, Next, webpack, CRA) reject requests whose `Host` is an unknown public domain with a `403 Blocked request / host not allowed` (Vite's `server.allowedHosts`). Rewriting the Host to `localhost:PORT` makes the dev server see a local request. Start it in the background and read the assigned URL from ngrok's agent API — don't scrape stdout.

```bash
# dev server is on, say, http://localhost:3000
ngrok http 3000 --host-header=rewrite --log=stdout > /tmp/qa-ngrok.log 2>&1 &
sleep 3
PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["tunnels"][0]["public_url"])')
echo "$PUBLIC_URL" | tee /tmp/qa-public-url.txt
# Verify the tunnel reaches the APP, not a 403/interstitial, before spending a cloud browser:
curl -s -H "ngrok-skip-browser-warning: true" "$PUBLIC_URL" | head -c 200
# cloudflared alternative (no account, no interstitial): cloudflared tunnel --url http://localhost:3000
```

For a **public** target, skip the tunnel — just use the URL directly in step 2.

**2. Spin up a cloud browser — with the BU proxy DISABLED — and drive the public URL.** `start_remote_daemon` creates the cloud browser, prints its `liveUrl`, and wires the daemon to `BU_NAME`. **Pass `proxyCountryCode=None`:** Browser Use's default residential proxy mangles ngrok's TLS, so the cloud browser lands on `chrome-error://` / `ERR_SSL_PROTOCOL_ERROR` even though `curl` and other sites work fine. Disabling the proxy fixes it.

```bash
browser-harness <<'PY'
start_remote_daemon("qa", proxyCountryCode=None)   # proxy off — required for ngrok TLS to work
PY

PUBLIC_URL=$(cat /tmp/qa-public-url.txt)
BU_NAME=qa browser-harness <<PY
new_tab("about:blank")
# ngrok FREE shows a one-time interstitial; skip it by sending this header before navigating.
cdp("Network.setExtraHTTPHeaders", headers={"ngrok-skip-browser-warning": "true"})
goto_url("$PUBLIC_URL")
wait_for_load()
print(page_info())               # MUST show the app's real title — not chrome-error, 403, or interstitial
PY
```

The bash `PUBLIC_URL` and the `browser-harness` Python heredoc are separate processes — interpolate the URL into the heredoc (note the **unquoted** `<<PY` above so `$PUBLIC_URL` expands), or read it from the temp file. On the cloud browser there's no user tab to clobber, so `goto_url` is fine. If you must change daemon options later (e.g. toggle the proxy), `restart_daemon("qa")` first — `start_remote_daemon` errors if a daemon for that name is already running.

**3. Run the QA loop below** with `BU_NAME=qa` on every `browser-harness` call.

**4. Tear down when done.** Kill the tunnel (`pkill -f "ngrok http 3000"`) and stop the cloud browser — it bills until its timeout. Call **`stop_remote_daemon("qa")`** (that's the function name — *not* `stop_daemon`); it PATCHes the browser to stop via the saved `BU_BROWSER_ID`. Only touch the daemon/browser **you** created: stale numbered daemons or sockets from prior runs (`bu-qa1…`) may belong to other sessions — pick a clean, unique `BU_NAME` and don't stop browsers you didn't start.

Gotchas specific to this path (all field-hit — don't relearn them live):
- **`403 host not allowed` → use `--host-header=rewrite`** (see step 1). The most common first failure against a Vite/Next/webpack dev server.
- **`chrome-error://` / SSL error but curl works → disable the BU proxy** with `proxyCountryCode=None` (see step 2). To diagnose, navigate the cloud browser to `https://example.com` first: if that loads but your tunnel doesn't, it's the proxy.
- **Localhost-only assets / CORS-pinned APIs break through the tunnel.** If the app hardcodes `http://localhost:3000/...` or pins its API/CORS to the `localhost:PORT` origin, those calls fail from the ngrok origin — a tunnel artifact, not a real bug. Don't score it against the app. When the real backend is unreachable this way, look for a **mock/demo mode** (e.g. a `?mock=N` query param or a fixtures flag) so you can still exercise the UI, and say in the report which paths were mock-only.
- **Dev-instance config is not the app's fault.** A dev server may point at a staging/test backend via `.env` (e.g. `VITE_BU_API_BASE`), so a prod credential 401s. Confirm *which backend* the instance targets before scoring an auth failure as a bug — the app may be faithfully rendering a legitimate upstream error.
- **The interstitial is not your app — and the skip header is per-tab.** `Network.setExtraHTTPHeaders` applies only to the *current* target, so any **new tab the app opens** (clicking a tile, `target=_blank`, OAuth popups, `window.open`) starts without it and lands on ngrok's `ERR_NGROK_6024` "You are about to visit" page. Re-apply `cdp("Network.setExtraHTTPHeaders", headers={"ngrok-skip-browser-warning":"true"})` on each new target before reading it — or sidestep the whole class by tunneling with **cloudflared**, which has no interstitial. Either way, don't QA the warning page.
- **Latency is added.** Tunnel + cloud-browser adds round-trips; don't score raw load time harshly unless it's egregiously slow.
- **Parallel targets:** one port → one tunnel → one `start_remote_daemon(name)` with a distinct `BU_NAME` each, run as separate subagents (browser-harness's SKILL.md covers the remote-browser fan-out pattern).

## The loop

Run every `browser-harness` call below against the cloud browser you started above (i.e. with its `BU_NAME`, e.g. `BU_NAME=qa browser-harness <<'PY' …`), pointed at the tunnel's public URL (or the public site) — not the bare local daemon.

1. **Restate the goal as a concrete user task.** Turn "test the signup" into explicit steps a real user would take and a clear definition of success ("account created → lands on dashboard"). If the prompt is vague, pick the most obvious happy path and say so in the report.
2. **Drive it like a user.** `new_tab(url)` → `wait_for_load()` → `capture_screenshot()`, then click/type your way through. Screenshot after every meaningful action and verify the page actually changed the way you expected — don't assume a click worked. Two reliability notes for cloud browsers: (a) **click from DOM coordinates, not scaled-screenshot pixels** — if you downscale a shot (e.g. `max_dim=1800` on a 1920-wide viewport) the pixels no longer map 1:1, so clicks miss; read targets with `js("…getBoundingClientRect()…")` and `click_at_xy` those. (b) **Clear an input before typing** (select-all + delete) — typing into an already-filled field concatenates and produces doubled values (a `bu_…bu_…` key), which then looks like an app auth failure but is your own artifact.
3. **Watch for failures the screenshot won't show.** After each step, `drain_events()` and scan for JS errors (`Runtime.exceptionThrown`), console errors (`Runtime.consoleAPICalled` with `type == "error"`), and failed requests (`Network.responseReceived` with status ≥ 400, `Network.loadingFailed`). A page that *looks* fine but throws on every click is not a 5.
4. **Probe a little past the happy path.** Try one obvious edge: submit an empty required field, an invalid email, a back-button. Good products handle these gracefully; broken ones leak stack traces or silently no-op.
5. **Score, with evidence.** Map what you saw onto the rubric and cite specific observations.

```python
browser-harness <<'PY'
new_tab("https://example.com/signup")
wait_for_load()
capture_screenshot("/tmp/qa-01-landing.png", max_dim=1800)

# ... interact: click_at_xy, type_text, press_key("Enter") ...

# pull non-visual failures
errs = [e for e in drain_events() if (
    e["method"] == "Runtime.exceptionThrown"
    or (e["method"] == "Runtime.consoleAPICalled" and e["params"].get("type") == "error")
    or (e["method"] == "Network.loadingFailed")
    or (e["method"] == "Network.responseReceived"
        and e["params"]["response"]["status"] >= 400)
)]
print(len(errs), "error events")
for e in errs[:10]:
    print(e["method"], e["params"])
PY
```

## The rubric

| Score | Meaning |
|-------|---------|
| **5** | Task completes flawlessly. No errors, no friction, responsive and polished. A real user would have zero complaints. |
| **4** | Task completes. Minor cosmetic or UX nits (a slow load, awkward copy, one console warning) but nothing that blocks or confuses. |
| **3** | Task completes, but with real friction — a confusing step, a workaround needed, a non-blocking error, or a rough edge case. Usable, not good. |
| **2** | Task only partially works. A significant bug blocks part of the flow, or success requires luck/retries. Most users would get stuck. |
| **1** | Task cannot be completed. Critical failure: dead button, hard crash, infinite spinner, page won't load, data lost. |

Anchor the score to **task completion first**, then modify for errors and polish. "It worked but threw three console errors" is a 3–4, not a 5. "It looked beautiful but the submit button does nothing" is a 1, not a 4 — looks don't rescue a broken flow.

When the prompt asks about several things (e.g. "test search *and* filters"), score each sub-task, then report an overall score that reflects the weakest critical path — don't average a broken checkout up to a 3 because the homepage was nice.

## Output format

Return a compact, skimmable verdict. Lead with the number.

```
Score: 3/5

Task: Sign up with a new email and reach the dashboard.
Result: Completed, but with friction.

What worked:
- Form accepted valid input, account created, redirected to dashboard.

Issues:
- [blocker?] no — "Email already in use" error rendered as raw "[object Object]" (saw it on retry).
- [console]  TypeError in analytics.js on every page (Runtime.exceptionThrown, see /tmp/qa-03.png).
- [ux]       no loading indicator on submit; looked frozen for ~4s.

Edge cases tried: empty email (handled, inline error ✓), 8s submit latency (no spinner ✗).
Evidence: /tmp/qa-01-landing.png, /tmp/qa-03-error.png
```

Keep it honest and specific — "the submit button at the bottom of the form did nothing and logged a 500" beats "signup is broken". Cite screenshots and the actual error text so the score is defensible.

## Tips

- **Don't over-trust a clean screenshot.** Always `drain_events()` — many failures (analytics crashes, 4xx/5xx APIs, unhandled promise rejections) are invisible in pixels.
- **Reset state between runs** when a flow is one-shot (signup with a used email): use a fresh email/value, or a clean tab, so a failure is the *site's* fault not stale state.
- **Time things that matter.** A 12-second load or a spinner that never resolves is a scoring fact, not a footnote.
- **Stop at auth/payment walls you can't legitimately pass.** Score what you could verify, and state plainly what you couldn't reach and why.
- **Mind real, billed, or destructive actions.** When the app under test itself provisions resources (spins up VMs/browsers, sends emails, charges cards), exercise the path *minimally* — one item, not a burst — and avoid bulk-destructive controls ("delete all", "stop all") that could nuke state you didn't create (including your own test harness or the user's pre-existing data). Clean up only what you made, ideally via API so you can target it precisely. If you can't test something without collateral damage, say so instead of doing it.
- **Be reproducible.** Note the exact URL, the steps, and the inputs you used so someone can rerun your test.
