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
   - Proof: `test_rust_agent_translates_browser_use_args_to_terminal`.

5. Remote CDP terminal mode
   - Terminal browser handling now accepts locked `remote-cdp` mode instead of rejecting `browser connect remote-cdp`.
   - Proof: `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent selected_remote_cdp_mode_allows_remote_cdp_connect -- --nocapture`.

6. Smoke example
   - `examples/rust_agent/basic.py` runs a Rust-backed Agent through the Browser Use-style API.
   - It accepts `BU_CDP_URL` or `BROWSER_USE_CDP_URL` for external CDP attachment.
   - Proof: managed-headless smoke returned `Example Domain` for `https://example.com`.

## Current Verification

- `python3 -m py_compile browser_use/rust/service.py browser_use/rust/__init__.py browser_use/__init__.py tests/ci/test_rust_agent.py examples/rust_agent/basic.py`
- `uv run pytest -q tests/ci/test_rust_agent.py`
- `cargo build -q -p browser-use-cli`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent selected_remote_cdp_mode_allows_remote_cdp_connect -- --nocapture`
- Managed-headless end-to-end:
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=managed-headless BU_TASK='Open https://example.com and report the page title only.' BU_MAX_STEPS=12 timeout 300 uv run python examples/rust_agent/basic.py`
  - Output: `Example Domain`

## Not Verified Yet

- Browser Use cloud remote browser end-to-end was not run because `browser-use-terminal auth status` reports `Browser Use cloud key: not connected`, and no `BU_CDP_URL` or `BROWSER_USE_CDP_URL` is set.
- Real v8 eval smoke was not rerun after this reset because the current objective prioritizes the latest-main integration branch and the VM has no connected Browser Use cloud key.

