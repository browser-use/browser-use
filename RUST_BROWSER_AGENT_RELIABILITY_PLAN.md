# Rust Browser Agent Reliability Plan

## Goal

Build a Rust-backed browser-use agent that ships inside the Browser Use library and reliably completes real browser automation tasks with the fewest practical model tokens and browser steps.

Concrete target:

- `real_v8` 100-task run above 90% by our own review, not only by the automated judge.
- Keep the default loop cheap enough that successful single-page tasks stay near the current fast path.
- Use Browser Harness semantics as the core browser action surface: raw CDP, screenshots, coordinate input, structured extraction, HTTP once discovered, and minimal helper code.
- Avoid a task compiler or pattern router. The model should infer intent from the user task using a simple general system prompt and good tools.

## Current Local State

The active Browser Use integration branch is:

- Repo: `/Users/magnus/Developer/browser-use`
- Remote: `https://github.com/MagMueller/browser-use.git`
- Branch: `magnus/browser-use-rust-wrapper`
- Rust wrapper: `browser_use/rust`

The Rust terminal/core worktree inspected is:

- Repo: `/Users/magnus/.superset/worktrees/terminal/MagMueller/testing-a-conversation-starter`
- Remote: `https://github.com/browser-use/terminal`
- Browser interaction tool: `crates/browser-use-browser`
- Prompt surface: `prompts/browser-agent-system.md`, `prompts/browser-script-tool-description.md`

The Browser Harness repo exists locally under:

- `/Users/magnus/.superset/worktrees/browser-harness/MagMueller/*`
- Remote: `https://github.com/browser-use/browser-harness`

I can create and stop Browser Use Cloud browsers with the local `BROWSER_USE_API_KEY`. I can inspect the local Rust state database at `~/.browser-use-terminal/state.db`. The missing local parity token is `UKC_TOKEN`, so exact Unikraft CI browser reproduction is unavailable unless that token is provided.

## Non-Goals

- No hard-coded task compiler.
- No routing layer that classifies `real_v8` task shapes and injects special plans.
- No site-specific prompt overfitting.
- No new broad browser framework on top of CDP.
- No Playwright/Selenium/Pyppeteer dependency.
- No judge-driven optimization without our own task-level review.

## Design Principle

The reliable path is not to make the prompt smarter by adding many rules. It is to make the browser tool and message history present the right information at the right granularity:

- The model gets one coherent browser action space.
- The model sees pixels when pixels matter.
- The model sees compact structured observations instead of huge DOM dumps.
- Long browser scripts can run, stream progress, emit checkpoints, and be observed without burning a full model turn per tiny action.
- Data discovered in the browser can move into cheap HTTP/bulk extraction inside the same `browser_script` call.
- The final answer is verified against the task requirements before `done`.

## Architecture Direction

### 1. Keep The Browser Surface Browser-Harness-Like

Use the current `browser` + `browser_script` split:

- `browser`: connect/status/recovery/profile/runtime ownership only.
- `browser_script`: all page work, CDP, screenshots, extraction, uploads, downloads, HTTP, artifacts.

Preferred improvements are general helper improvements inside `browser_script`, not new top-level tools. A new top-level helper tool is only justified if it is broadly useful, low-level, and hard to express cleanly through Python/CDP.

Likely `browser_script` improvements to investigate:

- Better default compact output for `page_info`, screenshots, tables, visible forms, and network events.
- A general visible-page snapshot helper that returns a compact accessibility/DOM/text summary plus screenshot, without dumping the full page.
- A general network/XHR capture helper that helps discover data endpoints after navigation.
- Better long-run script progress: emitted summaries should be concise and useful enough for the next turn.
- Better timeout diagnostics and checkpoint recovery.
- Stronger artifact/result audit helpers for list counts, required fields, JSON schemas, and inline final formatting.

### 2. Simplify The Prompt

The prompt should be short and general. It should teach the model the operating contract, not solve dataset categories.

Core instructions should fit roughly into:

- Use `browser_script` for page work.
- Start from the live website and verify.
- Screenshots are for state and verification, not decoration.
- Use CDP/JS/HTTP as appropriate; after discovering stable endpoints, switch to bulk HTTP.
- Avoid huge outputs; use structured `emit_output` summaries and files.
- For forms, use real browser input, not fake DOM mutation.
- If the task asks for N items, verify the count before finishing.
- If impossible, prove why from the live site and state that explicitly.

Remove or rewrite dataset-looking directives such as fixed `N>=5` rules or specific ThreadPoolExecutor mandates. The model can still be told generally that bulk extraction should happen in one bounded script when the page/data shape allows it.

### 3. Optimize Message History And Tool Responses

The biggest cheapness lever is what the next model turn sees.

Work items:

- Inspect actual `model.response.input_item` events for successful and failed tasks from SQLite and Laminar.
- Measure token cost by turn: system prompt, tool descriptions, screenshots, tool output text, summaries, prior history.
- Prefer compact summaries in transcript, with full data saved as artifacts.
- Keep image evidence only when it changes state or verifies an action.
- Ensure `browser_script` large JSON/text spills to artifact while preserving a compact count/schema/sample in context.
- Make final extraction data visible enough for judging without flooding every intermediate turn.
- Tune compaction so it preserves browser state, discovered endpoints, checkpoints, output files, and remaining task requirements.

### 4. Fix Sub-Agent Semantics Without Depending On Them

Sub-agents should be a useful optional capability, not the primary route to success.

The immediate reliability work is:

- Fix V2 lifecycle so `spawn_agent -> done -> wait_agent` returns useful child results.
- Ensure child context is compact and does not inherit massive browser transcripts by default.
- Give child agents isolated browser sessions only when parallel browsing is genuinely needed.
- Use child agents during our development and local judging, but do not require the benchmark agent to fan out unless the model naturally chooses to.

For benchmark tasks, first make a single smart agent efficient enough. Then add sub-agent support as a general acceleration path for independent research/extraction, not a task-specific mandate.

### 5. Build A Local Hard-Task Loop

Before launching evals, create a local loop that runs one selected eval task against:

- local Rust binary from the terminal worktree,
- Browser Use Cloud browser CDP URL,
- Browser Use rust wrapper in `/Users/magnus/Developer/browser-use`,
- local SQLite state/artifacts,
- self-judgment by Codex from logs, screenshots, result, and task requirements.

The existing `examples/rust/eval_one_task.py` fetches tasks and runs the Rust wrapper, but does not yet create/pass a cloud browser. Add a small local harness or extend it so it:

- creates a Browser Use Cloud browser,
- passes `BrowserSession(cdp_url=...)` into `browser_use.rust.Agent`,
- sets `BROWSER_USE_TERMINAL_BINARY` to the locally rebuilt Rust binary,
- runs one task,
- prints session id, artifacts, token use, final result, and SQLite query hints,
- stops the cloud browser in `finally`.

This local loop is the main iteration path. CI fanout is only for signal after local tasks work.

### 6. Pick Hard Tasks And Make Them Work One By One

Start with hard failures that expose general weaknesses:

- Multi-item extraction where the agent currently burns one browser turn per item.
- Cascading research where discovered links must be checkpointed and resumed.
- SPA grids and modals where load state and row data are not obvious.
- Autocomplete/forms where framework state must match visible state.
- Infinite-scroll/load-more pages where the scroll container and result count matter.
- Impossible/not-applicable tasks where the agent must prove impossibility.

For each task:

1. Run locally with the cloud browser and current Rust binary.
2. Read the exact input messages, tool calls, tool outputs, screenshots, artifacts, and SQLite events.
3. Decide manually whether the final answer is correct.
4. Identify the general failure: missing visual state, bad tool output shape, too many turns, lost checkpoint, wrong interaction primitive, weak final audit, context overflow, or broken runtime.
5. Fix the general mechanism.
6. Re-run that task until it works cleanly.
7. Re-run a small set of already-working tasks to catch regressions in cheapness and behavior.

Do not optimize for the automated judge until the task is actually correct by human review.

### 7. Eval Cadence

Use evals as batched validation, not as the primary debugger.

Sequence:

1. Local single-task runs on hard cases.
2. Local 3-5 task smoke set: one easy, one multi-item, one JS-heavy, one impossible/ambiguous if available.
3. CI 10-task fanout only after local smoke looks good.
4. Inspect all failures manually from Convex, Laminar, GitHub logs, SQLite/local analogs.
5. CI 50-task only after 10-task pass rate and trace quality improve.
6. CI 100-task only after the 50-task run is above the old best and failure modes are understood.

The target is not just pass rate. Track:

- successful tasks,
- manually correct tasks,
- average steps,
- average input/output tokens,
- browser_script calls per task,
- screenshots per task,
- context compaction events,
- timeout/error count,
- cost per successful task.

## First Implementation Goal

I would work on this exact goal:

> Create a local Browser Use Cloud + Rust-agent hard-task loop, then use it to reduce failed-task token waste by improving `browser_script` response/context quality and simplifying the eval prompt, without adding a task compiler or dataset-specific routing.

Definition of done for the first phase:

- A repeatable local command can run `real_v8` task `i` through the local Rust binary and Browser Use Cloud browser.
- The command records enough artifacts and SQLite/session ids to inspect every turn.
- The eval-mode prompt no longer contains task-compiler-like rules.
- Tool responses expose compact summaries and preserve full data as artifacts.
- At least two previously hard tasks are locally correct by manual review with fewer turns than the current baseline attempt.

## Open Questions / Access Needs

- Exact Unikraft parity requires `UKC_TOKEN`; otherwise local testing will use Browser Use Cloud CDP, which is good enough for most agent-loop work but not identical to CI.
- The Browser Use working tree is dirty. I will preserve all existing changes and treat them as user/previous-agent work unless told otherwise.
- I do not need Gemini for local judging if Codex/manual judgment is the source of truth. If later we need judge parity, a Gemini key is needed.
- I need confirmation only if you want the plan file somewhere else; otherwise this file is the working plan in the Browser Use fork.

