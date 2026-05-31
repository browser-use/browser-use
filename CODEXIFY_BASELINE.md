# Codexification Baseline Status

Phase 0 status for `CODEXIFY_IMPLEMENTATION_PLAN.md`.

This is a working baseline note, not a full test report. The goal is to capture enough current behavior and existing coverage to start the runtime refactor safely.

## Current Coverage Map

- DOM serializer and selector map:
  - `tests/ci/browser/test_dom_serializer.py`
  - Covers cleaned DOM representation, `selector_map`, shadow DOM, same-origin iframe content, iframe tags, and click execution through indexed elements.
- Multi-action guards:
  - `tests/ci/test_multi_act_guards.py`
  - Covers `terminates_sequence` metadata, static sequence termination, URL-change guard, focus-change guard, and safe chained inputs.
- Coordinate clicking:
  - `tests/ci/test_coordinate_clicking.py`
  - Covers click schema switching, coordinate-capable model detection, and externally passed `Tools`.
- Tabs:
  - `tests/ci/browser/test_tabs.py`
  - Covers creating, switching, closing, background tabs, and completion after tab operations.
- Screenshots:
  - `tests/ci/browser/test_screenshot.py`
  - `tests/ci/test_screenshot_exclusion.py`
- Downloads, uploads, and security:
  - `tests/ci/security/test_download_filename_sanitization.py`
  - `tests/ci/security/test_upload_file_containment.py`
  - Related upload behavior appears in CLI and tool tests.
- Browser interactions:
  - `tests/ci/interactions/test_autocomplete_interaction.py`
  - `tests/ci/interactions/test_dropdown_aria_menus.py`
  - `tests/ci/interactions/test_dropdown_native.py`
  - `tests/ci/interactions/test_radio_buttons.py`
- Extraction and markdown:
  - `tests/ci/test_structured_extraction.py`
  - `tests/ci/test_markdown_extractor.py`
  - `tests/ci/test_markdown_chunking.py`
  - `tests/ci/test_extract_images.py`
- Tool registry and action parameter injection:
  - `tests/ci/infrastructure/test_registry_core.py`
  - `tests/ci/infrastructure/test_registry_validation.py`
  - `tests/ci/infrastructure/test_registry_action_parameter_injection.py`
- Task evals:
  - `tests/ci/evaluate_tasks.py`
  - `tests/agent_tasks/*.yaml`
  - Requires `BROWSER_USE_API_KEY` and `GOOGLE_API_KEY` for meaningful non-skipped results.

## Baseline Commands Run

```bash
uv run pytest tests/ci/test_coordinate_clicking.py tests/ci/test_multi_act_guards.py::TestTerminatesSequenceMetadata -q
```

Result: `42 passed in 0.08s`.

```bash
uv run pytest tests/ci/test_multi_act_guards.py::TestRuntimeGuard::test_click_link_aborts_remaining -q
```

Result: `1 passed in 12.36s`.

Notes:

- Verified real-browser `multi_act` runtime guard.
- Click on link navigated from `/page_a` to `/page_b`.
- Remaining queued actions were skipped after page change.
- Fixture produced expected favicon 500s and a page readiness timeout warning.

```bash
uv run pytest tests/ci/browser/test_dom_serializer.py::TestDOMSerializer::test_dom_serializer_with_shadow_dom_and_iframes -q
```

Result: `1 passed in 12.25s`.

Notes:

- Selector map contained 10 interactive elements.
- Serialized DOM indices all mapped back into `selector_map`.
- Regular DOM, shadow DOM, same-origin iframe content, and iframe tags were represented.
- Clicks succeeded on regular DOM button, shadow DOM button, and same-origin iframe button.
- Page click counter reached `3`.

```bash
uv run pytest tests/ci/test_multi_act_guards.py tests/ci/browser/test_tabs.py tests/ci/browser/test_screenshot.py -q
```

Result: `20 passed in 58.63s`.

Notes:

- Covered `multi_act`, tab creation/switching/closing, background tabs, rapid tabs, and screenshot capture with vision enabled.
- Existing noisy baseline:
  - Tab tests log `No TargetID found ending in tab_id=...` warnings while still passing.
  - Mock judge trace logs a Pydantic validation error for a missing `verdict` field while still passing.
  - Local favicon requests and page readiness timeout warnings are common.

```bash
uv run pytest tests/ci/interactions -q
```

Result: `14 passed, 10 skipped in 46.81s`.

Notes:

- Covered autocomplete rewrite detection, combobox/datalist handling, sticky input retry, sensitive input typing, and radio buttons.
- Dropdown tests are skipped in the current suite.

```bash
uv run pytest tests/ci/security/test_download_filename_sanitization.py tests/ci/security/test_upload_file_containment.py -q
```

Result: `19 passed in 0.04s`.

Notes:

- Covered download filename sanitization, containment checks, and upload path containment.
- Upload containment test intentionally logs an unavailable file path error before passing.

