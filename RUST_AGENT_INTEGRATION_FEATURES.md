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
     model stream path as a stream-idle timeout, so a provider response that opens
     and then sends no SSE bytes becomes a retryable transport error instead of
     holding a GitHub eval runner indefinitely after `model.turn.request`.

## Current Proof

- terminal `cargo check -p browser-use-cli`
- terminal `cargo test -p browser-use-cli sdk_ -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_task_executes_fake_backend_with_normalized_history -- --nocapture`
- terminal `cargo test -p browser-use-llm stream_idle_timeout_yields_retryable_transport_error -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_provider_run_config_maps_browser_use_options_to_rust_core -- --nocapture`
- browser-use `uv run python -m py_compile browser_use/rust/service.py`
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
