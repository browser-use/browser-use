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
   - Terminal Rust SDK runs no longer advertise subagent tools unless the run
     has a configured child-agent runner. This prevents eval tasks from spending
     model turns on `spawn_agent` calls that can only fail with "subagents are
     not configured" in the SDK/CDP eval path.
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
- evaluations-internal `uv run python -m py_compile eval/service.py`
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
