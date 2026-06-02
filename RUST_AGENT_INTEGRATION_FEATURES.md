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

12. Available file path context
   - `available_file_paths` are now passed into the Rust terminal task as concise local-file context.
   - This preserves the Browser Use constructor argument and gives the Rust core enough information to inspect user-provided files when needed.
   - Proof: `test_rust_agent_adds_available_files_to_task_context`.

13. Terminal subprocess timeout
   - Browser Use `step_timeout` is now enforced for Rust terminal subprocess runs.
   - A timed-out terminal run is killed and surfaced as a normal history error instead of hanging the Python wrapper indefinitely.
   - Proof: `test_rust_agent_terminal_process_timeout`.

14. Agent package import path
   - `from browser_use.agent import Agent` now lazily resolves to the same Rust-backed wrapper as `from browser_use import Agent`.
   - The export is lazy to avoid circular imports with `browser_use.agent.views`.
   - Proof: `test_agent_package_export_uses_rust_wrapper`.

15. BrowserProfile headless bridge
   - `BrowserProfile(headless=False)` now selects terminal `managed-headed`; `headless=True` selects `managed-headless`.
   - Remote CDP and explicit browser mode environment variables still override the profile preference.
   - Proof: `test_rust_agent_translates_browser_profile_headless` and `test_rust_agent_browser_mode_env_overrides_profile_headless`.

16. Initial actions context bridge
   - Single navigation startup keeps the direct `First navigate...` behavior.
   - Multi-step or non-navigation `initial_actions` are now passed to the Rust terminal task as an ordered Browser Use action list instead of being silently stored and dropped.
   - Proof: `test_rust_agent_preserves_ordered_initial_actions_context`.

17. BrowserProfile cloud bridge
   - `BrowserProfile(use_cloud=True)` and compatible `cloud_browser=True` profiles now select terminal `browser_mode="cloud"`.
   - CDP URLs still select `remote-cdp`, and explicit browser mode environment variables still override profile preferences.
   - Proof: `test_rust_agent_translates_browser_profile_cloud`.

18. BrowserProfile domain constraints bridge
   - `BrowserProfile.allowed_domains` and `BrowserProfile.prohibited_domains` are now preserved on the Rust-backed agent and passed into the Rust terminal task as explicit navigation constraints.
   - Domain lists preserve caller order, set values are made deterministic, and duplicate profile entries are ignored.
   - Proof: `test_rust_agent_adds_browser_profile_domain_constraints`.

19. Rust-compatible history rerun helpers
   - `Agent.rerun_history()` and `Agent.load_and_rerun()` are now available on the Rust-backed wrapper.
   - Saved Rust histories can be loaded, and reruns execute through the Rust terminal core while returning Browser Use-style `ActionResult` lists.
   - Proof: `test_rust_agent_rerun_history_delegates_to_rust_run` and `test_rust_agent_load_and_rerun_loads_saved_rust_history`.

20. Sensitive data placeholder bridge
   - `sensitive_data` is now converted into sanitized placeholder context for the Rust-backed task.
   - Global and domain-scoped placeholder names are exposed, but raw secret values are not added to the task text.
   - Proof: `test_rust_agent_adds_sensitive_data_placeholders_without_values`.

21. Result file attachment bridge
   - Terminal `session.done` result files are now exposed as Browser Use `ActionResult.attachments`.
   - Nested `result_file` payloads from the Rust core and flat legacy result-file fields are both supported.
   - Proof: `test_rust_history_exposes_result_file_attachments`.

22. Structured output JSON extraction
   - When `output_model_schema` is provided, fenced or prose-wrapped JSON in the Rust terminal final result is normalized before `AgentHistoryList.structured_output` is read.
   - Candidates are accepted only if they validate against the requested Pydantic schema.
   - Proof: `test_rust_history_extracts_fenced_structured_output`.

23. BrowserProfile managed launch args bridge
   - `BrowserProfile.args`, `proxy`, `window_size`, `user_agent`, `disable_security`, and `deterministic_rendering` are serialized into `BU_MANAGED_BROWSER_ARGS` for terminal managed Chromium runs.
   - The terminal core converts those JSON args into repeated `browser connect managed --arg ...` flags for both selected-mode connect and auto-ensure before browser actions.
   - Proof: `test_rust_agent_translates_browser_profile_managed_launch_args` and `bare_browser_connect_resolves_to_selected_managed_mode_with_launch_args`.

