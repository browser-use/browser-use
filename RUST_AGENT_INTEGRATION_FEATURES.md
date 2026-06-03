# Rust Agent Integration Features

Branch: `magnus/browser-use-rust-core-integration`

Terminal core branch: `magnus/browser-use-rust-main-integration` at terminal main `ee3ce69` plus Codex session rerun support commit `8c8dd8a`.

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

50. Browser-script pricing card snapshot helper
   - Terminal browser scripts now expose `pricing_cards_snapshot(limit=50)`.
   - The helper surfaces visible commercial product/plan/package cards with normalized price amounts, currency and billing period, speed/data/network signals, contract terms, offer labels, provider candidates, links, images, and stable selectors.
   - Proof: `browser_script_pricing_cards_snapshot_surfaces_commercial_signals`.

51. Browser-script sitemap URL discovery helper
   - Terminal browser scripts now expose `sitemap_urls_snapshot(url_or_domain=None, keywords=None, limit=80, max_sitemaps=8, timeout=10.0)`.
   - The helper reads robots.txt and XML sitemap indexes, follows one nested sitemap level, ranks public routes by task keywords and listing/product/document/search route patterns, and demotes static assets.
   - Proof: `browser_script_sitemap_urls_snapshot_discovers_public_routes`.

52. Browser-script SPA route candidate helper
   - Terminal browser scripts now expose `route_candidates_snapshot(url_or_domain=None, keywords=None, limit=80, max_scripts=12, timeout=10.0)`.
   - The helper scans visible DOM route attributes, inline scripts, and same-origin bundled JavaScript for likely public listing, booking, product, document, search, and investor routes hidden inside SPA manifests.
   - Proof: `browser_script_route_candidates_snapshot_discovers_spa_routes`.

53. Browser-script network resource discovery helper
   - Terminal browser scripts now expose `network_resources_snapshot(limit=80, keywords=None)`.
   - The helper ranks API, JSON/CSV/table, document/download, pagination, form, export, inline-script, and data-attribute URLs from the current page's performance entries and DOM without fetching them itself.
   - Proof: `browser_script_network_resources_snapshot_surfaces_api_candidates`.

54. Browser-script JSON API record extraction helper
   - Terminal browser scripts now expose `json_api_records(urls, records_path=None, limit=200, max_urls=8, use_browser_fetch=False, timeout=20.0)`.
   - The helper fetches JSON/API candidates, recursively finds record arrays, supports explicit dot-path selection, flattens nested scalar fields, reports candidate array paths/fields, and can run through page-context `browser_fetch` when cookies/session access are needed.
   - Proof: `browser_script_json_api_records_extracts_nested_record_arrays`.

55. Browser-script tabular export extraction helper
   - Terminal browser scripts now expose `tabular_data_records(source, delimiter=None, limit=500, use_browser_fetch=False, table_index=0, timeout=20.0)`.
   - The helper fetches or reads CSV, TSV, and simple HTML table sources, normalizes duplicate/missing headers, returns fields and records, and can use page-context `browser_fetch` for cookie-protected exports.
   - Proof: `browser_script_tabular_data_records_normalizes_exports`.

56. Browser-script investor document discovery helper
   - Terminal browser scripts now expose `investor_documents_snapshot(limit=80, keywords=None, latest_only=False)`.
   - The helper classifies visible investor/report/earnings document links into releases, supplements, presentations, transcripts, reports, and data annexes with dates, extensions, period tokens, keyword matches, context, scores, and direct URLs for `read_document_text`.
   - Proof: `browser_script_investor_documents_snapshot_classifies_visible_links`.

57. Browser-script generic document link discovery helper
   - Terminal browser scripts now expose `document_links_snapshot(limit=100, keywords=None)`.
   - The helper classifies visible FERC, docket, regulatory, government, report, and generic filing/search result links with row/card context, docket tokens, accession IDs, dates, document type, extension, score, source, and direct URL for `read_document_text`.
   - Proof: `browser_script_document_links_snapshot_classifies_filing_documents`.

58. Browser-script Shopify catalog extraction helper
   - Terminal browser scripts now expose `shopify_products_api(url_or_domain=None, limit=250, page_limit=20, timeout=12.0)`.
   - The helper fetches public Shopify `/products.json` pages and normalizes product titles, handles, URLs, vendors, product types, tags, descriptions, variant availability/SKUs/options/prices, compare-at prices, images, and attempted catalog URLs.
   - Proof: `browser_script_shopify_products_api_normalizes_catalog_pages`.

59. Browser-script product record snapshot helper
   - Terminal browser scripts now expose `product_records_snapshot(limit=80, keywords=None)`.
   - The helper combines JSON-LD, product meta tags, and visible product-like cards for non-Shopify catalogs, returning normalized titles, URLs, descriptions, prices, specs, labels, images, source, scores, and detail-action counts.
   - Proof: `browser_script_product_records_snapshot_normalizes_catalog_products`.

60. Browser-script pagination helper
   - Terminal browser scripts now expose `pagination_controls_snapshot(limit=20)`, `click_pagination(label_or_text="next", timeout=2.0)`, and `click_pagination_until_stable(label_or_text="load more", max_clicks=20, wait_seconds=0.8, idle_timeout=3.0, count_selector=None)`.
   - The helpers rank visible Next/Load More/pager controls, click matched controls by label or intent, and repeatedly advance result lists until no matching control remains or the visible result state stops changing.
   - Proof: `browser_script_pagination_helpers_click_until_stable`.

61. Browser-script result-count snapshot helper
   - Terminal browser scripts now expose `result_count_snapshot(limit=12)`.
   - The helper parses visible range totals, showing/displaying totals, page totals, compact page counts, labeled totals, and found/total snippets from page body, status, table, and pagination regions.
   - Proof: `browser_script_result_count_snapshot_parses_visible_count_evidence`.

62. Browser-script contact details snapshot helper
   - Terminal browser scripts now expose `contact_details_snapshot(limit=50)`.
   - The helper extracts and normalizes visible and structured emails, phones, contact links, social links, addresses, JSON-LD contact records, and contact evidence sections.
   - Proof: `browser_script_contact_details_snapshot_normalizes_candidates`.

63. Browser-script location records snapshot helper
   - Terminal browser scripts now expose `location_records_snapshot(limit=200, keywords=None)`.
   - The helper extracts structured and visible store, hospital, office, directory, and local-business location records with names, addresses, city/state/postal fields, phone numbers, URLs, hours, source/kind labels, keyword scoring, and normalized text.
   - Proof: `browser_script_location_records_snapshot_normalizes_directory_records`.

64. Browser-script form control helper
   - Terminal browser scripts now expose `form_controls_snapshot(limit=30)` and `toggle_form_control(label_or_text, checked=True, timeout=1.0)`.
   - The helpers surface visible checkbox, radio, and switch controls with labels/state/rects, then set a matched rendered control by label, name, or selector using a real click.
   - Proof: `browser_script_form_control_helpers_toggle_labeled_controls`.

65. Browser-script select control helper
   - Terminal browser scripts now expose `select_controls_snapshot(limit=20, option_limit=30)` and `select_option(label_or_placeholder, option_text_or_value, timeout=1.0)`.
   - The helpers surface native selects and combobox-like controls with labels/current values/options/rects, then choose native select options by label/value via focus plus keyboard navigation or use click/type/Enter for comboboxes.
   - Proof: `browser_script_select_helpers_choose_native_select_options`.

