# Browser Use Codexification Migration Notes

These notes describe the current migration state after the codexification cleanup work.

## Public API

- `Agent(...)`, `Browser(...)`, `Tools(...)`, and existing action names remain compatible.
- `AgentConfig` plus `Agent.from_config(...)` is available as the grouped public configuration path for new code.
- `ChatBrowserUse` remains the recommended default model for browser automation.
- `Browser(use_cloud=True)` remains the recommended production browser path when remote browser performance, CAPTCHA resistance, profile sync, or low-latency hosted execution matters.
- Native tool-call mode remains opt-in through `use_native_tool_calls=True`.
- The legacy action-list output path remains supported.
- Provider serializers now understand `ToolMessage` tool-result messages instead of only assistant/user/system messages.

## Internal Runtime Shape

- The main `Agent` service is now closer to an orchestrator. File handling, model I/O, run logging, skills, planning policy, judge handling, initial actions, lifecycle controls, variable substitution, action execution, rerun replay, and configuration helpers live in dedicated modules.
- Browser tool implementations have been split out of the giant tools service into focused action modules.
- Browser session state, logging identity, and reset cleanup now live in a focused `browser_use.browser.session_state` helper instead of the giant session module.
- Browser session lifecycle entrypoints, event-handler registration, browser stop handling, and cloud-session cleanup now live in `browser_use.browser.session_lifecycle`.
- Browser navigation event handling and lifecycle readiness waiting now live in `browser_use.browser.session_navigation`.
- Browser tab, focus-cache, and download event handlers now live in `browser_use.browser.session_tab_events`.
- Browser actor-style page and storage helpers now live in `browser_use.browser.session_actor_api`.
- Raw BrowserSession CDP target, storage, permission, viewport, and navigation helpers now live in `browser_use.browser.session_cdp`.
- Browser frame hierarchy, frame-target lookup, and node CDP-session resolution now live in `browser_use.browser.session_frames`.
- Browser screenshot capture and element-bound lookup now live in `browser_use.browser.session_screenshots`.
- Browser visual highlight overlays, coordinate-click highlights, and element-coordinate lookup now live in `browser_use.browser.session_highlights`.
- Browser tab metadata, current-target lookup, DOM coordinate lookup, selector-map access, and file-input search now live in `browser_use.browser.session_dom`.
- Provider-native `browser.done` schemas now use a native `StructuredDoneInput` model instead of reusing the legacy `StructuredOutputAction` action wrapper. The legacy structured-output action remains as a compatibility wrapper for action-list mode.
- Browser state capture now calls the DOM state builder directly instead of dispatching `BrowserStateRequestEvent`; screenshot capture during state refresh also uses direct CDP instead of `ScreenshotEvent`. The event handlers remain as compatibility adapters.
- The MCP server's direct browser-control methods now call `BrowserServiceBundle` services instead of dispatching browser action events.
- State-message rendering now lives in `browser_use.agent.message_manager.state_message`.
- The model-context manager now lives in `browser_use.agent.runtime.model_context`; `browser_use.agent.message_manager.service.MessageManager` is a compatibility shim for legacy imports.
- Storage-state load/save now uses direct watchdog methods from browser lifecycle paths; the old storage request event handlers remain as adapters.
- About:blank tab recovery now creates/focuses the replacement tab directly through CDP instead of dispatching a navigation request event.
- Tab-close focus recovery now calls a direct tab switch helper; `SwitchTabEvent` remains as a compatibility adapter.
- `BrowserSession.navigate_to()` now calls the direct navigation helper; `NavigateToUrlEvent` remains as a compatibility adapter.
- `BrowserSession.start()` now calls a direct startup method, and local browser launch calls the local launch service directly; `BrowserStartEvent` and `BrowserLaunchEvent` remain as compatibility adapters.
- `BrowserSession.stop()` and `kill()` now call direct lifecycle cleanup and direct watchdog finalizers; `BrowserStopEvent` and `BrowserKillEvent` remain as compatibility adapters.
- Browser hot-path actions route through direct services where parity has been established, while event-bus/watchdog compatibility remains for behavior that has not been safely removed yet.
- The largest browser, agent, and tools files have been split into focused modules while keeping the legacy public API intact.
- The typed runtime/context/event structures are present behind compatibility paths; the runtime model-context manager owns state around focused context/rendering helpers.

