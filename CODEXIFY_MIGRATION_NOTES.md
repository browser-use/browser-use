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
- Browser session lifecycle entrypoints and event-handler registration now live in `browser_use.browser.session_lifecycle`.
- Browser navigation event handling and lifecycle readiness waiting now live in `browser_use.browser.session_navigation`.
- Browser hot-path actions route through direct services where parity has been established, while event-bus/watchdog compatibility remains for behavior that has not been safely removed yet.
- The typed runtime/context/event structures are present behind compatibility paths; the old message manager still exists as the public-compatible renderer and state holder.

## Migration Guidance

- Existing users should not need code changes for normal `Agent(task=..., llm=...)` usage.
- New code can use `Agent.from_config(task, llm=..., config=AgentConfig(...))` to avoid the large legacy constructor surface.
- `Agent.from_config(..., **overrides)` accepts the same names as legacy `Agent(...)` keyword arguments; explicit overrides win over values in `AgentConfig`.
- Users who want provider-native tool calls can opt in with `use_native_tool_calls=True`; old model-output parsing remains available.
- Custom tools should continue returning structured `ActionResult` data where possible.
- New internal changes should prefer adding focused modules or services rather than growing `agent/service.py`, `tools/service.py`, or `browser/session.py`.

## Known Remaining Work

- The legacy `Agent(...)` constructor is still broad for backwards compatibility, but new code has a grouped `AgentConfig` path.
- The old message manager is still part of the compatibility path.
- The old structured-output action protocol is still supported and has not been removed.
- Watchdog/event-bus code still exists for browser compatibility paths.
- Google judge-based task evals could not complete because the `GOOGLE_API_KEY` in the shared `.env` is expired.
- External local CDP validation requires launching Chrome with `--remote-allow-origins=*`; with that flag, `Browser(cdp_url=...)` connected and navigated successfully.