66. Browser-script semantic form field helper
   - Terminal browser scripts now expose `form_fields_snapshot(limit=30)` and `fill_form_field(label_or_placeholder, value, clear=True, timeout=3.0)`.
   - The helpers surface visible text fields, textareas, contenteditable fields, comboboxes, and textbox roles with labels/placeholders/selectors/rects, then fill a matched field by label, placeholder, name, selector, or nearby text through the existing real browser `fill_input` path.
   - Proof: `browser_script_form_field_helpers_match_labels_and_fill_semantically`.

67. Browser-script autocomplete helper
   - Terminal browser scripts now expose `autocomplete_suggestions_snapshot(query=None, limit=20)` and `select_autocomplete(label_or_placeholder, query, match_text=None, timeout=3.0)`.
   - The helpers score visible typeahead/listbox/menu suggestions using active-field `aria-controls`, roles, autocomplete/typeahead/dropdown classes, query text, rects, and centers, then fill the matched field and click the best visible suggestion.
   - Proof: `browser_script_autocomplete_helpers_select_visible_suggestions`.

68. Browser-script action control helper
   - Terminal browser scripts now expose `action_controls_snapshot(limit=30)` and `click_button(label_or_text, timeout=3.0)`.
   - The helpers surface visible buttons, submit/reset/button inputs, links, role buttons/links, and onclick elements with text/selectors/rects, then click the matched rendered action by text, aria-label, name, or selector using real mouse events.
   - Proof: `browser_script_action_helpers_click_named_controls`.

69. Browser-script overlay dismissal helper
   - Terminal browser scripts now expose `overlay_actions_snapshot(limit=20)` and `dismiss_overlay(prefer="accept", timeout=1.0)`.
   - The helpers score visible cookie, consent, privacy, GDPR, modal, dialog, popup, and banner actions with overlay context and centers, then click an accept/reject/close/dismiss action by preference using real mouse events.
   - Proof: `browser_script_overlay_helpers_dismiss_cookie_actions`.

70. Browser-script paginated grid row helper
   - Terminal browser scripts now expose `extract_paginated_grid_rows(selector=None, next_label="next", max_pages=10, per_page_limit=100, include_html=False, stop_on_duplicate_page=True)`.
   - The helper repeatedly extracts row-scoped records with `extract_grid_rows`, clicks matching pagination controls, annotates each record with `page_index`, deduplicates repeated pages, and returns page bookkeeping plus deduplicated file/detail actions.
   - Proof: `browser_script_extract_paginated_grid_rows_collects_pages`.

71. Browser-script Semantic Scholar helpers
   - Terminal browser scripts now expose `semantic_scholar_citations(query_or_paper_id, year=None, limit=200, search_limit=5, timeout=20.0)` and `semantic_scholar_references(query_or_paper_id, year=None, limit=200, search_limit=5, timeout=20.0)`.
   - The helpers search or fetch a target paper through the Semantic Scholar Graph API, normalize selected-paper metadata, authors, venues, external IDs, open-access PDF URLs, abstracts, and paginated citation/reference records with optional year filtering.
   - Proof: `browser_script_semantic_scholar_helpers_normalize_paper_graphs`.

72. Browser-script OpenReview notes helper
   - Terminal browser scripts now expose `openreview_notes(endpoint="search", params=None, limit=100, offset=0, timeout=20.0)`.
   - The helper calls OpenReview `notes/search` or `notes`, preserves note/forum/invitation/domain metadata, and unwraps nested `content.value` / `content.values` payloads into normal Python values for search, decision, review, and author-note tasks.
   - Proof: `browser_script_openreview_notes_normalizes_content_values`.

73. Browser-script Nobel Prize API helper
   - Terminal browser scripts now expose `nobel_prize_api(endpoint="laureates", params=None, timeout=20.0, lang="en")`.
   - The helper calls the official Nobel Prize API v2.1 for laureates or prizes, normalizes localized names, prize metadata, motivations, laureate fields, nested links, and official nobelprize.org URLs.
   - Proof: `browser_script_nobel_prize_api_normalizes_official_links`.

74. Browser-script Wikidata SPARQL helper
   - Terminal browser scripts now expose `wikidata_sparql(query, timeout=20.0, limit=None)`.
   - The helper runs Wikidata SPARQL queries, appends a limit when requested, normalizes result bindings, extracts QID/PID IDs and entity URLs from Wikidata entity URIs, and adds label-text convenience fields for `*Label` bindings.
   - Proof: `browser_script_wikidata_sparql_normalizes_entity_bindings`.

75. Browser-script Wikidata education/award cascade helper
   - Terminal browser scripts now expose `wikidata_education_award_cascade(person_names, award_keywords=None, limit_per_person=50, timeout=20.0)`.
   - The helper resolves people through Wikidata search, queries their education institutions and degree qualifiers, finds other award winners educated at the same institutions, deduplicates relationship rows, and returns normalized institution, award, degree, and person QIDs/URLs.
   - Proof: `browser_script_wikidata_education_award_cascade_resolves_and_queries`.

76. Browser-script row fanout manifest helper
   - Terminal browser scripts now attach row/file fanout manifests to `rows_snapshot(...)`, `extract_grid_rows(...)`, and `extract_paginated_grid_rows(...)`.
   - The helpers collect deduplicated row/file detail actions, recommend fanout when enough independent actions are present, and return `fanout_tasks` with per-item instructions and spawn messages for child-agent processing.
   - Proof: `browser_script_grid_rows_builds_fanout_manifests`; paginated coverage: `browser_script_extract_paginated_grid_rows_collects_pages`.

77. Rust Agent step/action compatibility
   - The Rust-backed `Agent` now exposes Browser Use-style `take_step(step_info=None)` and `multi_act(actions)`.
   - `take_step` drives one Rust terminal turn and returns `(is_done, is_valid)`; `multi_act` preserves local `done` action semantics and routes non-done Browser Use action batches through the active Rust session or a bounded one-step run.
   - Proof: `test_rust_agent_take_step_runs_one_terminal_turn`, `test_rust_agent_multi_act_preserves_done_action`, and `test_rust_agent_multi_act_routes_actions_to_followup`.

78. Rust Agent constructor session/filesystem parity
   - The Rust-backed `Agent` now initializes a real Browser Use `BrowserSession`/`BrowserProfile` pair when callers do not provide a session, preserving default post-construction access to `agent.browser_session` and `agent.browser_profile`.
   - The wrapper now creates Browser Use-style `agent_directory`, `file_system`, `file_system_path`, restored `file_system_state`, and download-path tracking attributes while preserving duck-typed profile/session inputs for lightweight tests and custom callers.
   - Proof: `test_rust_agent_initializes_browser_use_session_and_file_system`.

79. Rust Agent downloaded file tracking
   - The Rust-backed `Agent` now mirrors Browser Use's downloaded-file bookkeeping for supplied sessions by syncing `browser_session.downloaded_files` into `available_file_paths` after Rust runs and follow-ups.
   - The wrapper also exposes `save_file_system_state()` so callers can persist the Browser Use `FileSystem` state back onto the agent state.
   - Proof: `test_rust_agent_tracks_downloaded_files_and_saves_file_system_state`.

80. Rust Agent tools/action-model parity
   - The Rust-backed `Agent` now initializes Browser Use default `Tools` when callers do not provide tools/controller, including `use_vision=False` screenshot exclusion and structured-output `done` action registration.
   - The wrapper now exposes Browser Use-style `ActionModel`, `DoneActionModel`, and `AgentOutput` classes from the configured tools registry so custom callers can inspect and build action models against the same interface.
   - Proof: `test_rust_agent_initializes_tools_and_action_models`.