## Migration Guidance

- Existing users should not need code changes for normal `Agent(task=..., llm=...)` usage.
- New code can use `Agent.from_config(task, llm=..., config=AgentConfig(...))` to avoid the large legacy constructor surface.
- `Agent.from_config(..., **overrides)` accepts the same names as legacy `Agent(...)` keyword arguments; explicit overrides win over values in `AgentConfig`.
- Users who want provider-native tool calls can opt in with `use_native_tool_calls=True`; old model-output parsing remains available.
- Custom tools should continue returning structured `ActionResult` data where possible.
- New internal changes should prefer adding focused modules or services rather than growing `agent/service.py`, `tools/service.py`, or `browser/session.py`.

## Known Remaining Work

- The legacy `Agent(...)` constructor is still broad for backwards compatibility, but new code has a grouped `AgentConfig` path.
- The old message-manager import path is still part of the compatibility path, but the real model-context manager now lives under `agent.runtime`.
- The old structured-output action protocol is still supported for legacy action-list compatibility, but provider-native structured completion no longer depends on it.
- Watchdog/event-bus code still exists for browser compatibility paths, lifecycle wiring, and selected observers, but the core state and action hot paths no longer depend on event dispatch.
- Google judge-based task evals could not complete because the `GOOGLE_API_KEY` in the shared `.env` is expired.
- External local CDP validation requires launching Chrome with `--remote-allow-origins=*`; with that flag, `Browser(cdp_url=...)` connected and navigated successfully.
- Current `ChatBrowserUse` smoke/eval comparison is equal or better on success, steps, speed, and token usage for the measured baseline cases.

## Codexification Verification 107

After directizing public `BrowserSession.navigate_to()`:

```bash
uv run ruff check browser_use/browser/session_navigation.py browser_use/browser/session_dom.py tests/ci/browser/test_direct_navigation.py
uv run pyright browser_use/browser/session_navigation.py browser_use/browser/session_dom.py tests/ci/browser/test_direct_navigation.py
uv run pytest tests/ci/browser/test_direct_navigation.py -q
uv run pytest tests/ci/browser/test_direct_state_capture.py tests/ci/browser/test_cross_origin_click.py tests/ci/browser/test_session_start.py -q
uv run pytest tests/ci/browser/test_navigation_slow_pages.py tests/ci/browser/test_screenshot.py -q
```

Results:

- Direct navigation adapter tests: `2 passed`.
- State capture, cross-origin click, and session lifecycle tests: `11 passed`.
- Legacy navigation-event and screenshot tests: `7 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse` and the main worktree `.env`:

- `https://example.com` heading task: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.
- Final: `The main heading of https://example.com is 'Example Domain'.`

## Codexification Verification 108

After directizing public `BrowserSession.start()` and local browser launch:

```bash
uv run ruff check browser_use/browser/session.py browser_use/browser/session_lifecycle.py browser_use/browser/watchdogs/local_browser_watchdog.py tests/ci/browser/test_direct_lifecycle.py
uv run pyright browser_use/browser/session.py browser_use/browser/session_lifecycle.py browser_use/browser/watchdogs/local_browser_watchdog.py tests/ci/browser/test_direct_lifecycle.py
uv run pytest tests/ci/browser/test_direct_lifecycle.py -q
uv run pytest tests/ci/browser/test_direct_lifecycle.py tests/ci/browser/test_session_start.py -q
```

Results:

- Direct lifecycle tests: `4 passed`.
- Direct lifecycle plus browser session startup suite: `13 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse` and the main worktree `.env`:

- `https://example.com` heading task: success `True`, done `True`, `2` steps.
- Actions: `['navigate', 'done']`.
- Final: `The main heading on https://example.com is 'Example Domain'.`