```bash
uv run pytest tests/ci/infrastructure/test_registry_core.py tests/ci/infrastructure/test_registry_validation.py tests/ci/infrastructure/test_registry_action_parameter_injection.py tests/ci/test_structured_extraction.py tests/ci/test_search_find.py -q
```

Result: `87 passed, 8 skipped in 203.30s`.

Notes:

- Covered current dynamic registry behavior, special parameter injection, schema validation, structured extraction, search, and find-elements actions.
- Current suite logs errors for mocked browser session CDP access in `test_browser_session_double_kwarg`; the test expects this and passes.
- Empty DOM detection currently waits, reloads, and continues instead of failing immediately.

```bash
uv run python - <<'PY'
from pathlib import Path
from dotenv import load_dotenv
import os
import subprocess
import sys

load_dotenv(Path('../browser-use/.env'))
completed = subprocess.run([sys.executable, 'tests/ci/evaluate_tasks.py'], env=os.environ.copy())
raise SystemExit(completed.returncode)
PY
```

Result: `0/2 PASSED`, exit code `1`.

Notes:

- `BROWSER_USE_API_KEY` and `GOOGLE_API_KEY` were both present in the main worktree `.env`.
- Both browser tasks completed agent execution:
  - `browser_use_pip.yaml`: 6 steps; final output found `pip install browser-use`.
  - `amazon_laptop.yaml`: 5 steps; final output returned a first Amazon laptop result.
- The judge failed both tasks because the Google API key is expired: `400 INVALID_ARGUMENT`, `API key expired. Please renew the API key.`
- This is an eval infrastructure blocker, not evidence that the browser tasks failed.

## Real Agent Smoke

Used the main worktree `.env` and `ChatBrowserUse` against a local temporary HTTP page in headless Chromium.

Task:

```text
Open the local page, click the Reveal Answer button, then return only the revealed answer text.
```

Result: passed.

Metrics from the cost-tracked run:

- Success: `True`
- Steps: `5`
- Duration: `19.67s`
- Final result: `codexify-baseline-ok`
- Model: `bu-2-0`
- Total tokens: `18,197`
- Prompt tokens: `17,815`
- Cached prompt tokens: `6,113`
- Completion tokens: `382`
- Total cost: `$0.00909176`

## Phase 0 Assessment

- Current targeted baseline is healthy.
- Existing tests already cover many critical behaviors we need to preserve.
- Real `ChatBrowserUse` + Chromium smoke works and now has steps, duration, token usage, and cost recorded.
- Full repository test suite was not run in one command; instead, targeted suites covering the risky browser/runtime surfaces were run.
- Task eval judging is blocked by an expired Google API key, even though the agent executions produced plausible task outputs.

## Codexification Verification

Post-implementation targeted suite:

```bash
uv run pytest tests/ci/test_runtime_shape.py tests/ci/test_runtime_context.py tests/ci/test_runtime_events.py tests/ci/test_runtime_subscribers.py tests/ci/test_runtime_skills.py tests/ci/test_runtime_compaction.py tests/ci/test_native_tool_router.py tests/ci/browser/test_browser_services.py tests/ci/test_multi_act_guards.py::TestTerminatesSequenceMetadata tests/ci/test_multi_act_guards.py::TestRuntimeGuard::test_click_link_aborts_remaining -q
```

Result: `48 passed in 42.15s`.

Post-implementation real `ChatBrowserUse` + local Chromium smoke:

- Success: `True`
- Steps: `3`
- Final result: `codexify-agent-ok`
- Notes: public `Agent` path still works; the new runtime pieces remain side-by-side and do not change default behavior.

## Codexification Verification 2

After adding workspace artifact bridging, context-pressure compaction, direct native navigation services, centralized model capability detection, and lifecycle event helpers:

```bash
uv run pytest tests/ci/test_runtime_shape.py tests/ci/test_runtime_context.py tests/ci/test_runtime_events.py tests/ci/test_runtime_subscribers.py tests/ci/test_runtime_skills.py tests/ci/test_runtime_compaction.py tests/ci/test_native_tool_router.py -q
```

Result: `42 passed in 6.71s`.

Real `ChatBrowserUse` + headless local Chromium smoke:

- Success: `True`
- Steps: `6`
- Final result: `codexify-agent-ok`
- Notes: the `data:` URL page produced an empty indexed DOM, but the agent recovered with `evaluate` and completed. This is useful signal for future DOM/read escape-hatch work.

## Codexification Verification 3

After routing Agent side effects through runtime subscribers, extracting the runtime bridge, splitting native tool input schemas, and adding the typed message-manager mirror:

```bash
uv run pytest tests/ci/test_runtime_events.py tests/ci/test_runtime_subscribers.py tests/ci/test_agent_runtime_events.py tests/ci/browser/test_output_paths.py -q
uv run pytest tests/ci/test_native_tool_router.py -q
uv run pytest tests/ci/test_message_manager_typed_context.py tests/ci/test_agent_runtime_events.py tests/ci/test_runtime_context.py -q
```

