# Rust Agent Integration Feature/Proof Ledger

This branch keeps the Python `Agent` unchanged unless callers explicitly import
`from browser_use.rust import Agent`.

## Current Features

1. Rust SDK server execution path
   - `browser_use.rust.Agent` now runs normal tasks through the terminal SDK server
     (`browser-use-terminal sdk-server --transport stdio`) using the normalized
     `agent.run_task` request/response protocol.
   - Follow-up tasks reuse the returned SDK `agent_id`, `session_id`, and `browser_id`
     through `agent.run`, so the Python-facing interface can keep one Rust-owned session.
   - Browser-use-style options are mapped into SDK params, including model/provider,
     CDP URL/headers, viewport, user agent, storage state, downloads path, structured
     output schema, max steps, vision, cost calculation, and action limits.
   - The returned normalized event history is reconstructed into Browser Use-compatible
     `AgentHistoryList`, callbacks, usage, telemetry, Laminar replay, downloads, and
     final result handling.
   - The SDK stdout reader accepts large JSON-RPC response lines by reading stdout in
     chunks and splitting newline-delimited JSON-RPC manually. This avoids asyncio's
     separator-limit failure when normalized history includes screenshots, tool
     output, and observability data in a single response line.
   - SDK server `agent.event` / `agent.projected_event` notifications are retained and
     surfaced as concise in-flight progress logs, so GitHub-runner evals can show where
     a Rust-backed run is spending time before the final history response arrives.
   - Terminal SDK `agent.run` now mirrors the live executor by passing the latest durable
     task/follow-up input into `RuntimeHandle::run_agent` as `initial_input`, so SDK
     `agent.run_task` enters the runtime-owned loop with `agent.input.accepted` and
     `agent.input.consumed` events instead of stalling after browser creation.
   - Browser-use `llm_timeout`/SDK `llm.timeout` now reaches the terminal Rust
     model stream path as both a response-open timeout and a stream-idle timeout,
     so a provider request that never returns response headers, or a stream that
     opens and then sends no SSE bytes, becomes a retryable transport error instead
     of holding a GitHub eval runner indefinitely after `model.turn.request`.
   - Terminal SDK `agent.run_task` now drives the runtime on a multi-thread Tokio
     runtime, matching the live model transport bridge's `block_in_place` usage.
     This prevents SDK evals from stalling after `model.turn.request` before the
     configured response-open/stream-idle timeout can make progress.
   - Running `browser_script` calls now preserve the `run_id` and observe
     instruction in Rust event persistence, replay reconstruction, and Python
     `AgentHistoryList` reconstruction. This prevents eval traces from showing
     empty browser tool results while a script is still active and keeps the
     next model turn on the intended observe/cancel path instead of repeatedly
     navigating or reconnecting.
   - Simple initial navigation actions on CDP-backed Rust runs are now left for
     the Rust SDK by default, so the first navigation is a model-visible
     `browser_script` action with terminal page-state output instead of a hidden
     Python-side BrowserSession preload. The old direct CDP preload remains
     available behind `BROWSER_USE_RUST_DIRECT_INITIAL_NAVIGATION=1`.
   - Structured `browser_script` lifecycle events now preserve outputs, summaries,
     images, and browser state through terminal event persistence and Python
     history reconstruction. This prevents the first post-navigation page probe
     from appearing blank in eval/Laminar history when the script emitted only
     `emit_output(...)` or screenshots and no stdout text.
   - Printed `browser_script` page probes are also used to reconstruct browser
     state when they contain `page_info()` dictionaries, `list_tabs()` rows, or
     a bare URL. This keeps `Page State` aligned with visible tool output even
     when the script used `print(info)` instead of `emit_output(info, ...)`.
   - Terminal `list_tabs()` hides the internal `Starting agent ...` about:blank
     placeholder tab. This prevents the model from mistaking the startup tab
     for a user-relevant target and spending turns on unnecessary
     reconnect/reattach recovery after a successful navigation.
   - Terminal Rust runs only advertise sub-agent tools when the run has a
     configured child-agent runner, and SDK JSON-RPC runs now attach the same
     runtime-backed child runner as CLI runs. This enables terminal's advanced
     sub-agent system in `browser_use.rust.Agent` evals without exposing
     spawn tools on unsupported run surfaces.
   - Eval GitHub runners now refresh Convex progress during long `run_agent`
     and `evaluate` stages, so slow Rust or Agent SDK judge calls stay visible
     instead of looking stale while they are still legitimately running.
   - Terminal provider conversion now downsamples oversized data-URL screenshots
     before Anthropic requests. This keeps visual context in the model input
     while avoiding Claude's many-image 2000px dimension rejection, which was
     causing completed eval tasks to show a one-step HTTP 400 error and an
     empty final result.
   - Terminal direct Anthropic Messages serialization now also downsamples
     oversized inline `ContentPart::Media` base64 screenshots before request
     construction. This covers Rust live-model transports that bypass provider
     JSON normalization and previously still hit the same 2000px many-image
     rejection.
   - Terminal navigation helpers now wait briefly for page readiness and return
     `navigation_ready` plus `page_info` in the same `browser_script` result.
     This gives the next model turn concrete evidence that navigation landed,
     instead of a bare "navigation sent" placeholder that can lead to repeated
     navigate/status/recover loops on Cloud Browser CDP sessions.
  - Terminal `browser_script observe` now waits through the requested observe
    window instead of returning on the first partial stream event. If a
    navigation or extraction script emits partial page events and then finishes
    shortly after, the model receives the final result in the same tool call
    rather than spending extra LLM turns polling the same `run_id`.
  - Terminal `browser_script` start now auto-collects a previous active run
    that has already finished or timed out. If the model starts another browser
    action immediately after navigation completed in the background, the tool
    returns the completed navigation/page result in that same call instead of
    forcing a separate observe/status/recover turn.
  - Terminal remote-CDP attach now reuses an existing ordinary blank page target
    before creating a new `about:blank` tab. Browser Use Cloud sessions therefore
    begin with one stable controlled tab instead of splitting Python setup and
    Rust execution across separate blank targets.
  - Eval payloads preserve Rust/browser-use usage fields and add dashboard
    aliases (`input_tokens`, `output_tokens`, cached/cache-creation tokens, and
    `cost_usd`) before saving. This keeps cost/token displays working for Rust
    histories without changing the canonical browser-use usage structure.
   - Browser-use Rust CDP initial navigation now waits for a concrete
     post-navigation browser state summary and passes the observed current
     URL/title into the Rust task context. Start-URL tasks should begin by
     inspecting or extracting from the already-loaded page instead of spending
     early turns on repeated navigation/status recovery.
   - Browser-use Rust direct CDP pre-navigation now only records an initial
     navigation as completed when the observed browser state matches the
     requested URL. If the Cloud Browser remains on `about:blank` or another
     mismatched target, the original navigation stays in the Rust task context
     instead of giving the model a false "already loaded" state.
   - Eval GitHub runners now preserve visible output for interrupted Rust runs:
     if an agent is cancelled or errors after collecting history, formatting
     synthesizes a partial final answer from the latest memory/tool evidence;
     if no history exists, the saved dashboard payload still includes a
     non-empty failure response with the stage error.
   - Rust `token_count` usage reconstruction now treats summed per-turn
     `last_token_usage` as the billed usage source when it exceeds the latest
     cumulative context counters. Dashboard usage therefore reflects the whole
     agent run instead of only the latest context-sized prompt after
     recompute/compaction paths.
   - Rust cost-enabled usage reconstruction now reports token totals from the
     same summed per-turn usage entries used to calculate costs. This keeps
     dashboard token counts, cached/cache-creation buckets, and cost fields on
     one basis instead of showing summed cost beside latest-context token
     counters.
   - Rust cost-enabled usage reconstruction now treats `token_count` as a
     fallback billing source when provider `model.usage` events are absent.
     Mixed streams therefore do not double-count usage by pricing both provider
     usage and context occupancy counters.
   - Terminal SDK JSON-RPC responses are now bounded before they are written to
     stdio. Oversized final histories compact durable event payloads while
     preserving final output, success state, errors, usage, files, and recent
     events, so a completed run cannot lose its final answer because the Python
     wrapper hits its newline-delimited frame limit.
   - Browser-use Rust SDK runs now prefer live `agent.event` notifications when
     the final SDK response is missing, truncated, or smaller than the already
     observed stream. If a run is cancelled or the final transport fails after
     `session.done`, Python reconstructs `AgentHistoryList`, usage, and final
     output from the notification stream instead of returning an empty result.
   - Terminal provider overload errors are treated as retryable transient
     capacity failures. This prevents a single Claude/OpenAI `server overloaded`
     response from becoming an immediate no-output eval failure.
   - Terminal `browser_script observe` now defaults to a coarse 30 second wait,
     clamps too-small observe requests up to that window, and allows waits up to
     120 seconds. Long navigation/extraction scripts therefore spend fewer model
     turns polling the same `run_id` and are less likely to hit the step limit
     before finalizing partial evidence.
   - Terminal now includes a locally executed DuckDuckGo Lite `search` tool from
     the terminal web-search merge. URL-finding and general web-search tasks can
     discover candidate pages without spending browser-navigation turns on search
     engine result pages.
   - Terminal SDK histories now return child-agent events separately from parent
     events and expose a combined `usage_events` stream. Browser-use prices and
     traces against that combined stream, so sub-agent model calls contribute to
     run token/cost totals without letting child `session.done` events override
     the parent final answer.