## Codexification Verification 109

After directizing public `BrowserSession.stop()`/`kill()` and stop-aware watchdog finalizers:

```bash
uv run ruff check browser_use/browser/session_lifecycle.py browser_use/browser/session.py browser_use/browser/session_state.py browser_use/browser/watchdogs/aboutblank_watchdog.py browser_use/browser/watchdogs/storage_state_watchdog.py browser_use/browser/watchdogs/har_recording_watchdog.py browser_use/browser/watchdogs/local_browser_watchdog.py tests/ci/browser/test_direct_lifecycle.py
uv run pyright browser_use/browser/session_lifecycle.py browser_use/browser/session.py browser_use/browser/session_state.py browser_use/browser/watchdogs/aboutblank_watchdog.py browser_use/browser/watchdogs/storage_state_watchdog.py browser_use/browser/watchdogs/har_recording_watchdog.py browser_use/browser/watchdogs/local_browser_watchdog.py tests/ci/browser/test_direct_lifecycle.py
uv run pytest tests/ci/browser/test_direct_lifecycle.py -q
uv run pytest tests/ci/browser/test_direct_lifecycle.py tests/ci/browser/test_session_start.py tests/ci/browser/test_direct_storage_state.py -q
uv run pytest tests/ci/test_action_record.py::test_profile_record_video_dir_still_works -q
```

Results:

- Direct lifecycle tests: `7 passed`.
- Direct lifecycle, browser session startup, and direct storage-state suite: `19 passed`.
- Recording finalization test: `1 skipped` because optional recording dependencies are not active in this environment.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse` and the main worktree `.env`:

- `https://example.com` heading task: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.
- Final: `The main heading of the website is Example Domain.`

## Codexification Verification 110

After the final hot-path audit:

```bash
uv run pytest tests/ci/browser/test_direct_lifecycle.py tests/ci/browser/test_direct_navigation.py tests/ci/browser/test_direct_tab_focus.py tests/ci/browser/test_aboutblank_watchdog.py tests/ci/browser/test_direct_storage_state.py -q
uv run pytest tests/ci/browser/test_browser_services.py -q
uv run pytest tests/ci/test_message_manager_typed_context.py tests/ci/test_message_manager_compaction.py tests/ci/test_agent_native_tool_calls.py tests/ci/test_native_tool_router.py -q
```

Results:

- Direct lifecycle/navigation/tab/about:blank/storage hot-path tests: `16 passed`.
- Browser direct-service tests: `15 passed`.
- Message context, compaction, native tool-call, and native router tests: `24 passed`.
- Remaining `event_bus.dispatch(...)` calls are observer notifications, compatibility adapters, or fallback paths rather than the public browser action/lifecycle request path.

## Codexification Verification 102

After extracting state-message rendering out of `MessageManager`:

```bash
uv run pytest tests/ci/test_message_manager_typed_context.py tests/ci/test_message_manager_compaction.py -q
uv run pytest tests/ci/test_agent_native_tool_calls.py -q
uv run pytest tests/ci/security/test_sensitive_data.py -q
uv run pytest tests/ci/test_file_system_llm_integration.py -q
uv run pytest tests/ci/test_agent_planning.py tests/ci/test_budget_warning.py tests/ci/test_action_loop_detection.py -q
uv run ruff check browser_use/agent/message_manager/service.py browser_use/agent/message_manager/state_message.py tests/ci/test_message_manager_typed_context.py
uv run pyright browser_use/agent/message_manager/service.py browser_use/agent/message_manager/state_message.py tests/ci/test_message_manager_typed_context.py
```

Results:

- Message-manager typed-context and compaction tests: `6 passed`.
- Native tool-call agent tests: `2 passed`.
- Sensitive-data tests: `14 passed`.
- File-system LLM integration tests: `11 passed`.
- Planning, budget-warning, and loop-detection tests: `68 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse`:

- Task: go to `https://example.com` and report the main heading.
- Result: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.

## Codexification Verification 106

After directizing tab-close focus recovery:

```bash
uv run pytest tests/ci/browser/test_direct_tab_focus.py -q
uv run pytest tests/ci/browser/test_aboutblank_watchdog.py tests/ci/browser/test_direct_storage_state.py tests/ci/browser/test_direct_tab_focus.py -q
uv run pytest tests/ci/browser/test_session_start.py -q
uv run ruff check browser_use/browser/session_tab_events.py browser_use/browser/services.py tests/ci/browser/test_direct_tab_focus.py
uv run pyright browser_use/browser/session_tab_events.py browser_use/browser/services.py tests/ci/browser/test_direct_tab_focus.py
```

Results:

- Direct tab focus tests: `2 passed`.
- About:blank, storage, and tab direct-call tests: `7 passed`.
- Browser session lifecycle tests: `9 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse`:

- Task: go to `https://example.com` and report the main heading.
- Result: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.

## Codexification Verification 105

After directizing about:blank tab recovery:

```bash
uv run pytest tests/ci/browser/test_aboutblank_watchdog.py tests/ci/browser/test_direct_storage_state.py -q
uv run pytest tests/ci/browser/test_session_start.py -q
uv run ruff check browser_use/browser/watchdogs/aboutblank_watchdog.py tests/ci/browser/test_aboutblank_watchdog.py
uv run pyright browser_use/browser/watchdogs/aboutblank_watchdog.py tests/ci/browser/test_aboutblank_watchdog.py
```

Results:

- About:blank and storage direct-call tests: `4 passed`.
- Browser session lifecycle tests: `9 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse`:

- Task: go to `https://example.com` and report the main heading.
- Result: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.

## Codexification Verification 104

After directizing storage-state load/save on browser lifecycle paths:

```bash
uv run pytest tests/ci/browser/test_direct_storage_state.py -q
uv run pytest tests/ci/browser/test_session_start.py -q
uv run ruff check browser_use/browser/session_lifecycle.py browser_use/browser/watchdogs/storage_state_watchdog.py tests/ci/browser/test_direct_storage_state.py
uv run pyright browser_use/browser/session_lifecycle.py browser_use/browser/watchdogs/storage_state_watchdog.py tests/ci/browser/test_direct_storage_state.py
```

Results:

- Direct storage-state tests: `3 passed`.
- Browser session lifecycle tests: `9 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse`:

- Task: go to `https://example.com` and report the main heading.
- Result: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.
- Final: `The main heading of the page is 'Example Domain'.`

## Codexification Verification 103

After moving the runtime-owned model-context manager out of the legacy message-manager service module:

```bash
uv run pytest tests/ci/test_message_manager_typed_context.py tests/ci/test_message_manager_compaction.py -q
uv run pytest tests/ci/test_agent_native_tool_calls.py -q
uv run pytest tests/ci/security/test_sensitive_data.py -q
uv run pytest tests/ci/test_file_system_llm_integration.py -q
uv run pytest tests/ci/test_agent_planning.py tests/ci/test_budget_warning.py tests/ci/test_action_loop_detection.py -q
uv run ruff check browser_use/agent/service.py browser_use/agent/configuration.py browser_use/agent/planning.py browser_use/agent/runtime/__init__.py browser_use/agent/runtime/model_context.py browser_use/agent/message_manager/service.py
uv run pyright browser_use/agent/service.py browser_use/agent/configuration.py browser_use/agent/planning.py browser_use/agent/runtime/__init__.py browser_use/agent/runtime/model_context.py browser_use/agent/message_manager/service.py
```

Results:

- Message-manager compatibility tests: `6 passed`.
- Native tool-call agent tests: `2 passed`.
- Sensitive-data tests: `14 passed`.
- File-system LLM integration tests: `11 passed`.
- Planning, budget-warning, and loop-detection tests: `68 passed`.
- Ruff: passed.
- Pyright: `0 errors`.

Real Chromium smoke with `ChatBrowserUse`:

- Task: go to `https://example.com` and report the main heading.
- Result: success `True`, done `True`, `3` steps.
- Actions: `['navigate', 'extract', 'done']`.