81. Rust Agent initial action model conversion
   - The Rust-backed `Agent` now converts dictionary `initial_actions` into Browser Use registry-backed action model instances while keeping ordered raw `initial_action_payloads` for Rust task context.
   - Common Browser Use legacy aliases such as `go_to_url`, `open_tab`, `click_element_by_index`, and `input_text` normalize to the current `navigate`, `click`, and `input` actions when the local registry can validate them.
   - Proof: `test_rust_agent_preserves_ordered_initial_actions_context` and `test_rust_agent_mirrors_direct_url_startup`.

82. Rust Agent runtime metadata and observability parity
   - The Rust-backed `Agent` now exposes Browser Use-style `version`, `source`, `logger`, `eventbus`, `telemetry`, and `token_cost_service` attributes.
   - The wrapper registers supplied LLMs with token-cost tracking when they expose `ainvoke`, creates a valid Bubus event bus name for arbitrary task IDs, and exposes `DoneAgentOutput` alongside `DoneActionModel`.
   - Proof: `test_rust_agent_initializes_runtime_metadata_and_observability`.

83. Rust Agent message manager parity
   - The Rust-backed `Agent` now initializes a Browser Use `MessageManager` and exposes it through `agent.message_manager`.
   - `add_new_task(...)` now updates the message manager follow-up history, resets pause/stop state, and recreates a valid event bus name without depending on the Python Agent run loop.
   - Proof: `test_rust_agent_initializes_message_manager_and_followup_state`.

84. Rust Agent step method parity
   - The Rust-backed `Agent` now exposes Browser Use's async `step(...)` method and routes it through a single Rust terminal turn.
   - Single-step Rust results now synchronize into `agent.state.last_result`, so Browser Use callers can inspect the last action result after `step(...)`, `take_step(...)`, `run(...)`, or `follow_up(...)`.
   - Proof: `test_rust_agent_step_runs_single_terminal_turn_and_updates_state`.

85. Rust Agent screenshot service parity
   - The Rust-backed `Agent` now initializes Browser Use's `ScreenshotService` under the agent directory during construction.
   - Callers can use `agent.screenshot_service.store_screenshot(...)` and `get_screenshot(...)` with the same storage layout as the Python Agent.
   - Proof: `test_rust_agent_initializes_screenshot_service`.

86. Rust Agent completion logging parity
   - The Rust-backed `Agent` now exposes Browser Use's async `log_completion()` method.
   - Completed Rust-backed runs now log task completion before invoking any registered done callback, matching the Python Agent lifecycle surface.
   - Proof: `test_rust_agent_logs_completion_before_done_callback`.

87. Rust Agent GIF generation parity
   - The Rust-backed `Agent` now honors Browser Use's `generate_gif` setting after completed Rust terminal runs and follow-ups.
   - GIF creation uses Browser Use's `create_history_gif(...)` with the same default `agent_history.gif` output path or caller-provided string path.
   - Proof: `test_rust_agent_generates_gif_after_done_callback`.

88. Rust Agent session identity parity
   - The Rust-backed `Agent` now initializes `agent.session_id` during construction as a Browser Use agent session id, matching the Python Agent public interface.
   - Rust terminal session identity is tracked separately as `agent.terminal_session_id` and is used for `run-codex-session`, event loading, follow-ups, and transcript metadata.
   - Proof: `test_rust_agent_keeps_browser_use_session_id_separate_from_terminal_session`.

89. Rust Agent execute-step helper parity
   - The Rust-backed `Agent` now exposes Browser Use's async `_execute_step(...)` helper and routes it through a single Rust terminal turn.
   - The helper preserves Browser Use-style step start/end callbacks, returns the done state, and records timeout errors in `state.last_result`.
   - Proof: `test_rust_agent_execute_step_runs_one_turn_with_callbacks`.

90. Rust Agent page action model update parity
   - The Rust-backed `Agent` now exposes Browser Use's async `_update_action_models_for_page(...)` helper.
   - Page updates rebuild `ActionModel`, `AgentOutput`, `DoneActionModel`, and `DoneAgentOutput` through the configured tools registry with the current page URL.
   - Proof: `test_rust_agent_updates_action_models_for_page`.

91. Rust Agent browser profile property parity
   - The Rust-backed `Agent` now exposes `browser_profile` as a Browser Use-style property derived from the current `browser_session.browser_profile`.
   - The wrapper keeps a fallback initial profile for lightweight custom sessions while reflecting later browser-session profile changes through the public property.
   - Proof: `test_rust_agent_browser_profile_property_tracks_session_profile`.

92. Rust Agent stop/pause lifecycle helper parity
   - The Rust-backed `Agent` now exposes Browser Use's async `_check_stop_or_pause(...)` helper.
   - The helper evaluates external stop callbacks, sets stopped state for should-stop callbacks, and raises `InterruptedError` for stopped or paused agents.
   - Proof: `test_rust_agent_check_stop_or_pause_matches_browser_use_lifecycle`.

93. Rust Agent task helper method parity
   - The Rust-backed `Agent` now exposes Browser Use's `_enhance_task_with_schema(...)` and `_extract_start_url(...)` helper methods.
   - The helpers preserve Browser Use-style schema text formatting and direct-start URL filtering for domains, email addresses, ambiguous tasks, and document URLs.
   - Proof: `test_rust_agent_exposes_task_helper_methods`.

94. Rust Agent URL/text helper parity
   - The Rust-backed `Agent` now exposes Browser Use's think-tag cleanup and URL shortening/restoration helpers.
   - The helpers support Browser Use message content mutation plus recursive Pydantic/dict/list/tuple restoration of shortened URLs.
   - Proof: `test_rust_agent_exposes_url_text_helper_methods`.

95. Rust Agent setup helper parity
   - The Rust-backed `Agent` now exposes Browser Use's `_set_file_system(...)`, `_set_screenshot_service()`, `_set_browser_use_version_and_source(...)`, and `_verify_and_setup_llm()` setup helpers.
   - Construction routes through the helper methods, and direct calls support state restoration, explicit file-system initialization, screenshot storage setup, source overrides, and Rust-terminal LLM verification compatibility.
   - Proof: `test_rust_agent_exposes_setup_helper_methods`.

96. Rust Agent logging helper parity
   - The Rust-backed `Agent` now exposes Browser Use's run, startup, step context, action summary, step completion, final outcome, telemetry event, and action logging helpers.
   - Telemetry is emitted from reconstructed Rust history, preserving URLs, errors, usage tokens, final result, timing, and Browser Use model/session metadata where available.
   - Proof: `test_rust_agent_exposes_logging_helper_methods`.

97. Rust Agent step finalization helper parity
   - The Rust-backed `Agent` now exposes Browser Use's `_post_process()`, `_handle_step_error(...)`, `_finalize(...)`, `_force_done_after_last_step(...)`, `_force_done_after_failure()`, and `_make_history_item(...)` helpers.
   - The helpers preserve failure bookkeeping, done-result logging, screenshot-backed history item creation, file-system state persistence, step counting, and done-only output switching for Rust-backed helper execution.
   - Proof: `test_rust_agent_exposes_step_finalization_helper_methods`.

98. Rust Agent action replay helper parity
   - The Rust-backed `Agent` now exposes Browser Use's `_execute_initial_actions()`, `_execute_history_step(...)`, and `_update_action_indices(...)` replay helpers.
   - Initial actions execute through `multi_act` and are recorded as step 0, while history replay remaps moved DOM indices by element hash before routing actions through the Rust-backed action path.
   - Proof: `test_rust_agent_exposes_action_replay_helper_methods`.