24. BrowserProfile managed user data dir bridge
   - `BrowserProfile.user_data_dir` is serialized into `BU_MANAGED_BROWSER_PROFILE` for terminal managed Chromium runs.
   - The terminal core maps that value to `browser connect managed --profile ...`, preserving persistent browser state without passing `--user-data-dir` as a raw Chromium arg.
   - Proof: `test_rust_agent_translates_browser_profile_user_data_dir` and `bare_browser_connect_resolves_to_selected_managed_mode_with_profile_dir`.

25. BrowserProfile managed executable path bridge
   - `BrowserProfile.executable_path` is serialized into `CHROME_PATH` for terminal managed Chromium runs.
   - The terminal core already tries `CHROME_PATH` first when launching managed Chromium, so custom Browser Use browser binaries are preserved without changing the Rust launcher.
   - Proof: `test_rust_agent_translates_browser_profile_executable_path`.

26. BrowserProfile managed launch environment bridge
   - `BrowserProfile.env` scalar values are serialized into the terminal subprocess environment for managed Chromium runs.
   - Values are stringified for process-env compatibility, unsupported nested values are ignored, and cloud/CDP runs do not receive managed browser launch env overrides.
   - Proof: `test_rust_agent_translates_browser_profile_env`.

27. BrowserProfile chromium sandbox bridge
   - `BrowserProfile(chromium_sandbox=False)` now emits the same standard Chromium sandbox-disable flags Browser Use applies for local managed launches.
   - The flags are passed through `BU_MANAGED_BROWSER_ARGS` and deduped with caller-provided `BrowserProfile.args`.
   - Proof: `test_rust_agent_translates_browser_profile_chromium_sandbox`.

28. BrowserProfile window position bridge
   - `BrowserProfile.window_position` is serialized into `--window-position=x,y` for terminal managed Chromium runs.
   - Dict-style and tuple-style position values are accepted by the Rust-backed wrapper.
   - Proof: `test_rust_agent_translates_browser_profile_window_position`.

29. BrowserProfile devtools bridge
   - `BrowserProfile(devtools=True)` is serialized into `--auto-open-devtools-for-tabs` for terminal managed Chromium runs.
   - This preserves Browser Use's headed-browser devtools launch option through the Rust managed browser path.
   - Proof: `test_rust_agent_translates_browser_profile_devtools`.

30. BrowserProfile profile directory bridge
   - `BrowserProfile.profile_directory` is serialized into `--profile-directory=...` for terminal managed Chromium runs.
   - This works with the managed `user_data_dir` bridge so callers can target a named Chrome profile inside the persistent profile root.
   - Proof: `test_rust_agent_translates_browser_profile_profile_directory`.

31. BrowserProfile permissions bridge
   - `BrowserProfile.permissions` is serialized into `BU_BROWSER_PERMISSIONS`.
   - The terminal core parses that JSON permission list and calls CDP `Browser.grantPermissions` after connecting to managed, local, remote-CDP, or cloud browsers.
   - Proof: `test_rust_agent_translates_browser_profile_permissions` and `browser_permissions_env_parses_json_array`.

32. BrowserProfile downloads bridge
   - `BrowserProfile.accept_downloads` is serialized into `BU_BROWSER_ACCEPT_DOWNLOADS`.
   - `BrowserProfile.downloads_path` is serialized into `BU_BROWSER_DOWNLOADS_PATH`.
   - The terminal core applies those settings with CDP `Browser.setDownloadBehavior` after connecting to managed, local, remote-CDP, or cloud browsers.
   - Proof: `test_rust_agent_translates_browser_profile_downloads`, `browser_download_behavior_env_allows_downloads_path`, and `browser_download_behavior_env_denies_disabled_downloads`.

33. BrowserProfile viewport bridge
   - `BrowserProfile.viewport`, `screen`, `device_scale_factor`, and `no_viewport` are serialized into `BU_BROWSER_VIEWPORT` and `BU_BROWSER_NO_VIEWPORT`.
   - The terminal core applies viewport metrics with CDP `Emulation.setDeviceMetricsOverride`, and the headless screenshot helper reuses those settings instead of forcing its default 1280x720 viewport.
   - Proof: `test_rust_agent_translates_browser_profile_viewport`, `browser_viewport_env_parses_device_metrics`, and `browser_viewport_env_honors_no_viewport`.

34. BrowserProfile storage state bridge
   - `BrowserProfile.storage_state` dicts and JSON paths are serialized into `BU_BROWSER_STORAGE_STATE`.
   - The terminal core applies compatible cookies with CDP `Storage.setCookies` and installs origin-scoped localStorage/sessionStorage init scripts with `Page.addScriptToEvaluateOnNewDocument`.
   - Proof: `test_rust_agent_translates_browser_profile_storage_state` and `browser_storage_state_env_parses_cookies_and_storage_scripts`.