## Progress Log

### Local Cloud Harness

Implemented `examples/rust/eval_one_task_cloud.py` in the Browser Use fork. It creates a Browser Use Cloud browser, passes the CDP URL into the Rust wrapper, runs one `real_v8` task through the local Rust binary, prints session/token/Laminar/SQLite handles, and stops the cloud browser in `finally`.

### General Runtime Fixes From `real_v8` Task 5

The Sziget ticket task exposed general runtime bugs rather than a site-specific problem:

- `browser_script` observes used to report only `No new output`, so the parent model could not tell whether Python was in navigation, JS polling, screenshots, or a dead bridge call.
- WSS Browser Use Cloud CDP traffic was delayed by the dispatcher reader blocking before draining queued commands.
- Continuous session capture competed with actual task actions for CDP capacity.
- The first browser action created and attached a new blank tab even though the remote browser already had a reusable blank target.

General fixes made in the terminal Rust core:

- `browser_script` now streams compact progress heartbeats for user-code, bridge/meta, and CDP operation start/end/error.
- Observe outputs now include elapsed time, remaining script timeout, and latest operation progress.
- The CDP dispatcher now uses a short read timeout for Rustls/WSS sockets so queued commands are sent promptly.
- Background session capture is opt-in via `LLM_BROWSER_CAPTURE_FPS`; explicit `screenshot()` remains the default evidence path.
- Capture, JS load probes, and explicit screenshot helpers now have bounded CDP timeouts.
- `new_tab(url)` reuses the initial blank target once, avoiding slow create/activate/attach churn on first navigation.
- HTTP 404s from `http_get` return response objects instead of aborting whole batch scripts.
- The Browser Use rust wrapper can recover the session id from SQLite if the CLI output does not expose it before timeout.

Observed impact on local Sziget runs:

- Before the dispatcher/socket fix: 6 agent steps, 0 screenshots, repeated empty observe polling, no useful page state.
- After the dispatcher/socket and tab-reuse fixes: navigation and screenshots work; the agent reached 22 steps and 10 screenshots in 90s.

### Compact Snapshot / Browser-Only Loop

The local Sziget task loop exposed the next general bottleneck: browser control is good enough, but the model spends too many turns rediscovering where structured data lives.

Changes made:

- Added `page_snapshot(...)` / `emit_page_snapshot(...)` to the Rust `browser_script` helper surface.
- `page_snapshot` now traverses open shadow roots.
- `page_snapshot(visible_only=False, ...)` includes offscreen and collapsed DOM text for extraction tasks.
- `page_snapshot` returns a `SnapshotDict`, so accidental `snapshot[:N]` slicing becomes a JSON string slice instead of a Python `KeyError`.
- `page_snapshot` now includes high-signal `signals.headings` and `signals.prices` data for quick extraction orientation.
- Snapshot payload order now puts `signals` immediately after page metadata so truncated tool output shows the useful data first.
- Duplicate observes on a completed `browser_script` run now return a compact cached "already finished" status instead of a tool error.
- Browser Use wrapper runs now disable shell/unified-exec tools by default (`BU_RUST_ENABLE_SHELL_TOOL=1` opts back in), keeping browser tasks inside `browser` + `browser_script`.
- Local Cloud harness now retries Browser Use Cloud create/stop calls and does not fail the whole run when cleanup times out.

Observed local Sziget runs:

- Session `70583e3fc5cb`: 23 steps, 3 screenshots, 42.4k input tokens. `page_snapshot()` found ticket/shadow content, but the agent still fell back to shell parsing. This led to disabling shell tools in the Browser Use wrapper.
- Session `c824f6dec630`: shell disabled, 25 steps, 57.3k input tokens. The agent found full shadow text and extracted 171 ticket-like rows near the end, but hit the timeout before `done`.
- Session `d1187f615279`: after slice/collapsed-DOM fixes, 31 steps, 42.8k input tokens. The agent extracted 171 tickets on the last step but still did not finish.
- Session `1c2b26b4e0ed`: after signal extraction, 25 steps, 53.2k input tokens. The high-signal data was present but buried behind large visible text; payload order was changed afterward so future truncated snapshots expose signals first.

Current conclusion:

- The task is now mechanically solvable by the local Rust browser path.
- The remaining issue is not CDP reliability; it is message-history/tool-output economics and finalization behavior.
- Next architectural work should make compact extraction signals first-class in transcript summaries, reduce early screenshot/default DOM probing, and preserve enough structured extracted data for the model to call `done` immediately after a valid result instead of continuing exploratory loops.
- This is progress but still not correct: the model is now spending too many turns inspecting screenshots and scrolling instead of extracting structured page data in one script.

Next general architecture target:

- Add a compact repeated-item extraction helper inside `browser_script` for product/list/card/table-like pages. It should infer repeated DOM blocks, field names, visible text, price/date/status signals, parent headings/categories, and sample records without site-specific selectors.
- Make the helper cheap and general, not Sziget-specific.
- Use it to push the model away from repeated screenshot-only exploration and bespoke selector probing, toward one-script extraction with `emit_output` summaries and artifacts.

### Transcript And Cost Fixes From `real_v8` Task 5

The next Sziget runs showed that even when the browser path can reach the data, the transcript shape still made the agent inefficient:

- Raw `emit_output(...)` data was compacted only when the script used the structured channel; many agent-written scripts printed large JSON/text directly.
- Screenshot image parts accumulated in message history, so every later model turn resent old screenshots.
- The Browser Use Python wrapper launched the Rust agent from `/Users/magnus/Developer/browser-use`, causing the browser task to inherit repo workspace context and `AGENTS.md` even though this is not a coding task.
- Common browser scripts finished shortly after the initial async cutoff, causing unnecessary `start -> observe` model turns.

General fixes made:

- `browser_script` model-visible output now orders `summary` first and replaces raw `outputs`/`data` with `outputs_compact` / `data_compact`: labels, item counts, fields, non-empty field counts, and sample rows. Full raw output remains in SQLite `tool.output` and artifacts.
- Long raw stdout is compacted before reaching the model. JSON arrays and repeated JSON record blocks get parsed into count/schema/sample summaries instead of raw dumps.
- Browser-script image history now keeps only the latest screenshot-bearing `browser_script` tool output as image data; older browser screenshots become text placeholders. Other tool images are not affected.
- `browser_script` initial wait increased from 750ms to 6000ms so short navigation/screenshot/action scripts complete in one tool turn more often.
- The Browser Use wrapper now launches the Rust browser-agent subprocess from a clean state-dir runtime cwd (`~/.browser-use-terminal/browser-agent-cwd` by default, override with `BU_RUST_RUNTIME_CWD`) so repo developer context does not pollute browser eval tasks.

Observed local Sziget evidence:

- Session `a13c1733fa06`: after structured-output compaction only, 24 steps, 49.7k input tokens, 7.2k output tokens. The critical extraction still printed raw text, so `outputs_compact` was not exercised.
- Session `13b93383c844`: after long stdout JSON compaction, 27 steps, 45.0k input tokens, 8.7k output tokens. The agent saved a useful `sziget_tickets.json` artifact with 113 records but timed out before final `done`.
- Session `9f0da186ae28`: after increasing initial wait, 30 steps, 48.0k input tokens. Async overhead dropped, but the agent spent the saved turns on repeated DOM exploration.
- Session `5b7c3ff333a4`: after clean runtime cwd, first-turn `estimated_context_chars` dropped from about 38k to 4.3k, proving repo context isolation worked. The run overused screenshots and still timed out.
- Session `84250a265cab`: after image-history pruning, 23 steps, 39.4k input tokens, 7.2k output tokens. `model.turn.request.input_image_count` stayed at 1 after screenshots began, proving old browser screenshots were no longer resent. The task still timed out because the model kept writing bespoke exploratory DOM scripts instead of using a general extraction primitive.

Current conclusion:

- Cost mechanics are improving: clean cwd and image pruning materially reduce context growth.
- The local Sziget task is still not solved within 30 steps / 180s.
- The remaining blocker is now architectural at the browser helper level: the agent needs a very general way to inspect repeated visible/DOM-backed items and parent categories in one compact call, instead of hand-rolling selector guesses for every page.

### Repeated Item Extraction Work From `real_v8` Task 5

The Sziget task isolated a general failure mode that should affect many `real_v8` tasks: repeated products/cards/rows inside open shadow DOM.

Changes made in the Rust terminal core:

- Added `repeated_items_snapshot(...)` / `emit_repeated_items_snapshot(...)` as a general browser_script helper for repeated cards, products, rows, tickets, tables, and search results.
- The helper traverses open shadow roots, ranks repeated groups, returns record samples, parent heading context, price/date/status signals, field coverage, and a `recommended_group`.
- It now skips nested child fragments when a full semantic record exists, so child nodes like `div.product__header` do not outrank whole `article.product` records.
- It now merges state-class variants by canonical class token, so `article.product.product--has-img`, `article.product.product--has-info`, and sold-out variants do not split the same repeated record universe.
- It now returns `root_path` / `query_context`, so selectors under open shadow roots are not presented as if they work from `document`.
- Added `extract_repeated_items(...)`, a general full extraction helper that can infer or accept `selector`/`root_path`, extract all records, write a JSON file under `outputs_dir()`, and return count/field coverage plus a next-step hint.
- `page_snapshot(visible_only=False)` now automatically attaches repeated-item hints when it finds a strong repeated group. This is important because the model naturally calls `page_snapshot` first; the extraction hint must appear on that common path.
- `SnapshotDict` string slicing/string methods now prioritize `next_extract_hint`, `repeated_items`, output file, and count metadata first. This fixes the model habit of doing `snapshot[:5000]` or `snapshot.find(...)`, which previously hid the useful extraction hint or raised an error.
- Browser-script compaction now treats `repeated_items`, `next_extract_hint`, `next_step_hint`, `recommended_group`, `field_coverage`, `output_file`, `selector`, and record counts as explicit high-value keys.