99. Rust Agent model output helper parity
   - The Rust-backed `Agent` now exposes Browser Use's `get_model_output(...)`, `_get_model_output_with_retry(...)`, `_handle_post_llm_processing(...)`, `_get_next_action(...)`, and `_execute_actions()` helpers.
   - The helpers preserve long-URL restoration in parsed LLM actions, max-action truncation, empty-action retry, step callbacks, conversation saving, and action execution through the Rust-backed `multi_act` path.
   - Proof: `test_rust_agent_exposes_model_output_helper_methods`.

100. Rust Agent prepare-context helper parity
   - The Rust-backed `Agent` now exposes Browser Use's `_prepare_context(...)` helper.
   - The helper captures browser state with screenshots/recent events, updates downloads, logs step context, refreshes page-filtered action models, creates state messages with sensitive-data and available-file context, and applies last-step/failure done-only switching.
   - Proof: `test_rust_agent_exposes_prepare_context_helper_method`.

101. Rust Agent constructor signature order parity
   - The Rust-backed `Agent.__init__(...)` now preserves Browser Use's constructor parameter order, including the `source`, `file_system_path`, and `task_id` tail after `injected_agent_state`.
   - Positional constructor calls that rely on Browser Use's public signature now route those values to the same Rust wrapper fields while retaining keyword compatibility.
   - Proof: `test_rust_agent_constructor_signature_matches_browser_use_order`.

102. Rust Agent action-model setup signature parity
   - The Rust-backed `Agent._setup_action_models()` now preserves Browser Use's no-argument helper signature.
   - Page-specific action-model rebuilding remains available through the Rust wrapper's internal helper and `_update_action_models_for_page(...)`, so filtered tool models still work without exposing an incompatible public helper signature.
   - Proof: `test_rust_agent_setup_action_models_signature_matches_browser_use`.

103. Rust Agent service import parity
   - `from browser_use.agent.service import Agent` now resolves to the Rust-backed Agent wrapper, matching the top-level `browser_use.Agent` and package-level `browser_use.agent.Agent` exports.
   - The original Python Agent class remains available privately as `_PythonAgent` for parity audits while common direct service imports run through the Rust core.
   - Proof: `test_agent_service_export_uses_rust_wrapper`.

104. Rust Agent page-extraction LLM default parity
   - The Rust-backed Agent now mirrors Browser Use's constructor default that uses the main `llm` as `settings.page_extraction_llm` when no dedicated extraction model is provided.
   - Explicit `page_extraction_llm` overrides are still preserved, and both defaulted and explicit extraction models can be registered with token usage tracking.
   - Proof: `test_rust_agent_defaults_page_extraction_llm_to_main_llm`.

105. Rust Agent state ID default parity
   - The Rust-backed Agent now mirrors Browser Use's default `AgentState()` initialization instead of forcing `state.agent_id` to match the public task id.
   - Explicit `task_id` still controls `agent.id` and `agent.task_id`, while injected `AgentState` objects remain preserved for restored runs.
   - Proof: `test_rust_agent_state_id_defaults_like_browser_use`.

106. Rust Agent Browser Use LLM flash-mode parity
   - The Rust-backed Agent now mirrors Browser Use's constructor behavior that enables `settings.flash_mode` when the supplied LLM has `provider == 'browser-use'`.
   - Non-Browser Use providers retain the caller's flash-mode setting, and Browser Use-provider models build the same flash-mode action output class family.
   - Proof: `test_rust_agent_enables_flash_mode_for_browser_use_llm_provider`.

107. Rust Agent LLM timeout default parity
   - The Rust-backed Agent now mirrors Browser Use's constructor timeout defaults by model family: Gemini uses 45 seconds, Groq uses 30 seconds, O3/Claude/Sonnet/DeepSeek use 90 seconds, and other models use 60 seconds.
   - Explicit `llm_timeout` overrides still take precedence over the model-family heuristic.
   - Proof: `test_rust_agent_llm_timeout_defaults_match_browser_use_model_families`.

108. Rust Agent unsupported vision model parity
   - The Rust-backed Agent now mirrors Browser Use's constructor behavior that disables `settings.use_vision` for DeepSeek and Grok/XAI model families.
   - Ordinary vision-capable model families still preserve caller-provided `use_vision=True`.
   - Proof: `test_rust_agent_disables_vision_for_unsupported_model_families`.

109. Rust Agent generic subscription parity
   - The Rust-backed `Agent` now mirrors Browser Use's two-parameter generic runtime surface for `Agent[Context, StructuredOutput]` annotations.
   - The redirected `browser_use.agent.service.Agent` import also supports the same two-argument generic subscription, while one-argument subscriptions raise the same too-few-arguments error shape as Browser Use.
   - Proof: `test_rust_agent_generic_subscription_matches_browser_use`.

110. Rust Agent event bus naming parity
   - The Rust-backed Agent now mirrors Browser Use's public event bus naming convention with an `Agent_` prefix and public task-id suffix.
   - Hyphenated task-id suffixes are sanitized into valid identifiers, and follow-up task event buses keep the same base prefix with a unique suffix.
   - Proof: `test_rust_agent_eventbus_name_matches_browser_use_suffix_prefix`.

111. Rust Agent constructor type-hint parity
   - The Rust-backed `Agent.__init__(...)` now exposes Browser Use's constructor type metadata for the core public parameters that users and tooling introspect.
   - LLM, callback, structured-output, extraction-LLM, sample-image, and tools/controller annotations now mirror Browser Use's concrete types, while unannotated `**kwargs` and constructor return metadata stay unannotated like the Python Agent.
   - Proof: `test_rust_agent_constructor_type_hints_match_browser_use_core_params`.

112. Rust Agent run hook type-hint parity
   - The Rust-backed `Agent.run(...)` and `Agent.run_sync(...)` methods now expose Browser Use's hook callback type metadata.
   - `on_step_start` and `on_step_end` resolve to Browser Use's `Callable[[Agent], Awaitable[None]] | None` hook shape instead of the previous loose `Any` callback annotation, while the runtime callback behavior remains unchanged.
   - Proof: `test_rust_agent_run_type_hints_match_browser_use_hooks`.

113. Rust Agent action-model helper type-hint parity
   - The Rust-backed action helper methods now expose Browser Use's action-model type metadata for callers that introspect replay and multi-action APIs.
   - `_convert_initial_actions(...)`, `_update_action_indices(...)`, and `multi_act(...)` now resolve to Browser Use's `ActionModel`, `DOMInteractedElement`, and `BrowserStateSummary` annotations instead of loose `Any` metadata.
   - Proof: `test_rust_agent_action_model_helper_type_hints_match_browser_use`.

114. Rust Agent browser-state helper type-hint parity
   - The Rust-backed browser-state helper methods now expose Browser Use's `BrowserStateSummary` metadata for callers that introspect step preparation, logging, action selection, history creation, and finalization.
   - `_prepare_context(...)`, `_get_next_action(...)`, `_log_step_context(...)`, `_make_history_item(...)`, and `_finalize(...)` now resolve to the same Browser Use browser-state annotations instead of loose `Any` metadata.
   - Proof: `test_rust_agent_browser_state_helper_type_hints_match_browser_use`.

