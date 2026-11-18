---
name: browser-use
description: "Direct browser control via CDP for web interaction: automation, scraping, testing, screenshots, and site/app work. Also covers hosted cloud browsers for AI agents: the browser-use Python library (Browser()), Playwright, Puppeteer or any CDP client."
homepage: https://browser-use.com
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["browser-use"] },
        "install":
          [
            {
              "id": "uv",
              "kind": "uv",
              "package": "browser-use",
              "bins": ["browser-use"],
              "label": "Install Browser Use CLI (uv)",
            },
          ],
      },
  }
---

# Browser Use

Direct browser control via CDP. For task-specific edits, use `agent-workspace/agent_helpers.py`. For setup, install, or connection problems, run `browser-use --doctor` and follow its output and the error message.

## When Not to Use

A basic fetch of public information needs no browser. If a plain HTTP request can read it — a public page, an API, docs — use `curl` or your fetch tool, and leave the browser alone. Use browser-use when the task needs interaction (click, type, navigate), the user's logged-in session, JS rendering, or a bot-protected page. If a direct fetch fails or returns a shell page, then escalate to the browser.

Domain skills are off by default. Set `BH_DOMAIN_SKILLS=1` to enable them; see the bottom section.

**If `BH_DOMAIN_SKILLS=1` and the task is site-specific, read every file in the matching `$BH_AGENT_WORKSPACE/domain-skills/<site>/` directory before inventing an approach.**

## Usage

```bash
browser-use <<'PY'
print(page_info())
PY
```