35. BrowserProfile CDP headers bridge
   - `BrowserProfile.headers` is serialized into `BU_CDP_HEADERS`.
   - The terminal core applies those headers when resolving HTTP CDP endpoints through `/json/version` and when opening CDP WebSocket connections.
   - Proof: `test_rust_agent_translates_browser_profile_cdp_headers` and `cdp_headers_env_builds_websocket_request_headers`.

36. BrowserProfile interaction highlight bridge
   - `BrowserProfile.highlight_elements`, `dom_highlight_elements`, `interaction_highlight_color`, and `interaction_highlight_duration` are serialized into Rust terminal highlight env controls.
   - The terminal core now supports configurable highlight duration in addition to its existing highlight enable and color controls.
   - Proof: `test_rust_agent_translates_browser_profile_highlights` and `browser_highlight_env_controls_color_and_duration`.

37. BrowserProfile user agent CDP bridge
   - `BrowserProfile.user_agent` is serialized into `BU_BROWSER_USER_AGENT`.
   - The terminal core applies it with CDP `Network.setUserAgentOverride`, covering remote-CDP and cloud browsers in addition to the existing managed Chromium `--user-agent` launch arg.
   - Proof: `test_rust_agent_translates_browser_profile_remote_user_agent`, `test_rust_agent_translates_browser_profile_managed_launch_args`, and `browser_user_agent_env_builds_override_params`.

38. BrowserProfile page wait timing bridge
   - `BrowserProfile.minimum_wait_page_load_time`, `wait_for_network_idle_page_load_time`, and `wait_between_actions` are serialized into Rust browser-script helper env controls.
   - The terminal helper layer uses those values for post-navigation waits, default network-idle windows, and action helper delays.
   - Proof: `test_rust_agent_translates_browser_profile_wait_timings` and `browser_script_helpers_read_wait_timing_env`.

39. BrowserProfile IP address blocking bridge
   - `BrowserProfile.block_ip_addresses` is serialized into `BU_BROWSER_BLOCK_IP_ADDRESSES`.
   - The terminal helper layer rejects IP-literal hosts for `goto_url`, raw `Page.navigate`, and `http_get` when the setting is enabled.
   - Proof: `test_rust_agent_translates_browser_profile_block_ip_addresses` and `browser_script_helpers_block_ip_address_env`.

40. BrowserProfile domain constraints enforcement bridge
   - `BrowserProfile.allowed_domains` and `prohibited_domains` are serialized into `BU_BROWSER_ALLOWED_DOMAINS` and `BU_BROWSER_PROHIBITED_DOMAINS`.
   - The terminal helper layer enforces exact hosts, root-domain `www` variants, wildcard subdomains, scheme globs, and prohibited-domain blocking for `goto_url`, raw `Page.navigate`, and `http_get`.
   - Proof: `test_rust_agent_adds_browser_profile_domain_constraints` and `browser_script_helpers_enforce_domain_constraints_env`.

41. Browser-script navigation snapshot helper
   - Terminal browser scripts now expose `navigation_snapshot(keywords=None, limit=80)`.
   - The helper returns visible route links and menu-like controls with selectors, stable attributes, relevance scores, and keyword matches so Rust-backed agents can find hidden listings, document sections, and route/menu targets without broad planner changes.
   - Proof: `browser_script_navigation_snapshot_surfaces_menu_and_route_links`.

42. Browser-script embedded data snapshot helper
   - Terminal browser scripts now expose `embedded_data_snapshot(limit=80, max_sources=12)`.
   - The helper extracts bounded records from JSON-LD, Next.js/Nuxt hydration payloads, JSON script tags, and product/document meta tags, normalizing names, URLs, images, prices, dates, brands, descriptions, source metadata, and raw scalar fields.
   - Proof: `browser_script_embedded_data_snapshot_extracts_hydration_records`.

43. Browser-script document text extraction helper
   - Terminal browser scripts now expose `read_document_text(source, headers=None, timeout=30.0, max_chars=120000, binary=None)`.
   - The helper reads local paths or HTTP(S) document URLs and extracts bounded text from text/HTML, DOCX, and PDF sources using available Python PDF libraries, `pdftotext`, or a PDF byte-string fallback.
   - Proof: `browser_script_read_document_text_extracts_common_document_formats`.

