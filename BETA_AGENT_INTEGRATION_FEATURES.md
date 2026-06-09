# Rust Agent Integration Feature/Proof Ledger

This branch keeps the Python `Agent` unchanged unless callers explicitly import
`from browser_use.beta import Agent`.

## Current Features

1. Rust SDK server execution path
   - `browser_use.beta.Agent` now runs normal tasks through the terminal SDK server
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
     sub-agent system in `browser_use.beta.Agent` evals without exposing
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
   - Browser-use Rust SDK notification recovery now accepts both top-level
     `event_type` records and nested SDK event envelopes. Runs that visibly emit
     `session.done` in GitHub runner progress logs therefore reconstruct the
     final answer even if the final JSON-RPC history response is empty or
     compacted differently.
   - Browser-use Rust SDK notification recovery now normalizes both
     `agent.event` and `agent.projected_event` notifications into the retained
     event history. Runs whose progress logs show projected `session.done` or
     `agent.completed` events therefore no longer fall back to
     "Rust terminal session did not produce a final result."
   - Browser-use Rust SDK history reconstruction now prefers retained live
     notifications when the final JSON-RPC response history is present but lacks
     a final result. Stale response-side compaction errors no longer override a
     `session.done` event that Python already observed from the stream.
   - Browser-use Rust SDK billing reconstruction now falls back to the SDK
     response's aggregate `history.usage` when compacted histories omit usage
     events. This keeps dashboard usage nonzero even when the event payload is
     compacted before it reaches Python.
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
   - `browser_use.beta.Agent` no longer treats `_run_process` monkeypatches as an
     alternate runtime. Production `run()` and `follow_up()` now require the
     Rust SDK server path, so the legacy terminal CLI adapter cannot silently
     replace the new server protocol while the normal Python `browser_use.Agent`
     remains unchanged.
   - Terminal SDK browser requests now preserve and forward additional
     Browser Use-style browser settings: proxy country, local profile label,
     allowed/blocked domains, window size, and state directory. For cloud
     browser runs, proxy country is passed to `browser remote start`, so Rust
     SDK sessions can use Browser Use Cloud browser proxies through the same
     Python-facing `browser_profile`/`browser_session` options.
   - Browser-use now deduplicates SDK response/projected events before
     reconstructing history and usage. Duplicate `token_count` and
     `session.done` records no longer inflate eval history, dashboard usage, or
     telemetry payloads when the terminal server returns both live and projected
     event streams.
   - Browser-use no longer sends a Rust SDK `tool_allowlist` override. The
     terminal SDK server now owns its tool registry for `browser_use.beta.Agent`
     runs, so local search, web/search helpers, and v2 sub-agent controls are
     available in evals when the Rust core registers them.
   - Reconstructed browser history ignores internal browser-control endpoint
     URLs such as `http://127.0.0.1:<port>` while still preserving genuine local
     page URLs. Eval traces therefore show user-visible pages instead of CDP
     helper endpoints.
   - The Rust Agent default LLM resolution follows the normal browser-use path:
     explicit `DEFAULT_LLM` wins, otherwise `ChatBrowserUse()` is used. Real
     eval runs still pass Claude Sonnet 4.6 explicitly through the SDK request.
   - Terminal `http_get_many(...)` and `browser_fetch(..., return_error=True)`
     now return recoverable error records that are both dict-compatible and
     response-compatible (`.status_code`, `.status`, `.headers`, `.text`,
     `.content`, `.url`). General browser-script code can inspect a failed
     helper response without crashing the whole step with
     `AttributeError: 'dict' object has no attribute 'status_code'`.
   - Terminal `js(...)` in `browser_script` now tolerates common anonymous
     function snippets and async function-IIFE snippets emitted by agents. This
     avoids repeated generic JavaScript syntax failures such as
     `Function statements require a function name` and `await is only valid in
     async functions` without adding task- or domain-specific behavior.
   - Terminal SDK `agent.create` now persists the initial task input only through
     the runtime observed-event path. SDK LLM prompts and Laminar spans therefore
     contain the task once instead of duplicating the same initial user message,
     which improves trace fidelity and reduces avoidable prompt/cache churn.

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
- browser-use `uv run python -m py_compile browser_use/beta/service.py`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -k 'browser_script_lifecycle_outputs_as_result or initial_actions_pre_navigate_existing_cdp_session or run_hands_off_completed_initial_navigation_as_context' -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -k 'printed_browser_script_page_info_as_state or browser_script_lifecycle_outputs_as_result or initial_actions_pre_navigate_existing_cdp_session or run_hands_off_completed_initial_navigation_as_context' -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_rust_history_surfaces_running_browser_script_observe_instruction -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -k 'initial_actions_pre_navigate_existing_cdp_session or run_executes_initial_actions_before_sdk or run_hands_off_completed_initial_navigation_as_context' -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -k 'sdk_client_reads_large_json_rpc_lines or sdk_and_reuses_session or translates_browser_use_args_to_terminal'`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -k 'sdk_client_queues_agent_notifications_before_response or sdk_client_reads_large_json_rpc_lines or sdk_and_reuses_session or translates_browser_use_args_to_terminal'`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -k 'rust_sdk_client_reads_large_json_rpc_lines or rust_sdk_client_queues_agent_notifications_before_response' -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_rust_sdk_client_reads_large_json_rpc_lines tests/ci/test_beta_agent.py::test_beta_agent_run_leaves_initial_navigation_for_sdk_by_default tests/ci/test_beta_agent.py::test_beta_agent_initial_actions_can_pre_navigate_existing_cdp_session tests/ci/test_beta_agent.py::test_beta_agent_translates_browser_use_args_to_terminal -q`
- browser-use `PYTHONPATH=. uv run pytest tests/ci/test_beta_agent.py -q -k 'pre_navigates_cdp_session_before_sdk_by_default or initial_actions_can_pre_navigate_existing_cdp_session or direct_initial_navigation_defaults_on_for_cdp or direct_initial_navigation_can_be_disabled'`
- browser-use `uv run pytest -q tests/ci/test_beta_agent.py -k "pre_navigates_cdp_session_before_sdk_by_default or keeps_initial_navigation_when_direct_state_mismatches or initial_actions_can_pre_navigate_existing_cdp_session or direct_initial_navigation_defaults_on_for_cdp"`
- browser-use `uv run pytest -q tests/ci/test_beta_agent.py -k "terminal_token_count_usage or sums_token_count_last_usage_when_latest_total_underreports or terminal_usage_prices_token_count_events or terminal_usage_sums_token_count_cache_creation"`
- browser-use `uv run pytest -q tests/ci/test_beta_agent.py -k "terminal_nested_model_usage or token_count_does_not_shrink_model_usage_totals or terminal_usage_prices_token_count_events or terminal_usage_prices_anthropic_raw_cache_reads or terminal_usage_sums_token_count_cache_creation or priced_summary_sums_cache_read_tokens or mixed_events_do_not_shrink_totals or priced_usage_prefers_model_usage_over_token_count or sums_token_count_last_usage_when_latest_total_underreports"`
- browser-use `python -m py_compile browser_use/beta/service.py`
- terminal `cargo test -p browser-use-cli sdk_transport -- --nocapture`
- terminal `cargo test -p browser-use-providers server_overloaded -- --nocapture`
- terminal `cargo test -p browser-use-agent observe_timeout -- --nocapture`
- terminal `cargo test -p browser-use-agent observe_routes_to_observe_script -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_ -- --nocapture`
- terminal `cargo test -p browser-use-agent subagent_tools_are_registered_in_the_dispatcher -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_run_attaches_child_agent_runner_to_provider_config -- --nocapture`
- terminal `cargo test -p browser-use-agent search -- --nocapture`
- terminal `cargo test -p browser-use-agent dispatcher -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_returns_child_usage_events_separately -- --nocapture`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_prices_sdk_child_usage_events_without_overriding_parent_result -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_runs_through_sdk_and_reuses_session_for_followup tests/ci/test_beta_agent.py::test_beta_agent_recovers_final_result_from_sdk_notifications_after_transport_error tests/ci/test_beta_agent.py::test_beta_agent_preserves_sdk_notification_history_on_cancel -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_recovers_final_result_from_sdk_notifications_after_transport_error tests/ci/test_beta_agent.py::test_beta_agent_recovers_nested_sdk_notification_events tests/ci/test_beta_agent.py::test_beta_agent_prices_sdk_child_usage_events_without_overriding_parent_result -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_recovers_nested_sdk_notification_events tests/ci/test_beta_agent.py::test_beta_agent_prefers_notification_final_when_response_history_lacks_result tests/ci/test_beta_agent.py::test_beta_agent_uses_sdk_history_usage_when_events_do_not_include_usage tests/ci/test_beta_agent.py::test_beta_agent_prices_sdk_child_usage_events_without_overriding_parent_result -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_recovers_final_result_from_sdk_notifications_after_transport_error tests/ci/test_beta_agent.py::test_beta_agent_recovers_nested_sdk_notification_events tests/ci/test_beta_agent.py::test_beta_agent_recovers_projected_sdk_final_events tests/ci/test_beta_agent.py::test_beta_agent_prefers_notification_final_when_response_history_lacks_result tests/ci/test_beta_agent.py::test_beta_agent_uses_sdk_history_usage_when_events_do_not_include_usage tests/ci/test_beta_agent.py::test_beta_agent_prices_sdk_child_usage_events_without_overriding_parent_result -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_runs_through_sdk_and_reuses_session_for_followup -q`
- terminal `cargo fmt --check`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_browser_create_preserves_browser_use_settings -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_provider_run_config_maps_browser_use_options_to_rust_core -- --nocapture`
- terminal `cargo test -p browser-use-agent stored_cloud_profile_uses_sdk_proxy_country_env_when_connecting -- --nocapture`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_sdk_browser_payload_includes_profile_domains_window_and_proxy -q`
- browser-use `uv run python -m py_compile browser_use/beta/service.py`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_rust_sdk_event_dedupe_removes_projected_usage_duplicates tests/ci/test_beta_agent.py::test_rust_history_ignores_internal_browser_connection_url tests/ci/test_beta_agent.py::test_beta_agent_default_llm_matches_browser_use_default tests/ci/test_beta_agent.py::test_beta_agent_default_llm_respects_default_llm_env tests/ci/test_beta_agent.py::test_beta_agent_exposes_logging_helper_methods tests/ci/test_beta_agent.py::test_beta_agent_telemetry_filters_empty_reconstructed_urls -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py::test_beta_agent_translates_browser_use_args_to_terminal tests/ci/test_beta_agent.py::test_beta_agent_sdk_params_leave_terminal_tools_unrestricted -q`
- browser-use `uv run pytest tests/ci/test_beta_agent.py -q`
- browser-use `uv run ruff check browser_use/beta/service.py tests/ci/test_beta_agent.py tests/ci/models/test_llm_model_factory.py`
- terminal `cargo test -p browser-use-browser browser_script_http_get_many_preserves_order_and_errors -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_browser_fetch_single_returns_structured_errors_by_default -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_js_accepts_anonymous_function_snippets -- --nocapture`
- terminal `cargo test -p browser-use-browser browser_script_js_asyncifies_parenthesized_function_iife_with_await -- --nocapture`
- terminal `cargo fmt --check`
- terminal `cargo test -p browser-use-cli sdk_run_attaches_child_agent_runner_to_provider_config -- --nocapture`
- terminal `cargo test -p browser-use-agent subagent_tools_are_registered_in_the_dispatcher -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_executes_fake_backend -- --nocapture`
- terminal `cargo test -p browser-use-cli sdk_json_rpc_agent_run_task_executes_fake_backend_with_normalized_history -- --nocapture`
- evaluations-internal `uv run python -m py_compile eval/service.py`
- evaluations-internal `python -m py_compile eval/task_types.py`
- evaluations-internal `PYTHONPATH=. uv run pytest tests/test_service_cli.py -q -k 'usage_aliases or trims_oversized_history_fields or rust_eval_uses_adapter_initial_navigation_default or rust_eval_preserves_explicit_direct_initial_navigation_override'`
- evaluations-internal `PYTHONPATH=. uv run pytest -q tests/test_service_cli.py -k "synthesizes_partial_result_on_timeout or synthesizes_partial_result_without_timeout_marker or server_payload_includes_failure_final_response_without_history"`
- evaluations-internal `PYTHONPATH="$PWD" uv run pytest tests/test_service_cli.py::test_progress_updates_tolerate_transient_failures_by_default tests/test_service_cli.py::test_run_stage_with_progress_heartbeat_refreshes_active_stage -q`
- browser-use process-backed smoke with
  `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal`,
  proving `Agent.run()` calls the real SDK server and `Agent.follow_up()` reuses the
  same SDK session.
- real_v8 5-task eval smoke `kh721gr6v248emmdw9kn4mf645882qdk` on
  browser-use `ad74b9f23da5c3ec1773b57dce856df9467777c5` and terminal
  `b59372cc03b574e1bb82d9ad814ebb6c2d79bd1c`: 5/5 completed, scores
  80/90/100/100/100 with Agent SDK judge and Browser Use Cloud CDP browser.
- real_v8 50-task eval `kh7749jfyd5x54n5wzt4cqezmh883tgp` on the same
  browser-use SHA and terminal `b59372cc03b574e1bb82d9ad814ebb6c2d79bd1c`
  completed all 50 task rows but scored below target; repeated low-output
  rows exposed the terminal fetch error-record compatibility issue fixed by
  terminal `5382d8b`.
- real_v8 50-task eval `kh7530fhjr52h81b0fvx7fhem5882ty1` on browser-use
  `7bcf9754f103a1bb6c2e6d031940a162bb4adfbe` and terminal
  `5382d8b7ccc72c102fbeb2b68940177e5371d753` was still running when
  inspected, with 38/50 rows saved, no empty final responses in fetched full
  histories, no access-denied count, and repeated recoverable browser-script JS
  syntax errors that motivated terminal `aa3f3ea`.
- final real_v8 50-task eval `kh7br0crtahkq408f9dw41z901883qy5` was
  dispatched on browser-use `7bcf9754f103a1bb6c2e6d031940a162bb4adfbe` and
  terminal `aa3f3ea78d45564ea0e5f5443e4f13145e5ca9a5` with Browser Use Cloud
  CDP browser and Agent SDK judge. It completed all 50 rows with Agent SDK
  judging, averaged 78.5, saved partial final responses for the six timeboxed
  zero-score rows, and is tagged as `eval/kh7br-real-v8-50-78p50` in both
  browser-use and terminal.
- real_v8 50-task eval `kh7880wm0ffgsyqkwzfwn9hc7s882mff` was dispatched on
  browser-use `5c40474473a61651f25cd2d084aa1fc278c5c714` and terminal
  `640e052ca5f8e8654069a414814ac2f061861ce2` with Browser Use Cloud CDP
  browser, no `--proxyless` flag, a 30 minute task/agent timebox, and Agent SDK
  judge. GitHub runner logs show `--browser browser-use-cloud`, Browser Use
  Cloud session creation, and Rust `browser_mode=remote-cdp`. When inspected,
  49 scored rows averaged 76.29 while one placeholder row was rerunning; low
  rows mostly had partial final responses after 30 minute cancellations rather
  than missing branch/CDP/judge/Laminar infrastructure.
- Laminar trace inspection for `kh7880wm0ffgsyqkwzfwn9hc7s882mff` confirmed
  main-agent `rust_core.llm` spans, browser tool spans, usage attributes, and a
  duplicated initial task user message. Terminal `06627d9` fixes the duplicated
  `session.input` persistence and the focused SDK JSON-RPC tests above prove
  the initial task input is now stored exactly once for both `agent.run` and
  `agent.run_task`.

## Known Transitional Debt

- The production Rust path no longer uses `_run_process`/`_load_events`, legacy
  process-backed SDK adapter code, or direct CLI `run-*` command construction.
  The production wrapper now goes through the SDK server protocol.