115. Rust Agent LLM-message helper type-hint parity
   - The Rust-backed LLM helper methods now expose Browser Use's `BaseMessage` metadata for callers that introspect model-output and URL-shortening helpers.
   - `get_model_output(...)`, `_get_model_output_with_retry(...)`, `_handle_post_llm_processing(...)`, and `_process_messsages_and_replace_long_urls_shorter_ones(...)` now resolve to Browser Use's message-list annotations instead of loose `Any` metadata.
   - Proof: `test_rust_agent_llm_message_helper_type_hints_match_browser_use`.

116. Rust Agent unannotated helper type-hint parity
   - The Rust-backed helper methods now mirror Browser Use's intentionally unannotated metadata for helpers where the Python Agent does not publish runtime type hints.
   - `_log_action(...)`, `_verify_and_setup_llm()`, `close()`, and `load_and_rerun(...)` no longer expose Rust-only `Any` or return annotations that Browser Use callers would not see.
   - Proof: `test_rust_agent_unannotated_helper_type_hints_match_browser_use`.

117. Rust Agent class metadata parity
   - The Rust-backed replacement now presents `__module__` as `browser_use.agent.service`, matching Browser Use's public Agent class metadata.
   - This keeps direct imports, top-level imports, `repr(Agent)`, docs, and runtime introspection aligned after the service export redirects to the Rust wrapper.
   - Proof: `test_rust_agent_class_metadata_matches_browser_use_service_surface`.

118. Terminal main Codex session rerun compatibility
   - The current terminal `origin/main` baseline is now the active Rust core ground truth for this integration.
   - Terminal branch `magnus/browser-use-rust-main-integration` adds `run-codex-session`, so Browser Use-style `Agent.follow_up()` can append a follow-up turn and rerun the same terminal session through the Codex backend instead of depending on the older terminal integration branch.
   - Proof: terminal `cargo test -q -p browser-use-cli run_codex_session_command_accepts_task_id_and_model -- --nocapture`.
   - Proof: `browser-use-terminal run-codex-session --help` exposes `<TASK_ID>` and `--model`.
   - Proof: Python `Agent.run()` followed by `Agent.follow_up()` against the rebuilt current-main terminal binary completed successfully.
   - Current-main refresh: terminal `origin/main` fetched at `ee3ce69`; terminal integration head is `8c8dd8a` with only the `run-codex-session` commit on top.

119. Rust Agent runtime signature parity
   - The service export now copies Browser Use's original Agent `inspect.signature` metadata onto the Rust-backed replacement for the class constructor and common callable methods.
   - This removes string-annotation drift from the Rust wrapper and keeps docs, runtime introspection, and dependency-injection tooling aligned with the Browser Use Agent interface after the redirect.
   - Proof: `test_rust_agent_runtime_signatures_match_browser_use_callable_surface`.

120. Rust Agent terminal stream-error reconstruction
   - Terminal current-main `stream_error` events are now reconstructed as Browser Use history errors instead of being collapsed into the generic missing-final-result fallback.
   - This gives Python callers accurate diagnostics for cloud and benchmark runs where the terminal core reaches the browser but the model stream fails before `session.done`.
   - Proof: `test_rust_history_surfaces_terminal_stream_error_message`.
   - Evidence: real_v8 cloud task `18` reached Browser Use cloud and emitted terminal `stream_error` provider messages before this reconstruction fix.

121. Rust Agent terminal token-count usage reconstruction
   - Terminal current-main `token_count` events are now reconstructed into Browser Use `UsageSummary` totals.
   - The wrapper uses the latest cumulative `total_token_usage` snapshot so Python callers see prompt, cached prompt, completion, total token, and per-model usage values for terminal-main runs.
   - Proof: `test_rust_history_reconstructs_terminal_token_count_usage`.

122. Rust Agent terminal browser-script URL reconstruction
   - Terminal current-main `tool.output` events from browser scripts are now scanned for page URL/title fields and reconstructed into Browser Use `BrowserStateHistory`.
   - This makes `AgentHistoryList.urls()` reflect pages visited by the Rust terminal core instead of returning an empty URL when terminal main emits browser state through script output summaries.
   - Proof: `test_rust_history_reconstructs_terminal_browser_script_urls`.

123. Rust Agent class doc metadata parity
   - The Rust-backed replacement now mirrors Browser Use's original `Agent.__doc__` metadata.
   - This keeps docs, runtime introspection, and service-export class metadata aligned after `browser_use.agent.service.Agent` redirects to the Rust wrapper.
   - Proof: `test_rust_agent_class_metadata_matches_browser_use_service_surface`.

124. Rust terminal tool-call action history reconstruction
   - Rust terminal `tool.started` events are now reconstructed into Browser Use action models for `AgentHistoryList` consumers.
   - This makes `history.model_actions()`, `history.action_names()`, `history.last_action()`, and `history.action_history()` reflect terminal tool calls instead of staying empty when the Rust core ran browser tools.
   - Proof: `test_rust_history_reconstructs_terminal_tool_call_actions`.

125. Rust terminal completion done-action reconstruction
   - Successful terminal `session.done` events now synthesize a Browser Use `done` action when the terminal model did not emit one explicitly.
   - This keeps completed Rust-backed histories consistent for `history.last_action()`, `history.action_names()`, `history.model_actions_filtered(['done'])`, and action-history consumers that expect a final Browser Use completion action.
   - Proof: `test_rust_history_synthesizes_done_action_from_terminal_completion`.

126. Rust terminal streamed model output reconstruction
   - Terminal `model.stream_delta`/`model.delta` events are now reconstructed into Browser Use `AgentOutput.memory`, and `model.thinking_delta` events are reconstructed into `AgentOutput.thinking`.
   - The reducer mirrors terminal current-main retry semantics by clearing stale streamed text after `model.turn.request`, `model.turn.retry`, and `model.turn.error`, and de-duplicates prefix-style deltas before exposing `history.model_outputs()` and `history.model_thoughts()`.
   - Proof: `test_rust_history_reconstructs_terminal_streamed_model_thoughts`.

127. Rust terminal tool-failure error reconstruction
   - Terminal `tool.failed` events now surface their concrete tool name and error message in Rust-backed Browser Use histories when no final `session.done` result is available.
   - This keeps `history.errors()` and final action errors actionable instead of falling back to the generic "Rust terminal session did not produce a final result" message after the terminal core already recorded the failure.
   - Proof: `test_rust_history_surfaces_terminal_tool_failure_message`.

128. Rust terminal screenshot path reconstruction
   - Terminal browser-script image events now populate Browser Use `BrowserStateHistory.screenshot_path`.
   - This makes `history.screenshot_paths()` and `history.screenshots()` work for Rust-backed histories when terminal current-main records `tool.image` events or image paths on `tool.output`.
   - Proof: `test_rust_history_reconstructs_terminal_screenshot_paths`.

129. Rust terminal artifact attachment reconstruction
   - Terminal non-image artifact events are now reconstructed into Browser Use `ActionResult.attachments`.
   - This covers `tool.output` artifact lists, duplicate `artifact.created` records, spilled tool-output artifacts, and terminal `session.done` result files while keeping image artifacts on the screenshot path surface.
   - Proof: `test_rust_history_reconstructs_terminal_artifact_attachments`.

130. Rust terminal model-turn step reconstruction
   - Current-main terminal runs are now reconstructed into one Browser Use `AgentHistory` item per `model.turn.request` block instead of collapsing every run into a single synthetic step.
   - This makes `number_of_steps()`, `model_outputs()`, `model_thoughts()`, `action_history()`, `urls()`, screenshot paths, and final done state follow Browser Use step semantics while preserving collapsed behavior for event logs without terminal model-turn boundaries.
   - Proof: `test_rust_history_reconstructs_terminal_model_turn_steps`.