Results:

- Runtime/subscriber/output-path suite: `17 passed, 3 skipped`.
- Native tool router suite: `13 passed`.
- Typed context/message-manager suite: `6 passed`.

Real `ChatBrowserUse` + headless local Chromium smoke:

- Success: `True`
- Done: `True`
- Steps: `4`
- Duration: `8.28s`
- Final result: `codexify-real-smoke-ok`
- Runtime events: `run.started`, repeated `context.built` / `model.delta` / `turn.completed`, then `run.completed`.
- Notes: the `data:` URL still produced an empty indexed DOM, and the agent again recovered with `evaluate`. This confirms the escape-hatch path remains useful while we preserve the DOM pipeline.

## Codexification Verification 4

After routing public click/type tools through the explicit browser service bundle:

```bash
uv run pytest tests/ci/browser/test_browser_services.py tests/ci/test_native_tool_router.py::test_native_tool_router_can_drive_simple_browser_task -q
uv run ruff check browser_use/tools/service.py tests/ci/browser/test_browser_services.py
uv run pyright browser_use/tools/service.py tests/ci/browser/test_browser_services.py
```

Results:

- Browser services and public tool direct-service suite: `8 passed`.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: the public `input` and `click` tool test monkeypatches `browser_session.event_bus.dispatch` to fail, proving those actions no longer need bubus dispatch in the public agent path.

## Codexification Verification 5

After routing public navigation/back/tab/keyboard tools through explicit browser services:

```bash
uv run pytest tests/ci/browser/test_browser_services.py tests/ci/test_native_tool_router.py::test_native_tool_router_can_drive_simple_browser_task -q
uv run ruff check browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
uv run pyright browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
```

Results:

- Browser services and public direct-service suite: `9 passed`.
- Native tool router smoke: passed as part of the same run.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: browser/session events are still allowed for observability; the new test rejects the old action-control events for public navigation, back, and send-keys.

## Codexification Verification 6

After expanding the typed context mirror to include agent state, page-specific actions, unavailable skills, and step metadata:

```bash
uv run pytest tests/ci/test_message_manager_typed_context.py tests/ci/test_runtime_context.py tests/ci/test_agent_runtime_events.py -q
uv run ruff check browser_use/agent/runtime/context.py browser_use/agent/message_manager/service.py browser_use/agent/service.py tests/ci/test_message_manager_typed_context.py
uv run pyright browser_use/agent/runtime/context.py browser_use/agent/message_manager/service.py browser_use/agent/service.py tests/ci/test_message_manager_typed_context.py
```

Results:

- Typed context and runtime event suite: `6 passed`.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: the typed context now mirrors the important non-browser sections of the legacy state prompt, not only task/history/browser state.

## Codexification Verification 7

Real `ChatBrowserUse` + headless local Chromium smoke after routing public navigation/click/input through services:

- Success: `True`
- Done: `True`
- Steps: `3`
- Final result: `codexify-real-service-ok`
- Notes: the task opened a local HTTP page, typed into an input, clicked a button, and finished with the revealed text through the public `Agent` path.

## Codexification Verification 8

After routing public page and element scroll through `ScrollService`:

```bash
uv run pytest tests/ci/browser/test_browser_services.py -q
uv run ruff check browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
uv run pyright browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
```

Results:

- Browser services and public direct-service suite: `10 passed`.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: whole-page and element-scoped scroll now reject the old `ScrollEvent` control path in tests.

## Codexification Verification 9

After routing public upload through `UploadService`:

```bash
uv run pytest tests/ci/browser/test_browser_services.py -q
uv run ruff check browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
uv run pyright browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
```

Results:

- Browser services and public direct-service suite: `11 passed`.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: the upload test uses a real temp file and rejects the old `UploadFileEvent` control path.

## Codexification Verification 10

After routing public `find_text` through `ScrollService`:

```bash
uv run pytest tests/ci/browser/test_browser_services.py -q
uv run ruff check browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
uv run pyright browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
```

Results:

- Browser services and public direct-service suite: `12 passed`.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: `browser_use/tools/service.py` now only dispatches old browser action events for dropdown options/select handling.

## Codexification Verification 11

After routing public dropdown options/select through `DropdownService`:

```bash
uv run pytest tests/ci/browser/test_browser_services.py -q
uv run ruff check browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
uv run pyright browser_use/browser/services.py browser_use/tools/service.py tests/ci/browser/test_browser_services.py
```

Results:

- Browser services and public direct-service suite: `13 passed`.
- Ruff: passed.
- Pyright: `0 errors`.
- Notes: `browser_use/tools/service.py` has no remaining direct `event_bus.dispatch(...)` calls. Some services still fall back to legacy event handlers when a direct watchdog instance is unavailable.