## Current Proof

- terminal `cargo check -p browser-use-cli`
- terminal `cargo test -p browser-use-cli sdk_ -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_run_runtime_supports_model_transport_blocking_bridge -- --nocapture`
- terminal `cargo test -p browser-use-agent running_browser_script -- --nocapture`
- terminal `cargo test -p browser-use-agent runtime_browser_backend_records_script_lifecycle -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_list_tabs_hides_agent_startup_placeholder -- --nocapture`
- terminal `cargo test -p browser-use-agent subagent_tools -- --nocapture`
- terminal `cargo test -p browser-use-agent spawn_agent_agent_type_guidance_discourages_default_override -- --nocapture`
- terminal `cargo test -p browser-use-providers anthropic_messages_downsamples_oversized_tool_images -- --nocapture`
- terminal `cargo test -p browser-use-providers anthropic_messages -- --nocapture`
- terminal `cargo test -p browser-use-llm build_body_downsamples_oversized_inline_media_for_anthropic -- --nocapture`
- terminal `cargo test -p browser-use-llm anthropic_messages -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_navigation_helpers_wait_for_page_state -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_start_observe_finishes_slow_scripts -- --test-threads=1 --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_observe_waits_for_completion_after_partial_output --lib`
- terminal `cargo test -p browser-use-browser browser_script_observe --lib`
- terminal `cargo test -p browser-use-browser browser_script_start_observe_finishes_slow_scripts --lib`
- terminal `cargo test -p browser-use-browser browser_script_start_ -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_observe_is_idempotent_after_completion -- --nocapture`
- terminal `cargo test -p browser-use-browser remote_cdp_attach_reuses_existing_blank_page_before_creating_target -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_task_executes_fake_backend_with_normalized_history -- --nocapture`
- terminal `cargo test -p browser-use-llm stream_ -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_provider_run_config_maps_browser_use_options_to_rust_core -- --nocapture`
- browser-use `uv run python -m py_compile browser_use/rust/service.py`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'browser_script_lifecycle_outputs_as_result or initial_actions_pre_navigate_existing_cdp_session or run_hands_off_completed_initial_navigation_as_context' -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'printed_browser_script_page_info_as_state or browser_script_lifecycle_outputs_as_result or initial_actions_pre_navigate_existing_cdp_session or run_hands_off_completed_initial_navigation_as_context' -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py::test_rust_history_surfaces_running_browser_script_observe_instruction -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'initial_actions_pre_navigate_existing_cdp_session or run_executes_initial_actions_before_sdk or run_hands_off_completed_initial_navigation_as_context' -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'sdk_client_reads_large_json_rpc_lines or sdk_and_reuses_session or translates_browser_use_args_to_terminal'`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'sdk_client_queues_agent_notifications_before_response or sdk_client_reads_large_json_rpc_lines or sdk_and_reuses_session or translates_browser_use_args_to_terminal'`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'rust_sdk_client_reads_large_json_rpc_lines or rust_sdk_client_queues_agent_notifications_before_response' -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py::test_rust_sdk_client_reads_large_json_rpc_lines tests/ci/test_rust_agent.py::test_rust_agent_run_leaves_initial_navigation_for_sdk_by_default tests/ci/test_rust_agent.py::test_rust_agent_initial_actions_can_pre_navigate_existing_cdp_session tests/ci/test_rust_agent.py::test_rust_agent_translates_browser_use_args_to_terminal -q`
- browser-use `PYTHONPATH=. uv run pytest tests/ci/test_rust_agent.py -q -k 'pre_navigates_cdp_session_before_sdk_by_default or initial_actions_can_pre_navigate_existing_cdp_session or direct_initial_navigation_defaults_on_for_cdp or direct_initial_navigation_can_be_disabled'`
- browser-use `uv run pytest -q tests/ci/test_rust_agent.py -k "pre_navigates_cdp_session_before_sdk_by_default or keeps_initial_navigation_when_direct_state_mismatches or initial_actions_can_pre_navigate_existing_cdp_session or direct_initial_navigation_defaults_on_for_cdp"`
- browser-use `uv run pytest -q tests/ci/test_rust_agent.py -k "terminal_token_count_usage or sums_token_count_last_usage_when_latest_total_underreports or terminal_usage_prices_token_count_events or terminal_usage_sums_token_count_cache_creation"`
- browser-use `uv run pytest -q tests/ci/test_rust_agent.py -k "terminal_nested_model_usage or token_count_does_not_shrink_model_usage_totals or terminal_usage_prices_token_count_events or terminal_usage_prices_anthropic_raw_cache_reads or terminal_usage_sums_token_count_cache_creation or priced_summary_sums_cache_read_tokens or mixed_events_do_not_shrink_totals or priced_usage_prefers_model_usage_over_token_count or sums_token_count_last_usage_when_latest_total_underreports"`
- browser-use `python -m py_compile browser_use/rust/service.py`
- terminal `cargo test -p browser-use-cli sdk_transport -- --nocapture`
- terminal `cargo test -p browser-use-providers server_overloaded -- --nocapture`
- terminal `cargo test -p browser-use-agent observe_timeout -- --nocapture`
- terminal `cargo test -p browser-use-agent observe_routes_to_observe_script -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_ -- --nocapture`
- terminal `cargo test -p browser-use-agent subagent_tools_are_registered_in_the_dispatcher -- --nocapture`
- terminal `cargo test -p browser-use-agent search -- --nocapture`
- terminal `cargo test -p browser-use-agent dispatcher -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_returns_child_usage_events_separately -- --nocapture`
- browser-use `uv run pytest tests/ci/test_rust_agent.py::test_rust_agent_prices_sdk_child_usage_events_without_overriding_parent_result -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py::test_rust_agent_runs_through_sdk_and_reuses_session_for_followup tests/ci/test_rust_agent.py::test_rust_agent_recovers_final_result_from_sdk_notifications_after_transport_error tests/ci/test_rust_agent.py::test_rust_agent_preserves_sdk_notification_history_on_cancel -q`
- evaluations-internal `uv run python -m py_compile eval/service.py`
- evaluations-internal `python -m py_compile eval/task_types.py`
- evaluations-internal `PYTHONPATH=. uv run pytest tests/test_service_cli.py -q -k 'usage_aliases or trims_oversized_history_fields or rust_eval_uses_adapter_initial_navigation_default or rust_eval_preserves_explicit_direct_initial_navigation_override'`
- evaluations-internal `PYTHONPATH=. uv run pytest -q tests/test_service_cli.py -k "synthesizes_partial_result_on_timeout or synthesizes_partial_result_without_timeout_marker or server_payload_includes_failure_final_response_without_history"`
- evaluations-internal `PYTHONPATH="$PWD" uv run pytest tests/test_service_cli.py::test_progress_updates_tolerate_transient_failures_by_default tests/test_service_cli.py::test_run_stage_with_progress_heartbeat_refreshes_active_stage -q`
- browser-use process-backed smoke with
  `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal`,
  proving `Agent.run()` calls the real SDK server and `Agent.follow_up()` reuses the
  same SDK session.

## Known Transitional Debt

- `_LegacyProcessSdkClient` exists only to keep older `_run_process` monkeypatch tests
  meaningful while the production path moves to the SDK server. Once evals prove the
  SDK path and tests are rewritten around the protocol, the old CLI argv/load-events
  glue should be removed and `browser_use/rust/service.py` should become much shorter.