131. Rust terminal cancellation and tool-abort reconstruction
   - Terminal `session.cancelled` events are now reconstructed as Browser Use history errors instead of falling through to the generic missing-result fallback.
   - Terminal `tool.aborted` events now surface action-level abort messages and final history errors when no terminal completion result is available.
   - Proof: `test_rust_history_surfaces_terminal_cancellation_and_tool_abort_messages`.

132. Rust terminal model tool-call reconstruction
   - Terminal `model.tool_call` and provider `model.response.output_item` function-call records are now reconstructed into Browser Use action models.
   - This preserves model action history for terminal replay/import logs that contain model call records instead of, or in addition to, `tool.started`, and de-duplicates repeated call ids.
   - Proof: `test_rust_history_reconstructs_terminal_model_tool_call_actions`.

133. Rust terminal response-item model text reconstruction
   - Terminal `model.response.output_item` assistant message records are now reconstructed into Browser Use `AgentOutput.memory`.
   - This preserves model commentary for replay/import logs that store assistant text as response items instead of live `model.stream_delta` events, while still de-duplicating overlapping stream prefixes.
   - Proof: `test_rust_history_reconstructs_terminal_response_item_model_text`.

134. Rust terminal response-input tool-result reconstruction
   - Terminal `model.response.input_item` function-call-output records are now reconstructed into Browser Use `ActionResult` entries.
   - This preserves tool result text for provider-shaped replay/import logs that store tool outputs as response input items instead of `tool.output` events.
   - Proof: `test_rust_history_reconstructs_terminal_response_input_item_tool_results`.

135. Rust terminal finished-tool result reconstruction
   - Terminal `tool.finished` events now reconstruct Browser Use `ActionResult` entries when no richer tool output event was recorded for the same call id.
   - The fallback text mirrors terminal current-main synthetic tool-result semantics while preserving concrete `tool.output`, failure, abort, and provider input-item results when those are present.
   - Proof: `test_rust_history_reconstructs_terminal_tool_finished_results`.

136. Rust terminal nested model-usage reconstruction
   - Terminal `model.usage` events with provider usage nested under a `usage` object now populate Browser Use `UsageSummary`.
   - This preserves prompt, cached prompt, completion, cost, and invocation data for replay/import logs that use terminal's nested usage shape instead of the older flat usage payload.
   - Proof: `test_rust_history_reconstructs_terminal_nested_model_usage`.

137. Rust terminal response-item reasoning reconstruction
   - Terminal `model.response.output_item` reasoning records now populate Browser Use `AgentOutput.thinking`.
   - This preserves provider replay/import reasoning summaries, including OpenAI Responses `summary_text` parts, while keeping assistant message response items on the existing memory surface.
   - Proof: `test_rust_history_reconstructs_terminal_response_item_reasoning`.

138. Rust terminal session-rollback reconstruction
   - Terminal `session.rollback` events now filter rolled-back user turns before Browser Use history reconstruction.
   - This keeps rolled-back model outputs, tool actions, tool results, usage, attachments, and final results off Python-visible surfaces such as `action_names()`, `model_outputs()`, `action_history()`, and `final_result()`.
   - Proof: `test_rust_history_applies_terminal_session_rollback`.

139. Rust terminal session-compaction replay boundary reconstruction
   - Terminal `session.compacted` events now establish the Browser Use history replay boundary before action/result reconstruction.
   - This keeps pre-compaction model outputs, tool actions, tool results, usage, attachments, and final results off Python-visible history surfaces while preserving post-compaction run data.
   - Proof: `test_rust_history_applies_terminal_session_compaction_boundary`.

140. Rust terminal reasoning-token usage reconstruction
   - Terminal `token_count` usage snapshots now preserve `reasoning_output_tokens` on Browser Use `UsageSummary` surfaces.
   - The wrapper treats reasoning tokens as completion usage, matching Browser Use's LLM usage accounting, and preserves terminal-reported cumulative `total_tokens` instead of recomputing totals from visible output tokens only.
   - Proof: `test_rust_history_reconstructs_terminal_reasoning_token_usage`.

141. Rust terminal unkeyed tool-result reconstruction
   - Terminal tool result events without `tool_call_id` are now paired back to Browser Use action results by ordered tool name fallback.
   - This preserves CLI/manual tool paths such as `python`, where `tool.started`, `tool.output`, and `tool.finished` can omit call ids, while explicit call-id matching still takes precedence and transient streaming chunks stay out of final action history.
   - Proof: `test_rust_history_reconstructs_terminal_unkeyed_tool_results`.

142. Rust terminal text-artifact attachment reconstruction
   - Terminal `tool.output` events with `text_artifact` now expose the spilled text artifact on Browser Use attachment surfaces.
   - This preserves current-main Python worker outputs that truncate large text in `text` while carrying the full artifact under `text_artifact`, including the synthesized final `done.files_to_display`.
   - Proof: `test_rust_history_reconstructs_terminal_text_artifact_attachments`.

143. Rust terminal structured tool-output reconstruction
   - Terminal tool outputs now fall back to structured `summary`, `data`, and `outputs` payloads when no textual `text`, `output`, `result`, or text content is present.
   - This preserves current-main browser/Python tool results that return structured payloads instead of transcripts, so Browser Use `action_history()` and `ActionResult` surfaces do not show `None` for successful actions.
   - Proof: `test_rust_history_reconstructs_terminal_structured_tool_output_results`.

144. Rust terminal session-interrupted reconstruction
   - Terminal `session.interrupted` events are now reconstructed as Browser Use history errors instead of falling through to the generic missing-result fallback.
   - This preserves interrupted subagent/session lifecycle outcomes on Python-visible `errors()`, `is_done()`, and final `ActionResult.error` surfaces.
   - Proof: `test_rust_history_surfaces_terminal_session_interrupted_message`.

145. Rust terminal browser live-URL reconstruction
   - Terminal `browser.live_url` events are now reconstructed into Browser Use `BrowserStateHistory`.
   - This preserves Rust current-main live browser URLs on Python-visible `AgentHistoryList.urls()`, step state, telemetry, callbacks, and saved conversation snapshots even when no `browser.state` event is present.
   - Proof: `test_rust_history_reconstructs_terminal_browser_live_url`.

146. Rust terminal capture-curation GIF attachment reconstruction
   - Terminal `capture.curation` events now expose their saved `gif_path` on Browser Use attachment surfaces.
   - This preserves Rust current-main browser summary GIFs in Python-visible final `ActionResult.attachments` and synthesized `done.files_to_display`, even though generic image artifacts remain filtered from file attachments.
   - Proof: `test_rust_history_reconstructs_terminal_capture_curation_gif_attachment`.

147. Rust terminal tool-output-delta reconstruction
   - Terminal `tool.output_delta` streaming chunks are now folded into Browser Use action results when no final textual `tool.output` arrives.
   - This preserves current-main unified exec streamed stdout/stderr on Python-visible `ActionResult.extracted_content`, `long_term_memory`, and `action_history()` instead of falling back to synthetic tool-completion text.
   - Proof: `test_rust_history_reconstructs_terminal_tool_output_deltas`.

148. Rust terminal paired tool-abort precedence
   - Terminal tool calls that emit `tool.aborted` followed by the paired `tool.failed` now keep the abort-specific Browser Use error.
   - This preserves current-main user-aborted tool semantics on Python-visible `history.errors()`, per-action `ActionResult.error`, and final fallback errors instead of downgrading them to generic tool-failure messages.
   - Proof: `test_rust_history_preserves_terminal_tool_abort_when_failed_event_follows`.

