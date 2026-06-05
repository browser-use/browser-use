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
   - The SDK stdout reader accepts large JSON-RPC response lines, which are expected
     when normalized history includes screenshots, tool output, and observability data.
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
   - Simple initial navigation actions on existing CDP-backed browser sessions
     now execute once before the Rust SDK run starts. Evals that provision a
     Browser Use Cloud browser therefore hand Rust a browser already focused on
     the task's start URL instead of relying only on a prompt hint from
     `about:blank`.

## Current Proof

- terminal `cargo check -p browser-use-cli`
- terminal `cargo test -p browser-use-cli sdk_ -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_run_runtime_supports_model_transport_blocking_bridge -- --nocapture`
- terminal `cargo test -p browser-use-agent running_browser_script -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_task_executes_fake_backend_with_normalized_history -- --nocapture`
- terminal `cargo test -p browser-use-llm stream_ -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_provider_run_config_maps_browser_use_options_to_rust_core -- --nocapture`
- browser-use `uv run python -m py_compile browser_use/rust/service.py`
- browser-use `uv run pytest tests/ci/test_rust_agent.py::test_rust_history_surfaces_running_browser_script_observe_instruction -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'run_executes_initial_actions_before_sdk or initial_actions_pre_navigate_existing_cdp_session' -q`
- browser-use `uv run pytest tests/ci/test_rust_agent.py`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'sdk_client_reads_large_json_rpc_lines or sdk_and_reuses_session or translates_browser_use_args_to_terminal'`
- browser-use `uv run pytest tests/ci/test_rust_agent.py -k 'sdk_client_queues_agent_notifications_before_response or sdk_client_reads_large_json_rpc_lines or sdk_and_reuses_session or translates_browser_use_args_to_terminal'`
- browser-use process-backed smoke with
  `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal`,
  proving `Agent.run()` calls the real SDK server and `Agent.follow_up()` reuses the
  same SDK session.

## Known Transitional Debt

- `_LegacyProcessSdkClient` exists only to keep older `_run_process` monkeypatch tests
  meaningful while the production path moves to the SDK server. Once evals prove the
  SDK path and tests are rewritten around the protocol, the old CLI argv/load-events
  glue should be removed and `browser_use/rust/service.py` should become much shorter.
