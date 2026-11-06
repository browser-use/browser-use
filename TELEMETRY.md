# Telemetry

browser-use sends anonymized usage telemetry to PostHog so we can see which models, browsers and helpers work and where
runs fail. Turn it off with `ANONYMIZED_TELEMETRY=false` (any value not starting with `t`, `y` or `1`), for the library
and the `browser-use` CLI alike.

## Never sent

- the task, follow-up tasks, `extend_system_message`
- the result: `final_result()`, structured output, partial results, the model's text
- code the model writes (cells, `finish_from_repl` expressions)
- text typed into pages (`type_text`, `fill_input`, `bu.type`), `sensitive_data` names or values, typed secrets
- page content: titles, HTML, screenshots, extracted data, file names, `js()` expressions, cdp() parameters
- full URLs: only the hostname is kept; paths, queries, fragments, ports, users and passwords are dropped
- CDP endpoints: only their kind (`browser-use-cloud`, `localhost`, `private`, `public-other`), never the hostname. A
  Browser Use cloud browser's CDP hostname is its id, and that alone can drive the browser
- names the model's code chooses: a module that is neither in the standard library nor installed counts as `other`, an
  exception class it defined as `custom`, a `cdp()` method that is not in the CDP protocol as `invalid`
- error messages and tracebacks: only the exception class (`ValueError`, `ModelNotFoundError`)
- PostHog exception autocapture is off: no uncaught exception from your process is sent

## agent_event (one per `Agent.run()`)

Every field is a number, a bool, an enum, a hostname, or a name chosen by browser-use, the developer, Python or an
installed package (model id, helper, tool, module, exception class, CDP method). Names are cut at 64 characters.

| group | fields |
|---|---|
| install | `version`, `source` (pip, uv, editable, git, unknown), `agent_type` (`pydantic`), `run_id` (random per run), `schema_version` (2) |
| environment | `os`, `os_release`, `arch`, `python_version`, `pydantic_ai_version`, `browser_harness_version`, `is_docker`, `is_ci`, `is_notebook` |
| configuration | `model` (id as passed, e.g. `bu-auto`, `gpt-6-luna`), `model_provider`, `reasoning`, `mode` (default, ultrafast), `max_steps`, `timeout_s`, `structured_output`, `output_schema_fields`, `custom_tools` (names of your `Tools` actions), `sensitive_data_count`, `sensitive_data_domain_scoped`, `extend_system_message` (bool), `custom_workspace`, `follow_up`, `task_chars` (length only) |
| browser | `browser_mode` (cloud, chromium, chrome, cdp), `cdp_url` (cdp mode only: `browser-use-cloud`, `localhost`, `private` or `public-other`), `keep_alive`, `cloud_profile` (bool, never the id or name), `cloud_proxy_country`, `cloud_timeout_min`, `live_view`, `browser_start_seconds` |
| outcome | `status` (completed, timeout, max_steps, error, cancelled), `success`, `max_steps_hit`, `timed_out`, `finish_via` (finish, finish_from_repl, text), `partial_used`, `error_type`, `output_chars` (length only), `total_duration_seconds` |
| model | `steps`, `model_requests`, `total_input_tokens`, `total_output_tokens`, `prompt_cached_tokens`, `cache_write_tokens`, `total_tokens`, `cost_usd`, `tool_calls` (calls per tool name), `retry_prompts` |
| REPL | `cells`, `cell_errors`, `cell_seconds`, `cell_error_types` (class -> count; `CellTimeout`, `WorkerExited` for restarts, `custom` for a class the model's code defined), `helper_counts` (browser-harness helpers, `screenshot`, `type_secret`, `bu.<method>` -> calls), `cdp_method_counts` (the agent's own `cdp()` calls by CDP protocol method; any other string counts as `invalid`), `imports` (top-level modules cells import; `other` when neither in the standard library nor installed), `screenshots` |
| browsing | `domains` (hostnames of pages the agent navigated to, or read with `page_info()`/`current_tab()` after its first navigation; never the tab `Browser('chrome')` attaches to before that, nor your other tabs), `domain_count`, `navigations`, `captcha_started`, `captcha_solved`, `captcha_failed` (Browser Use Cloud solver events), `domain_restrictions` (bool: `allowed_domains`, `prohibited_domains` or `block_ip_addresses` is set; never the domains), `domain_blocks` (navigations refused or blocked and tabs reset by them), `downloads_started` (one per download, however many events announce it), `downloads` (cloud files copied; a cloud browser's copy of a JSON page it displayed is not copied), `download_exts` (extension -> count) |

Maps and lists keep their 50 most frequent keys.

## cli_event (the `browser-use` CLI)

The CLI runs browser-harness, whose `cli_event` would include the piped code, its output, helper arguments and error
text. The browser-use CLI removes those before the event is sent and keeps `command`, `action`, `exit_code`,
`duration_seconds`, `task_length`, `output_length`, `step_count`, `browser`, `cdp_url` (its kind, as above), `client`,
`client_version`, `agent_client`, `model`, `model_provider`, the browser-harness environment fields, plus
`helper_counts` (helper name -> calls), `helper_errors` and `schema_version` (2).

## Identity

Events carry one anonymous id per machine: `BROWSER_USE_DEVICE_ID` if set, else a random id stored in
`~/.config/browseruse/device_id` (`BROWSER_USE_CONFIG_DIR` moves it), else (that file cannot be written) a hash of the
machine's MAC address and hostname. PostHog derives a location from the request IP (GeoIP).