149. Rust terminal exec-command end-output reconstruction
   - Terminal `exec_command.end` final output is now reconstructed into Browser Use action results when no generic textual `tool.output` is present.
   - This preserves current-main unified exec final stdout/stderr on Python-visible `ActionResult.extracted_content`, `long_term_memory`, and `action_history()` even if only the exec lifecycle events were recorded.
   - Proof: `test_rust_history_reconstructs_terminal_exec_command_end_output`.

150. Rust terminal exec-command failure reconstruction
   - Terminal `exec_command.end` events with nonzero exit codes now surface Browser Use action and history errors when no explicit `tool.failed` or `tool.aborted` event is present.
   - This preserves current-main unified exec failures on Python-visible `history.errors()` and per-action `ActionResult.error` while retaining the final command output in action memory.
   - Proof: `test_rust_history_surfaces_terminal_exec_command_end_failure`.

151. Rust terminal command-waiting reconstruction
   - Terminal `command.waiting` events now reconstruct live unified-exec process results when no generic textual `tool.output` is present.
   - This preserves current-main long-running command state on Python-visible `ActionResult.extracted_content`, `long_term_memory`, and `action_history()` instead of falling back to synthetic tool-completion text.
   - Proof: `test_rust_history_reconstructs_terminal_command_waiting_result`.

152. Rust terminal exec-command output-delta reconstruction
   - Terminal `exec_command.output_delta` events now reconstruct live unified-exec process output when no generic final `tool.output` is present.
   - This preserves current-main exec-specific streamed `chunk` payloads on Python-visible `ActionResult.extracted_content`, `long_term_memory`, and `action_history()` while avoiding duplicate text when terminal also emits the paired generic `tool.output_delta`.
   - Proof: `test_rust_history_reconstructs_terminal_exec_command_output_deltas`.

153. Rust terminal tool-image action attachments
   - Terminal `tool.image` events and tool-output `images` payloads now attach their image paths to the matching Python-visible `ActionResult`.
   - This preserves current-main screenshot/image artifacts on the per-action Browser Use API surface while keeping final `done.files_to_display` limited to file/result attachments.
   - Proof: `test_rust_history_attaches_terminal_tool_images_to_actions`.

154. Rust terminal operational failure reconstruction
   - Terminal operational failure events now surface as Python-visible history errors when the session has no final result.
   - This preserves current-main browser cloud shutdown, browser cleanup, browser bridge, command write, compaction, and final-answer-not-ready failures on `history.errors()` and the final `ActionResult.error` instead of falling back to a generic missing-result error.
   - Proof: `test_rust_history_surfaces_terminal_operational_failure_events`.

155. Rust terminal subagent-completion result reconstruction
   - Terminal `agent.completed` events now fall back to their nested `payload.result` as the Browser Use final result when no `session.done` result is present.
   - This matches terminal protocol result reconstruction for parent/subagent completion histories while preserving `session.done` precedence when both results exist.
   - Proof: `test_rust_history_reconstructs_terminal_agent_completed_result`.

156. Rust terminal subagent-failure reconstruction
   - Terminal `agent.failed` and `agent.cancelled` events now surface nested subagent failure and cancellation details on Python-visible history errors.
   - This preserves current-main child-agent failure payloads that store error text under nested `payload.failure`, plus sensible cancellation/failure fallbacks when no text is present.
   - Proof: `test_rust_history_surfaces_terminal_subagent_failure_events`.

157. real_v8 smoke step-timeout bridge
   - `examples/rust_agent/real_v8_smoke.py` now accepts `--step-timeout` and `BU_STEP_TIMEOUT`, then passes the value to the Rust-backed Browser Use `Agent(step_timeout=...)`.
   - This keeps benchmark cloud smokes on the public Browser Use timeout interface instead of requiring task-specific runner edits when real_v8 tasks exceed the 120-second default.
   - Proof: `test_real_v8_smoke_passes_step_timeout_to_agent`.

158. Rust Agent sensitive-data domain warning parity
   - The Rust-backed Agent now mirrors Browser Use's sensitive-data safety warnings when credentials are supplied without `allowed_domains`, or when domain-scoped sensitive data is not covered by the configured allowed-domain patterns.
   - Warnings include placeholder/domain metadata but do not log raw secret values.
   - Proof: `test_rust_agent_warns_about_sensitive_data_domain_constraints`.

159. Rust Agent close lifecycle parity
   - `Agent.close()` now mirrors Browser Use cleanup by calling `browser_session.kill()` when a browser session is present and `browser_profile.keep_alive` is not enabled.
   - Keep-alive sessions are preserved, and lightweight custom sessions without a Browser Use browser process remain safe.
   - Proof: `test_rust_agent_close_kills_non_keep_alive_browser_session`.

160. Rust Agent close cleanup-error parity
   - `Agent.close()` now mirrors Browser Use cleanup resilience by logging browser-session cleanup failures instead of propagating them to callers.
   - This keeps close idempotent and safe for user cleanup/finally blocks even when a supplied BrowserSession fails during `kill()`.
   - Proof: `test_rust_agent_close_logs_cleanup_errors_without_raising`.

161. Rust Agent run telemetry parity
   - Terminal-backed `Agent.run()` and `Agent.follow_up()` now emit Browser Use `AgentTelemetryEvent` records from reconstructed Rust history.
   - Telemetry captures task/model metadata, URLs, usage, final result, success, and terminal process errors, while telemetry failures are logged and do not break the returned history.
   - Proof: `test_rust_agent_run_records_terminal_telemetry`.

162. Rust Agent run session-state parity
   - Terminal-backed `Agent.run()` and `Agent.follow_up()` now initialize Browser Use run lifecycle state before execution.
   - The wrapper sets `_session_start_time`, `_task_start_time`, and flips `state.session_initialized`, matching the observable Python Agent state callers can inspect around completed runs.
   - Proof: `test_rust_agent_run_initializes_browser_use_session_state`.

163. Rust Agent event-bus run lifecycle parity
   - Terminal-backed `Agent.run()` and `Agent.follow_up()` now dispatch Browser Use cloud event-bus lifecycle events around Rust core execution.
   - The wrapper emits `CreateAgentSessionEvent` once per Browser Use session, `CreateAgentTaskEvent` at each run start, and `UpdateAgentTaskEvent` after reconstructed terminal history is available.
   - Run event buses are stopped after completion and recreated before later runs when needed, matching Browser Use's per-run eventbus lifecycle without leaving pending no-handler events in local tests.
   - Proof: `test_rust_agent_run_dispatches_browser_use_lifecycle_events`.

164. Rust Agent GIF output-file event parity
   - Terminal-backed `Agent.run()` and `Agent.follow_up()` now dispatch `CreateAgentOutputFileEvent` when Browser Use `generate_gif` creates an agent history GIF.
   - The output-file event carries the generated GIF file name, `image/gif` content type, task ID, and base64 file content before the run eventbus is stopped.
   - Proof: `test_rust_agent_dispatches_gif_output_file_event`.

## Current Verification