Observed local Sziget evidence:

- Session `bd3eda036bed`: after the first `repeated_items_snapshot` version, the model called the helper but ignored it. The helper ranked `div.product__header` above whole product articles, split product variants into separate groups, and did not give a shadow-root replay selector.
- Session `7232f57edcd3`: after adding `extract_repeated_items`, the model did not call the repeated-item path at all. It spent 35 steps / 240s / 70.0k input tokens on screenshots and hand-written selectors. This showed that the helper must be surfaced through the normal `page_snapshot` path.
- Session `8c2892485cb1`: after adding snapshot extraction hints, the model eventually called `extract_repeated_items(...)` with `selector='article.product'` and `root_path='document.querySelector("#webshop-app-shadow").shadowRoot'`. It extracted 113 records and then wrote a structured `tickets_structured.json` with 93 entries, but still timed out at 22-step cap / 180s. Cost dropped to 40.2k input tokens, but the agent still used too many pre-extraction turns and then over-transformed the already useful extracted file.

Current conclusion:

- The general extraction primitive works: it can get the full repeated record set from an open shadow root in one browser_script call.
- The remaining Sziget blocker is decision timing and finalization. The agent reaches the right primitive too late, then keeps transforming/inspecting instead of verifying the extraction and finishing.
- The next high-leverage architecture work is to make snapshot hints visible even through accidental string slicing, make extracted files more obviously `done`-ready, and reduce the prompt/tool surface that encourages screenshot-first manual exploration.

### Finalizable Repeated Extraction Artifact From `real_v8` Task 5

The next iteration focused on making the extraction result directly usable as a final answer artifact instead of a transcript payload that invites more model-side processing.

Changes made:

- Simplified the browser-agent system prompt and browser_script tool description. The prompt files are now about 6.2k chars combined; the actual Anthropic instruction payload is still about 22.1k chars because provider code appends Browser Harness interaction skills.
- Added a socket-layer timeout for CDP bridge reads when a browser_script payload has `timeout_ms`, so stuck `Runtime.evaluate` calls raise a Python `TimeoutError` instead of hanging until the outer script/run timeout.
- `extract_repeated_items(...)` now returns compact metadata by default and omits full records from the model-visible return when `output_file` is set.
- The helper now emits `final_candidate` metadata: `ready_for_done`, record counts, field coverage, result file, metadata file, and result file format.
- The primary `output_file` is now a JSON array of extracted records, suitable for `done(result_file=...)`.
- Full extraction metadata, including page/root/selector/coverage/full records, is written to a sidecar `metadata_file`.
- `records_preview` is limited to a few compact records in the transcript. Full rows stay in the artifact and SQLite.

Observed local Sziget evidence:

- Session `caff12c52a85`: after prompt simplification, the model followed `next_extract_hint` at step 6 and extracted 113 records with `done_ready=true`, but it kept transforming/inspecting and timed out at 18 steps / 180s. This proved the prompt cleanup helped timing but not finalization.
- Session `6b0c63d26c49`: after extracted-summary improvements, navigation recovered and extraction happened at the final step, but the run still timed out. Cost was 30.6k input / 2.7k output tokens.
- Session `80a199df461a`: after the socket timeout, extraction succeeded at step 13 and wrote 113 records with `done_ready=true`, but the model again opened the artifact and transformed categories until timeout. Cost was 27.5k input / 4.95k output tokens.
- Session `f2d2e5386c4b`: after compact `final_candidate`, extraction succeeded with `ready_for_done=true`, but the model assumed the artifact was a list, hit a type mismatch because it was still a metadata object, repaired its transform, and timed out at 150s.
- Session `fd5f0acb73d2`: after changing `output_file` to a JSON record array and moving metadata to `tickets_raw.metadata.json`, the local Browser Use Cloud run completed successfully in 13 steps / 127.8s. It produced a final answer and artifacts `sziget_tickets.json` / `sziget_tickets.csv`. Cost was still high at 29.2k input / 8.37k output tokens, because the model chose to transform and print/review large structured output before `done`.

Current conclusion:

- The repeated-item architecture is now end-to-end viable on this hard Sziget task locally with a real Browser Use Cloud browser.
- The biggest remaining cost issue is post-extraction over-processing. Even with `ready_for_done=true`, the model may still transform, print, audit, and summarize a large result.
- The next general architecture target is a stronger finalization path after high-confidence extracted artifacts: either transcript pruning after `final_candidate.ready_for_done`, stricter model-visible guidance that `output_file` already satisfies common scraping tasks, or a browser_script helper that writes a clean normalized record array without requiring model-written transformation code.
- This should stay general. The goal is not Sziget-specific parsing; the target is reliable, cheap handling of repeated products/cards/results/tables across tasks.

### Browser-Only Runtime And Document Extraction From `real_v8` Task 6

The FERC eLibrary task exposed two general architecture issues.

First, the Browser Use wrapper had disabled shell tools but the Rust browser-agent registry still exposed workspace/code tools such as `apply_patch`, `update_plan`, goal tools, request-user-input, and capture curation. In local session `5e047721f138`, the model tried to create a local `extract_pdf.py` with `apply_patch` during a browser eval. This is the wrong action space.

General fix:

- Added `features.workspace_tools=false` support in the Rust tool registry.
- When disabled, the registry hides `apply_patch`, `view_image`, goal tools, `update_plan`, `request_user_input`, and `submit_capture_curation`.
- The Browser Use rust wrapper now sets `features.workspace_tools=false`, `features.plugins=false`, and `features.image_generation=false` by default for browser tasks, alongside shell/unified-exec disablement.
- Local smoke session `bbcac7fd29fa` confirmed the live model-visible tool count dropped from 11 to 3.

Second, FERC document links look like filename links, but the direct `filedownload?fileid=...` URL returns an Angular HTML shell under plain HTTP. The agent eventually discovered the real browser-context flow (`POST /eLibraryWebAPI/api/File/DownloadP8File`) and extracted PDF text, but took 52 tool steps, hit the 360s timeout, and consumed 116k input tokens.

General fixes started:

- Added `download_file(...)`, `extract_pdf_text(...)`, and `download_pdf_text(...)` helpers to `browser_script`.
- PDF helpers save binary/text artifacts and return compact metadata.
- `extract_pdf_text(...)` now writes full PDF text to an output file by default and returns only a short preview.

Current FERC evidence:

- Session `a9bae8d7f85d` timed out, but produced useful artifacts:
  - `row1_variance_approval.pdf`
  - `row2_transmittal_letter.pdf`
  - `row2_attachment_supplement.pdf`
  - extracted text files for row 1 / row 2 documents
- The task was not correct yet because it did not finalize the required markdown and likely did not process every first-two-row file cleanly.
- Main next architectural target: a browser-context document-download helper that captures a click-triggered download/XHR/blob response, saves the binary, extracts text, and returns one compact per-document record. The agent should not reverse-engineer Angular bundles or print full PDF pages turn by turn.

Verification for this slice:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo test -p browser-use-core browser_script_ -- --nocapture`
- `cargo test -p browser-use-core workspace_tools_feature_gates_code_and_planning_tools_for_browser_tasks -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

### Browser Harness-Style Network Events And Download Capture

The next FERC iterations showed why the first document helpers were still incomplete:

- Session `ea1e4a3f01da`: the non-PDF diagnostic worked. After `download_pdf_text(...)` returned `ok=false` with a clear app-shell diagnosis, the model switched to `capture_document_action(...)`. This is the right behavioral direction.
- The first `capture_document_action(...)` version captured Datadog RUM telemetry because it accepted the first matching XHR/body response. This is common SPA noise, not FERC-specific.
- The helper was changed to ignore telemetry-like URLs and wait for document-like responses by content type, content disposition, extension, and size.
- Session `a4da3db91307`: after telemetry filtering, the helper no longer captured RUM, but direct file links still produced no document body because terminal's Rust CDP bridge had no Browser Harness-style event buffer. `drain_events()` returned empty.

General fixes made:

- Added a bounded CDP event buffer to the Rust `CdpDispatcher`.
- `drain_events()` now returns id-less CDP events from the shared websocket instead of an empty list.
- First-page attach, reattach, and `set_session` now enable `Network` events in addition to `Runtime` and `Page`.
- `capture_document_action(...)` now falls back from page JS fetch/XHR hooks to CDP `Network.responseReceived` plus `Network.getResponseBody` when possible.
- Added Browser Harness-style download helpers:
  - `allow_downloads(...)`
  - `wait_for_download(...)`
  - `capture_file_download_action(...)`

Current evidence after these fixes:

- Focused tests and rebuild pass.
- Session `68994fc2674e` shows the model using the improved path:
  - `download_pdf_text(...)` returned structured `ok=false` instead of a traceback.
  - The model then tried `capture_document_action(...)`.
  - The model then tried `capture_file_download_action(...)`.
- The task still does not pass locally. The direct visible `filedownload?fileid=...` link is an app route that returns an HTML shell, not the real file. The real documents are behind the row's file-list/application flow.

Next architectural target:

- Add a general row-scoped grid/list extraction helper that returns each row with its row text, description-like fields, and all same-row links/buttons/actions. The agent should be able to ask for "first two result rows and their file actions" without hand-rolling selectors or treating every file link as globally equivalent.
- This should generalize to FERC docket grids, Epiq docket tables, FCC search results, marketplace result lists, and any SPA grid where links/actions must be associated with the correct row.
- Do not add FERC-specific URL rules. The helper should solve the structural problem: row association, action extraction, and compact row-scoped evidence.

