# Rust Agent Integration Features

Branch: `magnus/browser-use-rust-core-integration`

Terminal core branch: `magnus/browser-use-rust-integration` at latest pulled main plus small CLI/browser-mode support commits.

## Built Features

1. Rust-backed Browser Use Agent wrapper
   - `from browser_use import Agent` now resolves to `browser_use.rust.Agent`.
   - The wrapper accepts common Browser Use constructor arguments, runs `browser-use-terminal run-codex`, reloads terminal JSON events, and returns a real `AgentHistoryList`.
   - Proof: `uv run pytest -q tests/ci/test_rust_agent.py` passes.

2. Browser Use result compatibility
   - Returned histories support `final_result()`, `is_done()`, `is_successful()`, `errors()`, `urls()`, `usage`, and `structured_output`.
   - Missing terminal results are surfaced as errors instead of silent empty successes.
   - Proof: `test_rust_events_reconstruct_browser_use_history`, `test_rust_history_supports_structured_output`, and `test_rust_history_marks_missing_terminal_result_as_error`.

3. Existing-session follow-up
   - `Agent.follow_up()` appends a follow-up turn and reruns the same terminal session through `run-codex-session`.
   - Terminal core support was added in the terminal repo as `run-codex-session`.
   - Proof: `test_rust_agent_translates_followup_to_existing_terminal_session`; terminal build `cargo build -q -p browser-use-cli` passes.

4. Browser mode bridge
   - The wrapper sets `LLM_BROWSER_BROWSER_MODE` so terminal browser selection follows Browser Use wrapper settings.
   - `BrowserSession(cdp_url=...)` selects `remote-cdp` and forwards `BU_CDP_URL`.
   - `BrowserProfile(cdp_url=...)` also selects `remote-cdp` and forwards `BU_CDP_URL`.
   - Proof: `test_rust_agent_translates_browser_use_args_to_terminal` and `test_rust_agent_translates_browser_profile_cdp_url`.

5. Remote CDP terminal mode
   - Terminal browser handling now accepts locked `remote-cdp` mode instead of rejecting `browser connect remote-cdp`.
   - Proof: `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent selected_remote_cdp_mode_allows_remote_cdp_connect -- --nocapture`.

6. Smoke example
   - `examples/rust_agent/basic.py` runs a Rust-backed Agent through the Browser Use-style API.
   - It accepts `BU_CDP_URL` or `BROWSER_USE_CDP_URL` for external CDP attachment.
   - Proof: managed-headless smoke returned `Example Domain` for `https://example.com`.
   - Proof: remote-CDP smoke against an externally launched Chromium DevTools endpoint returned `Example Domain`.

7. real_v8 smoke runner
   - `examples/rust_agent/real_v8_smoke.py` loads `terminal/datasets/real_v8.json`, selects one benchmark case by zero-based index or `task_id`, and runs it through the same Rust-backed `Agent` API.
   - It accepts `BU_CDP_URL` or `BROWSER_USE_CDP_URL` so the same script can target a Browser Use cloud browser CDP endpoint when credentials are available.
   - Proof: `test_real_v8_smoke_selects_case_by_index_and_task_id`.
   - Proof: remote-CDP e2e smoke on real_v8 `task_id=18` returned `Paramjit Uppal, Founder`.

8. Browser Use lifecycle helpers
   - The Rust-backed `Agent` now supports Browser Use-style `on_step_start`, `on_step_end`, `register_done_callback`, `run_sync()`, `save_history()`, `pause()`, `resume()`, `stop()`, `close()`, and `add_new_task()`.
   - The run hooks receive the agent object, matching the Python Agent API, and the done callback receives the reconstructed `AgentHistoryList`.
   - Proof: `test_rust_agent_invokes_browser_use_style_callbacks`, `test_rust_agent_run_sync_delegates_to_async_run`, and `test_rust_agent_lifecycle_state_and_save_history`.

9. Browser Use settings and direct URL startup
   - The Rust-backed `Agent` now stores Browser Use-style `settings`, `available_file_paths`, `file_system_path`, `directly_open_url`, `include_recent_events`, `sample_images`, `initial_url`, and `initial_actions`.
   - When `directly_open_url=True` and exactly one webpage-like URL appears in the task, the wrapper mirrors Browser Use startup behavior by converting it into an initial navigation instruction before invoking the Rust terminal core.
   - Ambiguous multi-URL tasks and file-like URLs are left untouched.
   - Proof: `test_rust_agent_mirrors_direct_url_startup`, `test_rust_agent_skips_ambiguous_or_excluded_direct_urls`, and `test_rust_agent_exposes_browser_use_settings`.

10. Trace and step callback helpers
   - The Rust-backed `Agent` now supports `register_new_step_callback`, `get_trace_object()`, and `authenticate_cloud_sync()`.
   - The step callback is invoked from reconstructed Rust terminal history with browser state, `None` for Python-only model output, and the reconstructed step number.
   - `get_trace_object()` returns Browser Use-style `trace` and `trace_details` dictionaries from the reconstructed history.
   - Proof: `test_rust_agent_invokes_new_step_callback` and `test_rust_agent_trace_and_cloud_auth_helpers`.

11. Rust terminal conversation transcript
   - `save_conversation_path` now writes a structured Rust terminal transcript under the configured directory after a run.
   - The transcript includes task/session metadata, final result, errors, URLs, token usage, stdout/stderr, and raw terminal events.
   - Proof: `test_rust_agent_saves_terminal_conversation`.

## Current Verification

- `python3 -m py_compile browser_use/rust/service.py browser_use/rust/__init__.py browser_use/__init__.py tests/ci/test_rust_agent.py examples/rust_agent/basic.py examples/rust_agent/real_v8_smoke.py`
- `uv run pytest -q tests/ci/test_rust_agent.py` (19 tests)
- `cargo build -q -p browser-use-cli`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent selected_remote_cdp_mode_allows_remote_cdp_connect -- --nocapture`
- Managed-headless end-to-end:
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=managed-headless BU_TASK='Open https://example.com and report the page title only.' BU_MAX_STEPS=12 timeout 300 uv run python examples/rust_agent/basic.py`
  - Output: `Example Domain`
- Remote-CDP end-to-end:
  - Launch external Chromium with `--remote-debugging-port=49333`.
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_CDP_URL=http://127.0.0.1:49333 BU_TASK='Open https://example.com and report the page title only.' BU_MAX_STEPS=12 timeout 300 uv run python examples/rust_agent/basic.py`
  - Output: `Example Domain`
- real_v8 remote-CDP end-to-end:
  - Launch external Chromium with `--remote-debugging-port=49333`.
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_CDP_URL=http://127.0.0.1:49333 timeout 600 uv run python examples/rust_agent/real_v8_smoke.py --task-id 18 --max-steps 30`
  - Output: `{"task_id": "18", "successful": true, "final_result": "Paramjit Uppal, Founder"}`

## Not Verified Yet

- Browser Use cloud remote browser end-to-end was not run because `browser-use-terminal auth status` reports `Browser Use cloud key: not connected`. The remote-CDP path has been verified against an external CDP browser.
- real_v8 was verified through remote CDP against an external local Chromium endpoint, not a Browser Use cloud browser, because the VM has no connected Browser Use cloud key.