- `python3 -m py_compile browser_use/agent/service.py browser_use/rust/service.py browser_use/rust/__init__.py browser_use/__init__.py tests/ci/test_rust_agent.py examples/rust_agent/basic.py examples/rust_agent/real_v8_smoke.py`
- `uv run pytest -q tests/ci/test_rust_agent.py` (136 tests)
- `cargo build -q -p browser-use-cli` on terminal branch `magnus/browser-use-rust-main-integration`
- `cargo test -q -p browser-use-cli run_codex_session_command_accepts_task_id_and_model -- --nocapture`
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
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_pricing_cards_snapshot_surfaces_commercial_signals -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_sitemap_urls_snapshot_discovers_public_routes -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_route_candidates_snapshot_discovers_spa_routes -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_network_resources_snapshot_surfaces_api_candidates -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_json_api_records_extracts_nested_record_arrays -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_tabular_data_records_normalizes_exports -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_investor_documents_snapshot_classifies_visible_links -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_document_links_snapshot_classifies_filing_documents -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_shopify_products_api_normalizes_catalog_pages -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_product_records_snapshot_normalizes_catalog_products -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_pagination_helpers_click_until_stable -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_result_count_snapshot_parses_visible_count_evidence -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_contact_details_snapshot_normalizes_candidates -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_location_records_snapshot_normalizes_directory_records -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_form_control_helpers_toggle_labeled_controls -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_select_helpers_choose_native_select_options -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_form_field_helpers_match_labels_and_fill_semantically -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_autocomplete_helpers_select_visible_suggestions -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_action_helpers_click_named_controls -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_overlay_helpers_dismiss_cookie_actions -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_extract_paginated_grid_rows_collects_pages -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_semantic_scholar_helpers_normalize_paper_graphs -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_openreview_notes_normalizes_content_values -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_nobel_prize_api_normalizes_official_links -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_wikidata_sparql_normalizes_entity_bindings -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_wikidata_education_award_cascade_resolves_and_queries -- --nocapture`
- `CARGO_INCREMENTAL=0 cargo test -q -p browser-use-browser browser_script_grid_rows_builds_fanout_manifests -- --nocapture`
- Managed-headless end-to-end:
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=managed-headless BU_TASK='Open https://example.com and report the page title only.' BU_MAX_STEPS=12 timeout 300 uv run python examples/rust_agent/basic.py`
  - Output: `Example Domain`
- Remote-CDP end-to-end:
  - Launch external Chromium with `--remote-debugging-port=49333`.
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_CDP_URL=http://127.0.0.1:49333 BU_TASK='Open https://example.com and report the page title only.' BU_MAX_STEPS=12 timeout 300 uv run python examples/rust_agent/basic.py`
  - Output: `Example Domain`
- Browser Use cloud end-to-end:
  - Source `/home/exedev/.evaluation_tool_env`.
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=cloud BU_TASK='Open https://example.com and report the page title only.' BU_MAX_STEPS=12 timeout 300 uv run python examples/rust_agent/basic.py`
  - Output: `Example Domain`
- real_v8 cloud-browser end-to-end:
  - Source `/home/exedev/.evaluation_tool_env`.
  - `REAL_V8_DATASET=/home/exedev/Developer/evaluations-internal/datasets/real_v8.json BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=cloud timeout 900 uv run python examples/rust_agent/real_v8_smoke.py --task-id 18 --max-steps 30 --step-timeout 600`
  - Output: `{"task_id": "18", "successful": true, "final_result": "Paramjit Uppal, Founder"}`
- real_v8-2 cloud-browser end-to-end:
  - Source `/home/exedev/.evaluation_tool_env`.
  - `REAL_V8_DATASET=/home/exedev/Developer/evaluations-internal/datasets/real_v8-2.json BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=cloud timeout 900 uv run python examples/rust_agent/real_v8_smoke.py --task-id 1 --max-steps 25 --step-timeout 600`
  - Output: `{"task_id": "1", "successful": true, "final_result": "The 2024 Nobel Prize in Physics ..."}`
- Existing-session follow-up end-to-end:
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_RUST_BROWSER_MODE=managed-headless BROWSER_USE_RUST_STATE_DIR=/tmp/browser-use-rust-followup-smoke timeout 420 uv run python - <<'PY' ...`
  - Output: first run `Example Domain`; follow-up `example.com`.
- Multi-feature Python API cloud end-to-end:
  - Source `/home/exedev/.evaluation_tool_env`, unset browser-mode overrides, and construct `Agent(..., browser_profile=BrowserProfile(use_cloud=True), register_new_step_callback=..., register_done_callback=..., save_conversation_path=..., step_timeout=300)`.
  - Output: first run `Example Domain`; follow-up `example.com`; callback sequence `step, done, step, done`; two conversation JSON snapshots written; terminal session id present.
- Structured-output Python API cloud end-to-end:
  - Source `/home/exedev/.evaluation_tool_env`, unset browser-mode overrides, and construct `Agent(..., browser_profile=BrowserProfile(use_cloud=True), output_model_schema=PageAnswer, step_timeout=300)`.
  - Output: final result `{"title":"Example Domain","host":"example.com","ok":true}` and `history.structured_output` is a `PageAnswer(title="Example Domain", host="example.com", ok=True)`.
- Available-file Python API end-to-end:
  - Construct `Agent(..., available_file_paths=[/tmp/.../input-note.txt], step_timeout=240)` with a temp file containing `secret answer: file-bridge-ok`.
  - Output: final result `file-bridge-ok`, no history errors, and the agent preserves the supplied file path in `agent.available_file_paths`.
- Initial-actions Python API end-to-end:
  - Construct `Agent(task="Report only the current page title.", initial_actions=[{"go_to_url": {"url": "https://example.com"}}], directly_open_url=False, step_timeout=240)`.
  - Output: final result `Example Domain`, no history errors, converted initial action `navigate(url="https://example.com")`, and history URLs include `https://example.com`.
- Sensitive-data Python API end-to-end:
  - Construct `Agent(..., sensitive_data={"username": "...", "https://example.com": {"password": "..."}}, step_timeout=180)`.
  - Output: final result `username, password`, no history errors, sanitized context exposes only placeholder names, and raw secret values are absent from task, stdout/stderr, terminal events, and final result.
- BrowserProfile domain-constraint Python API end-to-end:
  - Construct `Agent(..., browser_profile=BrowserProfile(allowed_domains=["example.com"], prohibited_domains=["iana.org"]), step_timeout=240)`.
  - Output: final result `Example Domain`, no history errors, preserved allowed/prohibited domain lists, history URLs include `example.com`, and no history URL includes `iana.org`.
- real_v8 remote-CDP end-to-end:
  - Launch external Chromium with `--remote-debugging-port=49333`.
  - `BROWSER_USE_TERMINAL_BINARY=/home/exedev/Developer/terminal/target/debug/browser-use-terminal BROWSER_USE_CDP_URL=http://127.0.0.1:49333 timeout 600 uv run python examples/rust_agent/real_v8_smoke.py --task-id 18 --max-steps 30`
  - Output: `{"task_id": "18", "successful": true, "final_result": "Paramjit Uppal, Founder"}`

## Not Verified Yet

- A broader real_v8 cloud-browser sweep is in progress. Passing live benchmark tasks: real_v8 `18`, real_v8-2 `1`.
- Non-passing sweep data points so far:
  - real_v8 `11`: repository paths in the task appear stale for current `openai/codex`, and the run later hit the model context window while trying to retrieve large source contents.
  - real_v8 `13`: provider/tool-call decode error, `EOF while parsing an object`, before a final result.
  - real_v8 `5`: generated browser-script/provider failures while extracting Sziget ticket pricing, including invalid JavaScript and a provider request error.
  - real_v8-2 `3`: product-page discovery task did not produce a final result before the configured `Agent(step_timeout=600)` terminal subprocess timeout.