### Row-Scoped Grid Extraction And Helper Ergonomics

The next local FERC runs confirmed that row association is the right abstraction, but the model still needs the tool surface to make the cheap path easier than bespoke probing.

General fixes made:

- Added `rows_snapshot(...)` / `extract_rows(...)` and aliases `grid_rows_snapshot(...)` / `extract_grid_rows(...)`.
- The helper extracts table/grid/list rows with row-scoped cells, description-like fields, actions, file actions, coordinates, source selector, and root path.
- `page_snapshot(...)` now attaches `grid_rows`, `next_row_hint`, and `recommended_action` when it sees row-scoped actions.
- Row hints now take priority over repeated-item hints in `SnapshotDict` and transcript compaction.
- When rows and generic repeated items are both detected, `page_snapshot(...)` now makes `extract_grid_rows(...)` the primary `next_extract_hint` instead of letting a broad repeated selector win.
- Added general row selectors such as `[data-rowindex]`, `[aria-rowindex]`, `[class*='row']`, and `[class*='record']`.
- `capture_document_action(...)` now accepts `output_file=` as an alias for `text_output_file=`, because the model naturally tried that spelling.
- `allow_downloads(...)` now returns a path-compatible dict-like object, so model code can use either `info["download_dir"]` or pass the return value to path functions.
- `capture_file_download_action(...)` now accepts `download_dir=...`.

Current FERC evidence:

- Session `576d396e9bdc`: the row hint surfaced, but the model ignored it and followed global file links. It eventually discovered `DownloadP8File`, but only after 34 steps / 260s / 65.4k input tokens and timed out.
- Session `33d6ed447a59`: after row hint prioritization, the model got row-scoped cells and same-row links for Row 1 and Row 2 by step 15. It still did not call the helper directly, and later wasted time on brittle helper argument names and JS-driven `href="#"` document links. It timed out at 44 tool steps / 300s / 76.8k input tokens.

Current conclusion:

- The local agent can now identify the first two FERC rows and their correct same-row file links much earlier.
- The remaining failure is document capture/finalization after row extraction, plus the model still writing too much custom DOM/debug code.
- The next local target is to make `extract_grid_rows(...)` the default visible artifact for row pages and add a compact "document action recipe" for row file actions, so the model can go from row file link to extracted PDF text without manually reverse-engineering events.
- This is still general architecture: row-scoped data extraction, forgiving helper contracts, and browser-context document capture for JS-driven file links.

### JS-Driven Document Capture Success On `real_v8` Task 6

The next FERC run validated the general document-capture direction.

General fixes made:

- Added `capture_document_url(...)`.
  - It first tries a direct binary HTTP fetch.
  - If the URL returns an HTML app shell, it opens the URL in the live browser and captures the JS/fetch document response from the visible file action.
- Added explicit `capture_js_document_action(...)` as a clearer alias for `capture_document_action(...)`.
- Improved text-click targeting in document/download helpers to prefer visible actionable elements (`a`, `button`, roles, tabindex) over parent `div`/`span` containers.
- Updated `download_pdf_text(...)` diagnostics so HTML app-shell responses point to `capture_document_url(...)` / JS document capture, not browser-download polling.
- Factored document bytes saving/text extraction into one shared path so direct HTTP, JS capture, and CDP fallback return the same compact shape.
- `extract_pdf_text(...)` now returns `text_tail_preview` for truncated documents, so many document summaries can be completed from head+tail previews without reopening the full artifact.

Observed local FERC evidence:

- Session `9cc189a27091` completed successfully locally against Browser Use Cloud:
  - 19 steps
  - 125.8s
  - 32.1k input tokens / 4.4k output tokens
  - cost `$0.1620`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=7ac47488-5b98-dab6-bb52-1a133a6e93e4`
- The run still initially used bespoke table JS instead of `extract_grid_rows(...)`, but it kept row scope and got the first two row file links correctly.
- At step 11, direct `download_pdf_text(...)` returned HTML and gave the new app-shell diagnostic.
- At steps 12-14, `capture_document_action(...)` captured all three required PDFs through the live browser JS/fetch path and extracted text artifacts.
- The final answer included all three required row/file sections with descriptions, direct file URLs, and summaries.

Current conclusion:

- The generic JS-document-capture architecture works on the previously failing FERC task.
- The remaining cost issue is not document access; it is pre-extraction screenshot/coordinate exploration and post-extraction over-reading.
- The next target is to make the agent choose compact structural helpers earlier:
  - form/page snapshot before coordinate guessing,
  - `extract_grid_rows(...)` instead of custom table scripts,
  - head+tail PDF previews instead of full artifact reads,
  - finalization as soon as all required documents/records are present.

### App-Driven Search/API Capture For Large Enumeration Tasks

BSTN `real_v8` task 12 exposed the next general bottleneck: large paginated extraction where the DOM only renders a small visible subset but the app has a stable JSON search API.

Observed local evidence:

- Session `ac37770eaa8e` timed out after finding the product grid and Typesense endpoint too late.
- Session `0e1060b2e29a` extracted the correct data but still timed out before `done()`:
  - 7,493 products collected
  - all required fields present: name, price, url, image
  - output artifact: `/Users/magnus/.browser-use-terminal/browser-agent-cwd/bstn_men_products.json`
  - 52 steps / 360s / 62.4k input tokens / 17.3k output tokens / `$0.4471`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=03764465-d53d-a6b4-593c-93f1a5edd42d`
- The model made two general mistakes:
  - It reconstructed the API payload manually instead of replaying the exact browser request.
  - It changed important query parameters (`query_by`, filter casing/shape), briefly dropping the result count from 7,493 to 56.

General fixes made:

- Added `http_get(..., method=..., data=..., json_body=...)` and `http_json(...)` so browser-discovered POST/JSON APIs can be queried directly from `browser_script`.
- Added `capture_api_action(...)`.
  - It enables CDP `Network`, runs one click/navigation/action, pairs `requestWillBeSent` with `responseReceived`, fetches response bodies with `Network.getResponseBody`, saves response artifacts, and returns a compact exact `replay` object.
  - It redacts cookie/authorization headers while preserving query URL, method, content type, body, and casing.
  - It is intentionally general for app-driven search, filters, infinite scroll, pagination, and detail panes.
- Added `app_state_snapshot(...)`, and `page_snapshot(visible_only=False)` now surfaces compact hydrated app-state candidates when present.
  - It scans common SPA hydration globals such as `__NEXT_DATA__`, Nuxt, Apollo, React Query, Remix, and initial-state containers.
  - It returns candidate paths, record counts, item fields, sample records, and pagination-like metadata.
  - This makes lazy/virtualized result pages reveal bulk data paths before the model spends many turns on visible DOM cards.
- Updated the browser-script tool description and simple system prompt to prefer `capture_api_action(...)` before hand-reconstructing app-driven pagination/search requests.

Verification for this slice:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_capture_api_action_returns_exact_replay_and_artifact -- --nocapture`
- `cargo test -p browser-use-browser browser_script_page_snapshot_surfaces_hydrated_app_state -- --nocapture`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo test -p browser-use-core browser_script_ -- --nocapture`
- `cargo test -p browser-use-core browser_script_tool_description_preserves_raw_cdp_contract -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Current conclusion:

- The rebuilt prompt/helper path now solves the BSTN task locally against Browser Use Cloud without screenshots or manual per-item browsing.
- Successful local evidence:
  - Session `b5bb8dc84f6f`
  - Browser Use Cloud browser `82fcba00-0fa7-479d-9a15-348f0b7277e9`, stopped cleanly after the run
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=50a55d0b-b499-ceae-b99f-fd09fe630877`
  - 23 tool/observe steps, 144.1s
  - 19.1k input tokens / 3.6k output tokens / `$0.1119`
  - Extracted 7,490 products across 79 pages
  - Final artifact: `/Users/magnus/.browser-use-terminal/browser-agent-cwd/bstn_men_products_final.json`
  - Manual judgment: correct. Every record has `name`, `price`, `url`, and `image_url`; URLs were normalized to full `https://www.bstn.com/us_en/...` links.
- General fixes added after the initial stuck attempt:
  - `page_info()` now exposes a tiny `app_state` lead on the first observation.
  - `extract_app_state_records(...)` extracts SSR/SPA hydrated arrays across pagination and writes a file artifact.
  - The extractor avoids the blocking `current_tab()` metadata probe when JavaScript can provide `location.href`.
  - `current_tab()` metadata now uses short CDP timeouts so a wedged page cannot consume the whole browser-script run.
  - The extractor emits page-count progress so long bulk work is visible to the model and to local debugging.
- Remaining cost problem:
  - The run is correct but still spends many model turns observing the long extraction progress and then doing verification/transformation.
  - Next local target: make long-running helpers return coarser progress or self-finish with a compact result so the model does not need repeated observe turns, and make output normalization (`url` base, alias mapping) a helper option so the model does not need extra scripts after extraction.

Follow-up cost fix:

- `extract_app_state_records(...)` now fetches sibling SSR/SPA pages with a bounded thread pool instead of sequential HTTP requests.
- Routine page-count updates now use structured progress events rather than stdout, so observe calls are not woken up by every progress line.
- The model-visible progress text still includes page and record counts when a run is observed, preserving debuggability without flooding the transcript.

Observed local BSTN evidence after the follow-up:

- Session `b2ff6ea4563b` after parallel fetch:
  - 10 steps / 51.0s
  - 12.1k input tokens / 2.1k output tokens / `$0.0672`
  - Extracted 7,492 current products across 79 pages
  - Final artifact: `/Users/magnus/.browser-use-terminal/browser-agent-cwd/bstn_men_products_clean.json`
  - Manual judgment: correct; all records had `name`, `price`, `url`, `image_url`.