44. Browser-script arXiv query helper
   - Terminal browser scripts now expose `arxiv_query(search_query="cat:cs.AI", start=0, max_results=20, sort_by="submittedDate", sort_order="descending", timeout=20.0)`.
   - The helper queries arXiv's Atom API directly and normalizes paper titles, authors and affiliations, summaries, abs/pdf URLs, categories, DOI, journal/comment metadata, and timestamps.
   - Proof: `browser_script_arxiv_query_normalizes_atom_metadata`.

45. Browser-script row-scoped grid extraction helper
   - Terminal browser scripts now expose `rows_snapshot(limit=8)` and `extract_grid_rows(selector=None, limit=50, include_html=False)`, plus compatibility aliases `grid_rows_snapshot` and `extract_rows`.
   - The helper identifies table/grid/list row selectors and extracts row-scoped cells, headers, description fields, links, buttons, file/document actions, and element coordinates so actions remain associated with the correct row.
   - Proof: `browser_script_grid_row_helpers_surface_row_scoped_actions`.

46. Browser-script batch HTTP fetch helper
   - Terminal browser scripts now expose `http_get_many(urls, headers=None, timeout=20.0, binary=False, max_workers=8)`.
   - The helper fetches static page/API URLs concurrently while preserving input order and returning compact per-URL success, status, headers, text/content, and error records so one blocked URL does not discard the whole batch.
   - Proof: `browser_script_http_get_many_preserves_order_errors_and_binary`.

47. Browser-script page-context fetch helper
   - Terminal browser scripts now expose `browser_fetch(url, headers=None, method="GET", body=None, timeout=20.0, binary=False)`.
   - The helper runs `fetch(...)` in the current page context with browser credentials, timeout aborting, JSON parsing, and binary base64 output for sites where direct HTTP is blocked but the loaded page has cookies or same-origin API access.
   - Proof: `browser_script_browser_fetch_uses_page_context_credentials`.

48. Browser-script batch page-context fetch helper
   - Terminal browser scripts now expose `browser_fetch_many(urls, headers=None, method="GET", body=None, timeout=20.0, binary=False, max_concurrent=8)`.
   - The helper fetches multiple URLs concurrently in the loaded page context, preserves input order, returns per-URL JSON/text/binary records, and converts BrowserProfile-blocked absolute URLs into per-row errors without sending them to page JavaScript.
   - Proof: `browser_script_browser_fetch_many_preserves_order_errors_and_binary`.

49. Browser-script repeated item extraction helper
   - Terminal browser scripts now expose `repeated_items_snapshot(min_count=3, limit=8, include_prices=True)` and `extract_repeated_items(selector, limit=50, include_html=False)`.
   - The helper finds repeated visible cards/list items using stable selectors and extracts actionable records with attributes, headings, labels, prices, row/cell headers, links/buttons, and image/lazy-load metadata.
   - Proof: `browser_script_repeated_item_helpers_surface_actionable_records`.

## Current Verification

- `python3 -m py_compile browser_use/rust/service.py browser_use/rust/__init__.py browser_use/__init__.py tests/ci/test_rust_agent.py examples/rust_agent/basic.py examples/rust_agent/real_v8_smoke.py`
- `uv run pytest -q tests/ci/test_rust_agent.py` (49 tests)
- `cargo build -q -p browser-use-cli`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent selected_remote_cdp_mode_allows_remote_cdp_connect -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent bare_browser_connect_resolves_to_selected_managed_mode_with_launch_args -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-agent bare_browser_connect_resolves_to_selected_managed_mode_with_profile_dir -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_permissions_env_parses_json_array -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_download_behavior_env_ -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_viewport_env_ -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_storage_state_env_parses_cookies_and_storage_scripts -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser cdp_headers_env_builds_websocket_request_headers -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_highlight_env_controls_color_and_duration -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_user_agent_env_builds_override_params -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_helpers_read_wait_timing_env -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_helpers_block_ip_address_env -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_helpers_enforce_domain_constraints_env -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_navigation_snapshot_surfaces_menu_and_route_links -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_embedded_data_snapshot_extracts_hydration_records -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_read_document_text_extracts_common_document_formats -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_arxiv_query_normalizes_atom_metadata -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_grid_row_helpers_surface_row_scoped_actions -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_http_get_many_preserves_order_errors_and_binary -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_browser_fetch_uses_page_context_credentials -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_browser_fetch_many_preserves_order_errors_and_binary -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_repeated_item_helpers_surface_actionable_records -- --nocapture`
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