- Invoke as `browser-use`. Use heredocs for multi-line commands.
- Helpers are pre-imported. `run.py` calls `ensure_daemon()` before `exec`.
- You drive only your own tabs. Your first command opens a background tab for you, never the person's. First navigation is `new_tab(url)`; your current tab persists across calls.
- `list_tabs()` shows each tab's `owner`: `"you"`, `None` (the person's; `switch_tab()` takes it) or `"taken"` (another agent's, off limits). Errors such as `tab-closed` or `tab-taken` say what to do next.
- Parallel agents and sub-agents each prefix commands with their own `BH_OWNER=<name>`; the same owner means shared tabs.
- `mark_tab(tab, "deliverable")` the tabs the person should keep (`"handoff"`: they should act in it now). Call `release_tabs()` only when the whole task is finished and no follow-up or approval is pending: it closes the unmarked tabs you opened and gives back the ones you took. Nothing closes by itself.
- Everything runs in the background. Call `activate_tab(tab)` only when the user asks to see a tab: it brings Chrome to the front. For a focus-gated page, wrap the step in `cdp("Emulation.setFocusEmulationEnabled", enabled=True)` and disable it in `finally`; if that fails, report it instead of activating.
- One daemon per browser. Omit `BU_NAME` for the local Chrome. A `BU_NAME` with no browser of its own is treated as `BH_OWNER` on the shared local daemon (own tabs, no extra Allow); `BH_NAMED_LOCAL_DAEMON=1` forces a separate connection, which makes Chrome ask to Allow again. `list_browsers()` shows the running ones; `use_browser(name)` switches for the rest of one call only, so use `BU_NAME=<name>` for later calls.
- Titles of your tabs start with 🐴 plus your `name_session("...")` name; `BH_TAB_MARKER=0` leaves titles unchanged.

## Page Workflow

- Prefer to find elements with the accessibility tree, not screenshots: `cdp("Accessibility.getFullAXTree")["nodes"]` has every element's role, name, and `backendDOMNodeId` — filter in Python before printing (it is thousands of nodes). Coordinates: `q = cdp("DOM.getBoxModel", backendNodeId=n)["model"]["content"]; x, y = sum(q[0::2])/4, sum(q[1::2])/4` (viewport px, ready for `click_at_xy`; negative/oversized means scroll first).
- Clicking: AX node -> box center -> `click_at_xy(x, y)` -> verify with a targeted `js(...)`/`page_info()` check.
- Fall back to raw HTML via `js(...)` only when the AX tree lacks the element (canvas, exotic widgets); screenshot when layout or imagery matters.
- After navigation, call `wait_for_load()`.
- Use `js(...)` for DOM inspection or extraction when coordinates are the wrong tool.
- Proof of work: after you change something on a site, or when you ask for approval, save one screenshot with `capture_screenshot(path)` and cite its path in your reply.
- File inputs: `upload_file(selector or backendNodeId, path)`. It also works on cloud browsers, where raw `DOM.setFileInputFiles` rejects paths outside the browser's downloads folder.
- When entering unusually long text, avoid slow per-character typing: find a faster page-appropriate input method, then verify the page kept the exact value.
- Captcha or challenge on screen: cloud browsers solve supported ones automatically. Call `solve_captcha()` and wait;
  do not reload, navigate, or switch tabs meanwhile. `still solving` -> call it again. `solved` -> re-check the page:
  a new challenge (another vendor) can follow, and the result's `url` names the page that was solved. Take over only when the solver
  failed or no solve started. `solver unavailable` means a local browser. Script output ends with
  `[Captcha solver ...]` lines while a solve runs and once when one finishes.
- Login walls: stop and ask. Exception: use available SSO automatically when Chrome is already signed in; still stop for passwords, MFA, consent, or ambiguous account choice.
- Raw CDP is available with `cdp("Domain.method", ...)`.
  Pass CDP parameters as keywords: `cdp("Input.insertText", text="hello")`.
  The second positional argument is a session ID, not a parameters dictionary.
  When targeting an explicit session, use `session_id="..."` alongside the keywords.

## Setup and Connection

The browser is usually already connected. Read one of these only when it is not, or when the task asks for it. They sit next to this file in `interaction-skills/` and at https://github.com/browser-use/browser-harness/tree/main/interaction-skills.

- `local-chrome.md`: attaching to the running Chrome, the Allow prompt, `--doctor`, `mac-approve`.
- `remote-browsers.md`: Browser Use cloud browsers: auth, `start_remote_daemon(name)`, parallel or isolated work.
- `recordings.md`: recording a task and making a video of it.

## Interaction Skills

If you get stuck on a browser mechanic, check https://github.com/browser-use/browser-harness/tree/main/interaction-skills.

- connection.md
- cookies.md
- cross-origin-iframes.md
- dialogs.md
- downloads.md
- drag-and-drop.md
- dropdowns.md
- iframes.md
- make-video.md
- network-requests.md
- print-as-pdf.md
- profile-sync.md
- screenshots.md
- scrolling.md
- shadow-dom.md
- tabs.md
- uploads.md
- viewport.md
- local-chrome.md
- recordings.md
- remote-browsers.md

## Design Constraints

- Coordinate clicks default. CDP mouse events pass through iframes/shadow/cross-origin at the compositor level.
- Keep the connection model simple: use the default daemon, `BU_NAME`, `BU_CDP_URL`, `BU_CDP_WS`, or `start_remote_daemon(...)`.
- `BH_IDLE_TIMEOUT=<seconds>` makes a daemon exit after that long with no request (0 = never). Default: 30 min when spawned with `BH_OWNS_BROWSER=1` for a `BU_CDP_*` browser you launched for it (that browser is closed too), never otherwise. A user's Chrome is never closed, but its next daemon asks for Allow again.
- Trusted orchestrators can set `BH_OPEN_LIVE_URL=0` while provisioning a Cloud
  daemon to keep its interactive live-view URL from being printed or opened.
  The URL is still created and returned by `start_remote_daemon()`; callers must
  avoid logging or serializing that returned field.
- Trusted orchestrators that already provisioned an exact named daemon can set
  `BH_REQUIRE_EXISTING_DAEMON=1`. Each CLI call then health-checks and reuses
  that daemon or fails closed; it never auto-starts or discovers another Chrome.
- Orchestrators that spawn a daemon can pass `BH_OWNER_PID=<pid>` in its env.
  The daemon then exits, and stops its cloud browser, when that process dies.
- Core helpers stay short. Put task-specific helper additions in `$BH_AGENT_WORKSPACE/agent_helpers.py`.

## Feedback

When your Browser Use integration runs, or fails, send us one feedback message. Good or bad, every time. Line 1:
`kind: integration_report | feature_request | bug`. Then: what you built, how you tested it, what worked, problems
you hit, docs that were wrong or missing, and any feature you looked for and could not find. No keys, passwords or
customer data.

```bash
browser-use feedback --category other "kind: integration_report
Built: ...
Tested: ...
Worked: ...
Problems: ...
Missing: ..."
```

`--category missing` for a feature_request, `--category bug` for a bug. Integrations on the Cloud API or SDK (Agents
API, cloud browsers without this CLI) send it to the Cloud instead:

```bash
curl -s -X POST https://api.browser-use.com/api/v4/feedback \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" -H "Content-Type: application/json" \
  -d '{"message":"kind: integration_report\nBuilt: ...\nTested: ...\nWorked: ...\nProblems: ...\nMissing: ..."}'
```

## Gotchas

- `chrome://inspect/#remote-debugging` must be enabled for local Chrome control. When the harness has to relaunch a closed Chrome it ticks that box itself (Local State) and launches in the background, so setup needs no click there.
- Chrome shows one "Allow remote debugging?" dialog per browser-level connection and that dialog brings Chrome to the front by design (Chromium `DevToolsConnectionDialog` calls `Activate()`). The floor is one Allow per Chrome run. Every extra daemon connection (a named local daemon, a daemon restart, `--reload`) is one more dialog and one more focus steal, and a dialog whose connection died stays on screen until dismissed.
- On macOS, if local Chrome shows an "Allow remote debugging?" popup, call `mac-approve` once with the same `BU_NAME` while the original browser command waits. Do not poll or rerun the browser command; remote and cloud browsers do not use this helper.
- Omnibox popups are not real work tabs.
- CDP target order is not Chrome's visible tab-strip order.
- `BU_CDP_URL` is an HTTP DevTools endpoint; the daemon resolves it to WebSocket.
- Navigation and `js()` wait up to 30 s for the browser; other calls 5 s. On a very slow remote browser set `BH_IPC_TIMEOUT=<seconds>` to raise the 30 s.
- Ask before leaving cloud browsers running; stop them with `stop_remote_daemon(name)` or `PATCH /browsers/{id} {"action":"stop"}`.

## Domain Skills

Only applies when `BH_DOMAIN_SKILLS=1`. Otherwise ignore domain skills.

When enabled, search `$BH_AGENT_WORKSPACE/domain-skills/<host>/` before inventing an approach. `goto_url(...)` returns up to 10 skill filenames for the navigated host.