- Session `12c8460aaede` after structured progress:
  - 7 steps / 53.9s
  - 14.3k input tokens / 1.8k output tokens / `$0.0704`
  - Only one observe turn during the long extraction helper.
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=8982c30f-0bcc-3510-b5fa-6fe6c9dcbb8e`
  - Final artifact: `/Users/magnus/.browser-use-terminal/browser-agent-cwd/bstn_men_products_clean.json`

Current conclusion:

- Bulk app-state extraction is now correct and much cheaper on this class: 52-step timeout -> 23-step success -> 10-step success -> 7-step success.
- Remaining general improvement for this class: add optional URL normalization / final schema shaping inside the helper so the agent does not need a post-extraction cleanup script.
- Next hard class should be different from catalog extraction, such as address autocomplete, dropdown/state iteration, SPA table sorting, or large load-more telecom package lists.

### Form And Autocomplete Failure From `real_v8` Task 40

DNA broadband address lookup exposed a different general failure class from Sziget/FERC/BSTN:

- Session `fbd832abd7c0`:
  - The model guessed `input[type="text"]` / broad selectors and filled the wrong visible field.
  - It accidentally navigated from `kauppa.dna.fi/laajakaista/valitse-netti` to a generic DNA broadband page.
  - It then used many screenshots and coordinate guesses to operate the postal-code/street/house-number flow.
  - I stopped the run after it had enough evidence; the browser was stopped cleanly.
- Session `5f6ab1f02990`:
  - Before the form issue, `page_info()` spent too long in the app-state hint path while the page was still `interactive`.
  - The app-state candidates were mostly navigation/header arrays, not task data.
  - The page reached an error state and the model continued screenshot/debug loops.
  - I stopped the run; the browser was stopped cleanly.
- Session `9399dd3e518a` after the first form/page-info fixes:
  - `page_info()` completed much faster than the previous stuck run.
  - The model used `click_suggestion(...)` once, but still relied heavily on coordinate clicks and screenshots.
  - It successfully reached the package results; visible page text contained 5 DNA packages:
    - DNA Netti Huoleton 150M lisänopeus, 14,99 €/kk/24 kk, 150 Mbit/s
    - DNA Netti Huoleton 300M lisänopeus, 16,99 €/kk/24 kk, 300 Mbit/s
    - DNA Netti Huoleton 600M lisänopeus, 19,99 €/kk/24 kk, 600 Mbit/s
    - DNA Netti Huoleton 1000M lisänopeus, 26,99 €/kk/24 kk, 1000 Mbit/s
    - DNA Netti 10M/10M perusnopeus, 0,00 €/kk, 10 Mbit/s
  - It timed out before final `done`.
  - Main reason: `page_snapshot(visible_only=False)` / `extract_grid_rows(...)` over-prioritized hidden zero-size navigation/menu rows, so the useful package content was buried and the agent fell back to custom DOM probing.

General fixes started:

- Added `form_fields_snapshot(...)` to expose visible fields with labels, placeholders, names, current values, active field, rects, and visible suggestions.
- Added `fill_form_field(label_or_placeholder, value)` so the model can target a field semantically instead of broad selectors like `input[type=text]`.
- Added `click_suggestion(text=None, index=0)` for autocomplete/listbox/menu suggestions.
- Added a small tool-description entry for these helpers.
- Changed `page_info()` so app-state hints only run when `document.readyState == "complete"`. This keeps first inspection cheap on still-hydrating pages and avoids surfacing irrelevant navigation state as a bulk-data lead.
- Changed `rows_snapshot(...)` and `repeated_items_snapshot(...)` so `visible_only=False` still requires a real element box. This prevents hidden zero-size navigation/menu items from outranking visible product/package cards while still allowing offscreen but rendered records.

Verification for this slice:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_form_field_helpers_match_labels_and_suggestions -- --nocapture`
- `cargo test -p browser-use-browser browser_script_page_info_surfaces_tiny_app_state_hint -- --nocapture`
- `cargo test -p browser-use-browser browser_script_repeated_items_snapshot_returns_compact_groups -- --nocapture`
- `cargo test -p browser-use-browser browser_script_page_snapshot_returns_compact_visible_state -- --nocapture`

Current conclusion:

- The helper surface now exists and the task is mechanically reachable, but DNA is not yet locally solved.
- The next general move is not more prompt text. It is to make `page_snapshot()` surface form summaries and visible repeated price/package cards ahead of global navigation/app-state noise, then rerun DNA.

Follow-up local DNA evidence:

- Session `6ba3433b8312` after the first hidden-row fix:
  - 31 steps / 220.3s timeout
  - 69.5k input tokens / 4.8k output tokens / `$0.2809`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=cda5d05e-d503-eb9d-65cb-670fb7e6c882`
  - It reached the correct package result page and extracted the page text containing all 5 packages, but kept opening `Sopimusehdot` sections and never finalized.
  - `extract_repeated_items(context=...)` failed because the helper rejected the harmless `context` argument.
  - `extract_repeated_items(...)` then selected hidden/global `li` navigation records; `packages.json` contained 165 nav/menu rows and `final_candidate.ready_for_done=false`.
- Session `69584e9984e3` after accepting `context`, requiring boxes for hidden extraction, adding package/plan candidates, and recognizing number-then-currency prices:
  - 27 steps / 220.4s timeout
  - 55.8k input tokens / 4.0k output tokens / `$0.2269`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=afcc64a7-3dd8-6c53-2540-cd0920ef782c`
  - Cost improved, but the model regressed earlier into screenshot/coordinate form handling and navigated into the wrong 5G section instead of extracting the already-visible package cards.
- Session `dc1ee0285913` after adding tiny `form_fields` / `next_form_hint` to `page_info()`:
  - 26 steps / 220.4s timeout
  - 52.4k input tokens / 3.6k output tokens / `$0.2116`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=f7c4025d-3825-9b23-4e1f-9bc64284fcdb`
  - Cost improved again, but the model skipped `page_info()` on the first interaction and still operated from screenshots and coordinates.
- Session `fe7787f743d0` after adding structured `screenshot_state` summaries:
  - 27 steps / 220.1s timeout
  - 80.8k input tokens / 4.3k output tokens / `$0.3069`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=c528366d-7bfd-0409-9f72-217fb484944a`
  - This was a cost regression. The first version emitted verbose nav controls and fake suggestions for ordinary links when no form field was active.

General fixes made from these runs:

- `page_snapshot(visible_only=False)` now also requires a real element box instead of accepting zero-rect hidden DOM.
- `extract_repeated_items(...)` now accepts a harmless `context=` hint, avoiding a wasted failure turn when the model supplies one.
- Currency detection now handles European price text like `14,99 €/kk`, so package/product cards get real price signal scores.
- Repeated-item candidate discovery now includes general `package` and `plan` class tokens.
- Row extraction now downranks nav-like non-table list rows with many links and no price/file/table signal.
- `page_info()` now includes a tiny visible form summary when fields are present.
- `screenshot_state` was kept conceptually but tightened after the cost regression:
  - autocomplete suggestions are only collected around an active input/select/textarea,
  - screenshot summaries skip nav-only pages with no fields, no actionable controls, and no price signals,
  - controls are limited to form controls/buttons instead of global links/navigation.

Updated conclusion:

- The remaining DNA blocker is not browser connectivity or basic CDP interaction.
- It is first-action economics and state choice: the model can still spend the whole task in screenshots/coordinates before it reaches compact structural extraction.
- The next local iteration should make the common screenshot-first path cheap enough and should add a direct, general `extract_visible_offers`-style specialization only if it is really a generic layer over repeated priced cards, not a site/task rule.
- Before another full DNA run, verify that the tightened screenshot summary no longer emits nav-only 5k summaries on pages without visible fields/prices.

Latest local DNA slice:

- Session `3f95f85aa279` after SPA readiness summaries and stricter hidden extraction:
  - 30 steps / 240.4s timeout
  - 91.5k input tokens / 3.9k output tokens / `$0.3333`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=ffd5350d-004c-bbed-82ee-c0f3ab1ab408`
  - The model naturally called `fill_and_select_suggestion("input#address-search-street", "Inkoonkatu", "Inkoonkatu")`, but the helper made `suggestion_text` keyword-only, causing a wasted TypeError and fallback to manual coordinate work.
  - It eventually reached visible packages and price signals, but kept screenshotting/clicking instead of moving directly to extraction.
- Session `f53d5cf2b6e3` after accepting the natural positional helper call:
  - 29 steps / 240.4s timeout
  - 108.8k input tokens / 4.6k output tokens / `$0.3959`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=d8acf582-72cd-d29a-a734-22e72a07a6cd`
  - The street helper worked, but the model had no reliable named-control helper for the submit button. It repeatedly clicked coordinates and then used a broad `document.querySelector("button...")`, which clicked the header search form and navigated to `/hakutulokset`.
- Session `3212424043f0` after adding `click_button(...)`, surfacing nearby form actions, and adding a price-visible extraction hint:
  - 30 steps / 240.3s timeout
  - 111.9k input tokens / 5.1k output tokens / `$0.4119`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=8ce7ae57-a170-0a06-db97-9703f56e612f`
  - Positive: the model used `click_button("Näytä laajakaistat")`; screenshot summaries exposed the visible submit action and later the product-card add-to-cart actions.
  - Positive: it reached visible product results and began structural extraction.
  - Remaining blocker: `extract_repeated_items(...)` still chose global/nav `li` records before priced offer cards. `page_snapshot(visible_only=False)` recommended `extract_grid_rows` / `li`, while the useful DOM structure was `subscriptioncard subscriptioncard--bordered`. A manual JS probe found three visible subscription cards with names and prices, but the agent burned the remaining budget probing and then restarted the task.

General fixes completed in this slice:

- Added `page_readiness()` and `wait_for_page_ready(...)`; screenshots now settle briefly and can report unresolved template markers/skeleton readiness warnings.
- Tightened `screenshot_state` so it avoids nav-only summaries, reports form fields/actions when visible, and emits a short `next_extract_hint` when price/product signals are visible.
- Enriched `form_fields_snapshot(...)` with validity/ARIA/autocomplete state, messages, stricter suggestion filtering, nearby actions, and compact active-field metadata.
- Added `fill_and_select_suggestion(...)` for framework autocomplete fields.
- Added `click_button(...)` for visible named controls, avoiding coordinate clicks and broad global JS selectors.

Next local-first architectural fix:

- Improve repeated-card discovery/scoring before any more full DNA reruns:
  - prefer repeated containers with product/card/package/offer/plan/subscription class names when they contain headings plus descendant price text;
  - downrank global navigation/list structures even harder when they have no descendant prices and many links;
  - make `extract_repeated_items(context=...)` use context as a soft scorer, not a selector-specific route;
  - add a focused Rust helper test where a page has nav `<li>` rows plus visible `subscriptioncard` product cards, and assert the card group wins.
- Add a compact "priced cards visible but extraction picked nav" diagnostic to extraction output so the model does not continue with bad `li` records.
- Only after that, rerun DNA locally once. Do not launch eval-platform fanout from the current state.

Follow-up DNA evidence after repeated-card and scroll fixes:

- Session `ec0613b7cfad`:
  - 27 steps / 240.4s timeout
  - 87.5k input tokens / 4.4k output tokens / `$0.3282`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=abd310b5-012d-ebc6-008a-c08fa681707f`
  - The model still burned turns on scroll/button state. This exposed a general helper bug: `scroll(0, 2000)` was interpreted as a wheel event at y=2000, not a delta scroll.
- Session `586fd882a723` after fixing common scroll semantics:
  - 31 steps / 240.4s timeout
  - 99.3k input tokens / 4.9k output tokens / `$0.3712`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=1b3b67a8-8e79-1841-faba-fb917344e1ff`
  - It reached package data and `extract_repeated_items(...)` selected `div.dna-grid-item` with `final_candidate.ready_for_done=true`, but the result file still included aggregate/noisy records.
- Session `5d0305089bc7` after priced-context record filtering:
  - 29 steps / 240.3s timeout
  - 84.1k input tokens / 6.0k output tokens / `$0.3428`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=00d951f6-4993-0c72-905f-166a43170400`
  - It solved the data extraction locally: all 5 address-specific packages were captured and written to `dna_broadband_packages.json`.
  - It failed because the model streamed a long Markdown final answer instead of calling `done(...)` before the outer timeout.
- Session `38b88d8f36b6` after surfacing JSON artifacts as `result_file_candidates`:
  - 36 steps / 300.4s timeout
  - 162.9k input tokens / 6.0k output tokens / `$0.5788`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=927ace84-3497-1a5e-17ad-98476688902f`
  - Regression: the model navigated into the generic `www.dna.fi` 5G package page and produced a 3-package answer. The result file was not surfaced because `outputs_dir()` is a shared cwd and the same filename already existed, so artifact collection ignored an overwritten file.
- Session `ad2259eff6be` after collecting modified output files and extracting result-file paths from stdout:
  - 38 steps / 300.4s timeout
  - 113.1k input tokens / 6.2k output tokens / `$0.4325`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=6c41b4c2-8d0c-4f94-1e6b-d64171ca0d53`
  - The agent reached the correct `kauppa.dna.fi/laajakaista/valitse-netti` result page and saw all 5 packages in body text by step 28.
  - It still kept validating with screenshots and broad extraction. `result_file_candidates` appeared for `grid_rows.json`, proving the artifact/result-file visibility path works, but `extract_grid_rows(...)` falsely marked broad nav/list rows as `done_ready`.

General fixes completed in this follow-up:

- `scroll(0, y)` now behaves like common delta scrolling from the viewport center; explicit coordinate wheel events still work with `dy=...`.
- `extract_repeated_items(context=...)` now favors priced product/package/offer/plan/subscription cards and filters aggregate/no-price records when the context asks for priced records.
- Browser-script tool output now surfaces JSON/CSV/text artifacts as compact `result_file_candidates` with path, format, record count, fields, and a `done(result_file=path)` hint.
- Artifact collection now detects modified existing output files, not only brand-new paths.
- Result-file candidate detection also falls back to existing file paths printed in stdout, so hand-written scripts that print `Saved to: /path/result.json` still get a compact finalization path.
- `extract_rows(...)` no longer marks generic nav/list rows with only links/actions as `done_ready`; rows need table cells, descriptions, or file actions.

Updated next local target:

- Do not run eval-platform fanout yet.
- Before another full DNA run, make `page_snapshot()` and extraction routing prefer repeated priced records over broad app-state/grid rows whenever price/product/package signals are present.
- Add a stop-after-complete mechanism that is architectural, not prompt bloat: when a tool output contains a high-confidence extracted record set or body text with all requested entities, the next observation should push toward a single small transform or `done(...)`, not more screenshots.
- Then rerun only this DNA task locally. Success criteria: correct 5-package final answer, explicit `done`, under 20 steps, and materially below 80k input tokens.

Latest DNA evidence after priced-record routing and finalization work:

- Session `536529981056` after adding effect-aware `click_button(...)`, `completion_candidates`, and priced repeated-record routing:
  - 36 steps / 260.3s timeout
  - 122.6k input tokens / 8.4k output tokens / `$0.4933`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=996d9864-d25f-5f9f-72be-791554f40301`
  - Positive: the address submit path worked and the model used `click_button("Näytä laajakaistat")`.
  - Positive: `page_snapshot(visible_only=False)` recommended `extract_repeated_items(selector='div.dna-grid-item', root_path='document', ...)`.
  - Positive: `extract_repeated_items(...)` wrote `packages.json` with `final_candidate.ready_for_done=true`, `record_count=13`, and model-visible `completion_candidates`.
  - Remaining blocker: Sonnet explicitly acknowledged the extraction, then ignored the ready result file and spent the remaining budget re-reading, re-scraping, scrolling, and screenshotting instead of calling `done(...)` or doing one bounded transform.
- Session `db0c818bb5a0` after suppressing large previews when a ready completion candidate exists:
  - 35 steps / 260.3s timeout
  - 133.6k input tokens / 6.5k output tokens / `$0.4985`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=9807a7a8-3edc-eed5-e650-325520ccfb94`
  - This run diverged before the finish gate: the model invented `extract_repeated_items(hint=...)`, got a keyword error, then recovered with an overly broad selector and produced 137 noisy records with `ready_for_done=false`.
  - New fix from this evidence: `extract_repeated_items(...)` now accepts `hint=` as a tolerant alias for `context=`, so near-correct intent-bearing calls trigger the existing priced-card scorer instead of causing an error/recovery spiral.

General fixes completed in this slice:

- `click_button(...)` now reports activation effect. It coordinate-clicks the named visible control, waits for URL/text/price/control changes, falls back to DOM click/requestSubmit only after a no-op, and returns a compact `activation` diagnostic plus `next_step` when nothing changed.
- Browser-script model output now treats ready result files as a finish gate: `completion_candidates` are surfaced first, large summaries/previews are suppressed, duplicate candidates are deduped by result file, and the model sees a direct rule to call `done(result_file=...)` or run one bounded transform.
- `extract_repeated_items(hint=...)` is accepted as an alias for `context=...`; the documented form remains `context="what records matter"`.

Updated next local target:

- Do not run eval-platform fanout yet.
- Rerun DNA only after the extraction helper has a stronger default for product cards:
  - when context/hint mentions packages/products/prices and the page has visible `subscriptioncard`/product-card records, prefer those over generic `div.dna-grid-item` aggregates;
  - if helper output has `ready_for_done=false` but a smaller high-signal priced card group exists, return a compact diagnostic and suggested exact selector instead of dumping broad noisy records;
  - add a focused fixture with aggregate grid containers, subscription-card child records, and noisy card-like nav content.
- Add a bounded transform pattern that is still general: a helper or output contract that lets the model convert extracted records into the user-requested schema in one script and immediately produce `done(result_file=...)`, without further browser inspection.

### Product-Card Extraction And JSON Tolerance Follow-Up

Local implementation completed:

- `repeated_items_snapshot(...)` now scores groups by per-record price/name coverage, product-like classes, and aggregate-price penalties, so broad wrappers with many prices lose to repeated offer/product records.
- It also infers repeated product cards around controls such as checkboxes, radios, and buttons. This handles generated SPA component trees where semantic classes are opaque but each selectable plan has a bounded card, prices, and product-like text.
- `extract_repeated_items(...)` now uses the same priced-card scorer for `context=` / `hint=` and reports a compact `priced_alternative_available` diagnostic when an explicit broad selector misses a better priced group.
- Browser-script `SnapshotDict` objects now tolerate accidental `json.loads(snapshot)` calls. This fixes a real wasted-turn pattern from the latest trace without adding prompt instructions or task-specific code.

Validation:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_repeated_items_snapshot_returns_compact_groups -- --nocapture`
- `cargo test -p browser-use-browser browser_script_extract_repeated_items_ -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Latest local DNA evidence:

- Session `375e5049085e`:
  - 28 steps / 260.2s timeout
  - 100.1k input tokens / 9.4k output tokens / `$0.4413`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=212bf541-9cf4-78b6-c9f2-2a4ccb020017`
  - The run reached `kauppa.dna.fi/laajakaista/valitse-netti` and the model manually discovered all 5 address-specific packages, but the extraction helper missed the generated control/card structure and the model kept inspecting details until timeout.
- Session `10d3a1808b02`:
  - 36 steps / 260.1s timeout
  - 83.4k input tokens / 4.5k output tokens / `$0.3173`
  - Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=06ef07c4-9bab-2760-1e0c-52b9b876a163`
  - The run was cheaper, but it stayed on the generic DNA page, extracted 3 generic 5G packages with `ready_for_done=true`, and did not satisfy the address-specific task.
  - It also exposed two general runtime issues: an early `Page.captureScreenshot` timeout recovered but cost progress, and `json.loads(page_snapshot(...))` raised a TypeError before the compatibility patch.

Updated evaluation policy:

- Keep working locally first with Browser Use Cloud plus the local Rust binary.
- When eval-platform runs are justified, use `claude-sonnet-4-6` only. Do not use GPT-5.4-mini for browser automation.
- Start eval-platform validation with very small slices, around 5 tasks. Scale only after local task evidence is strong and the small slice has clean Laminar traces and sensible cost.

Next local target:

- Build a direct local probe for DNA that navigates/fills to the package chooser and calls `repeated_items_snapshot(...)` / `extract_repeated_items(...)` without the LLM. This isolates helper quality from model navigation and should confirm whether inferred control-card extraction sees the 5 true address-specific packages.
- If helper output is correct, rerun only DNA through the model and inspect whether the finish gate is still ignored. If it is, fix the output contract/finalization path generally before any eval-platform run.
- If helper output is wrong, continue improving general repeated-card/card-control extraction locally; do not compensate with DNA-specific prompt text.

### Direct Cloud Browser-Script Probe And Form Visibility Fix

Local tooling added:

- Added `examples/rust/browser_script_cloud.py` in the Browser Use fork. It starts a short-lived Browser Use Cloud browser, creates a Rust terminal session, attaches `browser_script` through `BU_CDP_URL`, runs arbitrary helper code, prints the session id / SQLite handle, and stops the browser.
- Added `browser-use-terminal browser-script --timeout-seconds` so local direct probes are not limited to the previous hardcoded 30s CLI timeout.

General runtime fixes from the direct DNA probe:

- `form_fields_snapshot(...)` now returns rendered form fields, not only fields currently inside the viewport. It annotates `field_visibility` with `in_viewport`, `near_viewport`, `offscreen`, and `distance_y`.
- `fill_form_field(...)` now matches rendered fields and relies on the existing CDP scroll/focus path to bring them into view. It also polls briefly for matched SPA fields to become enabled instead of failing immediately on delayed dependent inputs.
- `repeated_items_snapshot(...)` now gives a default priority boost to repeated priced records and penalizes aggregate/excess-price containers. On pages with actual priced product cards, this prevents no-price marketing cards or broad grid wrappers from becoming the top recommendation.

Validation:

- `python3 -m py_compile examples/rust/browser_script_cloud.py`
- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_form_field_helpers_match_labels_and_suggestions -- --nocapture`
- `cargo test -p browser-use-browser browser_script_repeated_items_snapshot_returns_compact_groups -- --nocapture`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Direct Cloud evidence:

- Smoke session `68ee9c34d272` proved the direct runner can create a Cloud browser, attach the Rust browser-script runtime through remote CDP, execute helper code, and stop the Cloud browser.
- DNA form probe `db8f755e0d1d` confirmed the form helper fix live:
  - `form_fields_snapshot(...)` surfaced the below-viewport `zipcode`, `street`, and `apartment` fields.
  - `fill_form_field("input#address-search-zipcode", "00510")` filled the postal code.
  - `fill_and_select_suggestion("input#address-search-street", "Inkoonkatu", "Inkoonkatu")` scrolled/focused the offscreen street field and selected the street suggestion.
  - The helper exposed the nearby `Näytä laajakaistat` action without screenshot/coordinate discovery.
- DNA package-surface probe `4490efef66a6` confirmed the repeated-card scorer fix live:
  - Before the fix, `repeated_items_snapshot(...)` recommended `div.dna-card-free` or broad `div.dna-grid-item` groups.
  - After the fix, it recommends `div.subscriptioncard` with `count=3`, `price_record_count=3`, and `price_signal_count=12` on the generic DNA package surface.

Remaining local blocker:

- The direct form flow still did not produce the address-specific 5-package result. It reached the generic DNA package surface and extracted the 3 generic 5G cards. `click_button("Näytä laajakaistat")` reported no visible state change after apartment text entry, so the next local investigation should focus on general autocomplete/validation semantics:
  - distinguish "typed text into an autocomplete field" from "selected a valid option";
  - surface field validation/messages and disabled submit state more explicitly after no-op activation;
  - make `fill_and_select_suggestion(..., require_selection=False)` return stronger diagnostics when the field looks autocomplete-backed but no valid option was selected.

Do not run eval-platform fanout from this state. The right next step is another local direct probe and then a single local DNA LLM run only after the address-specific form path is mechanically reliable.

### Combined Address Diagnostic And Click Budget Fix

The actual `real_v8` DNA tasks are indexes `21` and `39`. They start from `https://kauppa.dna.fi/laajakaista/valitse-netti`, but the live site currently redirects to the generic three-field DNA broadband form. The task text says to type a combined address, while the page exposes separate postal-code, street, and apartment fields.

General fixes made:

- `click_button(...)` now respects the caller's timeout budget after a target is found. It no longer spends unbounded time in effect waits and retries.
- The cheap DOM activation fallback still runs even for tiny timeouts, so robust click semantics do not disappear when the caller asks for a fast probe.
- `_control_page_signature(...)` now includes `target_rect`, and click retries re-read the target's current rect before clicking. This fixes stale-coordinate retries after DOM activation or scrolling changes the page position.
- No-op click retries use shorter waits so two real retries can fit into a normal helper timeout.
- `fill_and_select_suggestion(...)` now detects a common general failure shape: a combined address string typed into a postal/zip field on a rendered multi-field address form. It returns `selection_diagnostic.possible_multi_field_form` with the nearby fields and their disabled/visibility state.

Validation:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_click_button_reports_noop_and_dom_fallback_effect -- --nocapture`
- `cargo test -p browser-use-browser browser_script_form_field_helpers_match_labels_and_suggestions -- --nocapture`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Direct Cloud evidence:

- Session `d7102368-2279-4c5f-a623-a2aaad8c98e4` showed the previous helper could fill the three DNA fields, but one click retry was not enough and the output still extracted 3 generic 5G cards.
- Session `d9140055-abd1-4943-9749-dd6ebf1e0aaf` verified that target rects are refreshed and two no-op retries happen, but the generic DNA form still did not navigate for typed apartment variants. This showed the remaining issue is form/address validity, not stale coordinates.
- Session `4bcceb3b-6564-4902-9644-fd4d5114a17c` tried apartment variants `3`, `3A`, `3 A`, `3A 10`, `3 A 10`, and `3 A AS 10`; none navigated via Enter or button click. This suggests the current public page may not expose a committed apartment option for that address through the three-field flow.
- Session `6056683d-926b-407c-9501-395a6db1eb6b` confirmed the eval URL redirects to the generic form. A combined address got typed into the postal-code field, produced no suggestions, and still extracted only the 3 generic cards.
- Session `8d6a4681-6d69-4836-9cfc-03bc14354828` verified the new diagnostic live. The tool output now says the typed value looks like a combined address on a split address form and lists `input#address-search-street` plus disabled `input#address-search-apartment` as nearby fields.

Next local target:

- Run the full Rust agent locally on `real_v8` task `21` or `39` and inspect whether it recovers from `possible_multi_field_form` by splitting the address across fields.
- If the model still continues with the invalid combined value, improve the compact tool-output contract or final audit. Avoid adding a prompt rule for DNA.
- If it recovers but no address-specific result is available, treat the live task as ambiguous/stale and move to the next hard local task while preserving the diagnostic as a general form-recovery improvement.

### Local DNA Agent Run And Screenshot Extraction Hint

Local Rust-agent run:

- Session `6f320f3fce02`
- Task: `real_v8` index `21`
- Model: `claude-sonnet-4-6`
- Result: timeout after 31 steps / 260.4s, exit code `124`
- Cost: 109,979 input tokens / 4,403 output tokens / `$0.3960`
- Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=f3163749-c03e-c8c0-da88-877eab2ad323`

What the run proved:

- The model did not need the new `possible_multi_field_form` diagnostic in this run. From the screenshot/form summary alone it correctly inferred that the live DNA page has separate postal-code, street, and apartment fields.
- The expensive failure happened after the address form was filled. Once package-card headings were visible, the model kept taking screenshots, scrolling, and re-clicking instead of switching to `repeated_items_snapshot(...)` or `extract_repeated_items(...)`.
- The screenshot summaries at the package area exposed headings like `DNA Netti Huoleton 5G 300M`, but did not expose the repeated-card extraction route. This made the next efficient action too implicit.

General fix made:

- `_screenshot_state_summary(...)` now calls `page_snapshot(..., include_repeated=True)` and carries compact repeated-record recommendations into screenshot summaries.
- When repeated priced records are visible, screenshot state can now include:
  - `recommended_action: "extract_repeated_items"`
  - `next_extract_hint` with the selector/root path
  - compact `repeated_items.recommended_group`
- This is a message-history/tool-response fix, not a DNA-specific prompt rule. It makes pixels actionable when product/list records are visible and should reduce screenshot loops across product, ticket, listing, and package pages.

Validation:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_screenshot_state_summary_is_compact_and_actionable -- --nocapture`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Direct Cloud evidence:

- Session `b0e1687f-f2c1-4617-8ba2-77e6bfd81728` scrolled to the visible DNA product-card area and called `_screenshot_state_summary("packages_visible")`.
- The summary returned `recommended_action: "extract_repeated_items"` and `next_extract_hint: extract_repeated_items(selector='div.subscriptioncard', root_path='document', ...)`.
- The recommended group was `div.subscriptioncard`, `count=3`, `price_signal_count=12`, with parent heading `5G-laajakaistat kotiin`.

Next local target:

- Rerun a shorter local Rust-agent DNA task after this screenshot-summary change. The expected behavioral improvement is that once package cards are visible, the model should call `extract_repeated_items(...)` instead of continuing screenshot/scroll/click loops.
- If it still ignores the recommendation, the next architecture change should be stronger but still general: make repeated-record recommendations appear as a concise top-level tool output field, not buried inside screenshot summary text.

### DNA Rerun After Screenshot Extraction Hint

Local Rust-agent rerun:

- Session `de04dcac6c65`
- Task: `real_v8` index `21`
- Model: `claude-sonnet-4-6`
- Result: timeout after 26 steps / 230.3s, exit code `124`
- Cost: 97,720 input tokens / 3,722 output tokens / `$0.3490`
- Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-5aaa-222ee805547f`

What improved:

- The model reached the visible DNA product-card section and then called `extract_repeated_items(...)`.
- It extracted the 3 visible DNA packages before moving on.
- This confirms the screenshot extraction-route hint changed behavior in the desired direction.

What still failed:

- The run still spent too many turns getting through one provider, then over-explored hypothetical `Valokuitu` / `Kaapelinetti` tabs after already extracting the visible DNA package records.
- It then moved to Telia too late and timed out.
- Screenshot summaries also exposed noisy repeated-record hints for non-priced navigation/list groups early in the page, such as `li` or `div.dna-card-free`, before true product cards were visible.

Follow-up fix made:

- `_screenshot_state_summary(...)` now only surfaces repeated-record `recommended_action` / `next_extract_hint` when the recommended group is priced (`price_signal_count > 0` or field coverage includes prices).
- This keeps the useful product-card extraction hint while suppressing nav/list noise.

Validation:

- `python3 -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_screenshot_state_summary_is_compact_and_actionable -- --nocapture`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Next architectural target:

- Reduce multi-step task waste after a partial extraction. The agent needs a general way to preserve completed extraction files and move to the next explicit task requirement instead of re-validating or exploring optional categories.
- Candidate mechanism: a compact task-progress / result ledger in the Rust core that records completed extraction artifacts and remaining user requirements, without a task compiler. The ledger should be derived from agent actions and explicit user requirements, not hard-coded dataset categories.

### DNA Rerun After Ready Metadata Promotion

General fix made:

- `browser_script` result metadata files are now promoted into top-level `completion_candidates`, not only loose `result_file_candidates`.
- Completion candidates include `source_page`, record counts, coverage, result file, and result format when those fields are available in the sidecar metadata.
- The finish gate now explicitly distinguishes two cases:
  - if the result file satisfies the whole task, call `done(result_file=...)`;
  - if the task asks for more independent sources or items, keep the file as completed evidence and move to the next missing requirement.
- When a ready completion candidate exists, large printed extraction text is omitted from the model-visible tool output. The model sees `printed_text_omitted` plus the metadata instead of another large `text_compact` block.

Why this is architectural:

- This is not a DNA rule. Any extractor or browser script that writes a ready metadata artifact can now create a compact, durable "completed evidence" signal.
- It reduces the common failure where the model extracts correctly, then spends turns re-reading, reprinting, or re-scraping the same records because the transcript does not make the artifact's status unambiguous.
- It keeps the system prompt simple. The pressure is moved into the tool-output contract: completed evidence appears as structured, compact state at the top of the next observation.

Validation:

- `cargo fmt --check`
- `cargo test -p browser-use-core browser_script_ready_metadata_artifact_is_promoted_for_completion -- --nocapture`
- `cargo test -p browser-use-core browser_script_ready_final_candidate_is_promoted_for_completion -- --nocapture`
- `cargo test -p browser-use-core browser_script_json_artifact_surfaces_result_file_candidate -- --nocapture`
- `cargo test -p browser-use-core browser_script_ -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Local Rust-agent rerun:

- Session `eb5db80247b1`
- Task: `real_v8` index `21`
- Model: `claude-sonnet-4-6`
- Result: timeout after 28 steps / 220.3s, exit code `124`
- Cost: 94,600 input tokens / 3,953 output tokens / `$0.3431`
- Laminar: `https://laminar.sh/project/f07da4a9-b7de-488a-91e3-e17c5f6d676a/traces?traceId=a3f32fb1-f0de-b3c0-429d-095f1d488089`

What improved:

- After extracting DNA packages, the model saw `completion_candidates` and a `finish_gate` instead of only weaker result-file hints.
- It moved to Telia instead of spending more turns exploring optional DNA tabs or re-checking the same package section.
- Input tokens dropped again versus the previous DNA rerun, but the task still timed out.

Remaining blocker:

- The run reaches Telia too late. The current path still spends too many turns on the first provider before the second independent provider begins.
- The next local target is to reduce first-provider cost further and make the Telia form/action flow mechanically reliable with direct probes first, then a single local LLM rerun.
- Do not launch eval-platform fanout from this state. Keep working locally with Cloud browsers and the Rust binary until this task or another hard class is solved end to end.

### Progress Tracking Reset After Direction Correction

Timestamp: 2026-06-01 07:15 PDT

I had not been tracking progress rigorously enough. The plan had a progress log and the SQLite traces had evidence, but the working loop was still too implicit. Going forward, every meaningful local run or architecture change should record:

- state database path and session id,
- model, max steps, timeout, and browser mode,
- whether the task was manually correct,
- turn count, observe count, screenshot count, largest model-visible outputs, max context, and total tokens,
- concrete failure mode from what the model actually saw,
- general architecture/tool/message-history change made,
- validation commands,
- next local task or batch to run.

New local trace tool:

- Added `examples/rust/inspect_rust_trace.py`.
- It reads the Rust state SQLite DB and reports turn timeline, model-visible output size, screenshots, observe loops, token growth, artifacts, and trace-level signals.
- `examples/rust/eval_one_task_cloud.py` now prints the exact inspector command for each run.

Evidence from old DNA trace:

- Session: `c387417c3744`
- DB: `/tmp/but-lean-prompt-dna/state.db`
- Result: timed out before final answer.
- Turns: 30 model requests / 29 model calls.
- Browser script: 28 calls, including 12 `observe` turns.
- Screenshots/interact scripts: 12.
- Extraction scripts: 1.
- Model-visible tool output: 68,404 chars.
- Total tokens: 101,422.
- Max context: 26,207 tokens.

General fix made from that evidence:

- `browser_script` now waits longer before returning an async `running` result.
- `observe_browser_script(...)` now waits until the script finishes or the observe deadline, instead of returning immediately on the first progress/image delta.
- Default initial wait is now controlled by `LLM_BROWSER_SCRIPT_INITIAL_WAIT_MS` and defaults to 20s.
- This is a general scheduling/message-turn change. It reduces model polling turns without teaching a task-specific behavior.

Evidence from new DNA run after scheduling change:

- Session: `94791612fe56`
- DB: `/tmp/but-scheduling-dna/state.db`
- Result: timed out at 360s / exit 124 before final answer.
- Browser script observe turns dropped from 12 to 1.
- Total turns still reached 29.
- Screenshots/interact scripts increased to 21.
- Extraction scripts stayed at 1.
- Model-visible tool output increased to 113,577 chars.
- Total tokens increased to 149,014.
- Max context reached 40,966 tokens.

Learning:

- The scheduling fix worked, but it exposed the next deeper issue: the model still browses with many small screenshot scripts instead of writing larger CDP/JS/network scripts.
- The model-visible tool description and screenshot summaries were biasing it toward helper-driven observations.
- A large helper surface is the wrong center of gravity. BrowserHarness should stay a thin Python/CDP action plane, with architecture work in compaction, message turns, sub-agent semantics, and trace review.

General simplification made:

- Reduced `prompts/browser-agent-system.md` to a short BrowserHarness-style contract: thin Python/CDP harness, bounded scripts, compact evidence, real browser actions, and clear impossible/blocker proof.
- Reduced `prompts/browser-script-tool-description.md` from a broad helper catalog to the core primitives: `cdp`, `js`, navigation/wait, screenshot, input, scroll, network/HTTP, artifacts, and `emit_output`.
- Removed the model-visible list of high-level extraction/form/app-state helpers from the tool description. Helpers may still exist internally for now, but they should not dominate the model’s mental model.

Screenshot output simplification:

- `screenshot(...)` no longer automatically emits the large `_screenshot_state_summary(...)`.
- State summaries are now opt-in with `screenshot(..., state=True)` / `include_state=True`.
- This is intended to stop every visual check from adding several thousand characters of DOM/form/repeated-record text to the next model turn.

Validation after these changes:

- `python -m py_compile examples/rust/eval_one_task_cloud.py examples/rust/inspect_rust_trace.py`
- `python -m py_compile crates/browser-use-browser/src/browser_script_helpers.py`
- `cargo fmt --check`
- `cargo test -p browser-use-browser browser_script_ -- --nocapture`
- `cargo test -p browser-use-providers default_instructions -- --nocapture`
- `cargo test -p browser-use-core compacted_context_keeps_browser_agent_contract -- --nocapture`
- `cargo test -p browser-use-core browser_script_history_keeps_only_latest_image_message -- --nocapture`
- `cargo build -p browser-use-cli --bin browser-use-terminal`

Current conclusion:

- Do not add more semantic helpers until traces prove a repeated low-level browser need.
- Next local loop should run a small 3-5 task batch with the lean tool description and screenshot summaries disabled by default, then inspect all traces with `inspect_rust_trace.py`.
- The next likely architecture lever is a stronger compaction/progress ledger that preserves completed evidence and remaining requirements while dropping repetitive screenshot/tool-output history.
