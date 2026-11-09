# Telemetry

browser-use sends anonymized usage telemetry to PostHog so we can see which models, browsers and helpers work, where
runs spend their time and where they fail. Turn it off with `ANONYMIZED_TELEMETRY=false` (any value not starting with
`t`, `y` or `1`), for the library and the `browser-use` CLI alike. Off means off: no event, no background thread, no file
written.

## Never sent

- the task, follow-up tasks, `extend_system_message`
- the result: `final_result()`, structured output, partial results, the model's text
- code the model writes (cells, `finish_from_repl` expressions); repeated code is detected by a hash that never leaves
  the process
- text typed into pages (`type_text`, `fill_input`, `bu.type`), `sensitive_data` names or values, typed secrets
- page content: titles, HTML, screenshots, extracted data, file names, `js()` expressions, cdp() parameters
- full URLs: only the hostname of an http(s) URL is kept, and only when it is a DNS name or an IP address (a
  navigation to `https://the task as text/` records no host); paths, queries, fragments, ports, users and passwords
  are dropped. Revisited pages are detected by URL hashes kept inside the REPL worker; only counts leave it
- hostnames that alone grant access: tunnels (`*.trycloudflare.com`, `*.ngrok-free.app`, `*.ngrok.io`, `*.ngrok.app`,
  `*.loca.lt`, `*.devtunnels.ms`), cloud IDE ports (`*.github.dev`, `*.app.github.dev`, `*.gitpod.io`, `*.repl.co`,
  `*.replit.dev`, `*.csb.app`), Lambda function URLs (`*.lambda-url.<region>.on.aws`) and preview deploys
  (`*.vercel.app` names with a deploy id or `-git-`, `*.netlify.app` names with `--`) are sent as that provider pattern
- CDP endpoints: only their kind (`browser-use-cloud`, `localhost`, `private`, `public-other`), never the hostname. A
  Browser Use cloud browser's CDP hostname is its id, and that alone can drive the browser
- names the model's code chooses: a module that is neither in the standard library nor installed counts as `other`, an
  exception class it defined as `custom`, a `cdp()` method that is not in the CDP protocol as `invalid`, a tool name
  that is not one of the agent's tools as `invalid`, a model name a custom endpoint reports as `other` (below)
- error messages and tracebacks: only the exception class (`ValueError`, `ModelHTTPError`) and a provider's error code
  when it is at most 40 characters of `[a-z0-9_.]` (`rate_limit_exceeded`, `429`), else `other`
- paths: `browser_exe` is an enum from the executable's file name, `user_data_dir` and `chrome_profile` are bools, a
  `model` given as a local path (a vLLM or llama.cpp model) is sent as its last segment
- endpoints: `model_provider` is the provider's name (`openai`), never its `base_url`
- PostHog exception autocapture does not exist here: no uncaught exception from your process is sent

## agent_event (one per `Agent.run()`)

Every field is a number, a bool, an enum, a hostname, or a name chosen by browser-use, the developer, Python or an
installed package (model id, helper, tool, module, exception class, CDP method), or a list or map of those. Names are
cut at 64 characters. Times are integer milliseconds unless the name ends in `_seconds`.

| group | fields |
|---|---|
| install | `version`, `source` (pip, uv, editable, git, unknown), `agent_type` (`pydantic`), `run_id` (random per run; also the event's uuid), `schema_version` (3), `is_internal` (`BROWSER_USE_TELEMETRY_INTERNAL` is true: our own evals and tests), `$lib` (`browser-use`), `$lib_version` |
| environment | `os`, `os_release`, `arch`, `python_version`, `pydantic_ai_version`, `browser_harness_version`, `is_docker`, `is_ci`, `is_notebook` |
| configuration | `model` (id as passed, e.g. `bu-auto`, `gpt-6-luna`; a local path as its last segment, a URL as `other`), `model_provider` (its name, e.g. openai, never its base_url), `reasoning`, `mode` (default, ultrafast), `max_steps`, `timeout_s`, `structured_output`, `output_schema_fields`, `custom_tools` (names of your `Tools` actions), `sensitive_data_count`, `sensitive_data_domain_scoped`, `extend_system_message` (bool), `custom_workspace`, `follow_up`, `task_chars` (length only), `web_search`, `use_vision`, `highlight_actions`, `max_context_chars_set` (bool), `gateway` (bool: the Browser Use gateway serves the model), `model_api` (responses, chat, anthropic, google, other), `compaction_mode` (server, client), `context_window`, `sync` (run_sync), `run_in_process` (1 for the process's first run, 2, ...), `concurrent_runs` (other runs in progress in this process when this one started) |
| browser | `browser_mode` (cloud, chromium, chrome, cdp), `cdp_url` (cdp mode only: `browser-use-cloud`, `localhost`, `private` or `public-other`), `keep_alive`, `cloud_profile` (bool, never the id or name), `cloud_proxy_country`, `cloud_timeout_min`, `live_view`, `captcha_solver` (cloud only), `headless`, `chrome_profile` (bool), `user_data_dir` (bool), `browser_exe` (chrome, chromium, edge, other; from `executable_path`), `domain_restrictions` (bool), `allowed_domains_n`, `prohibited_domains_n` (counts, never the domains), `block_ip_addresses`, `browser_start_seconds` |
| outcome | `status` (completed, timeout, max_steps, error, cancelled, crashed), `success`, `max_steps_hit`, `timed_out`, `finish_via` (finish, finish_from_repl, text), `partial_used`, `error_type` (exception class; `PreflightError` when the key, model or search check failed before the browser started), `error_phase` (preflight, browser_start, model, cell, delivery, budget, shutdown; null when completed), `budget_hit` (max_steps, timeout, browser_gone: what forced the delivery-only turn), `delivery_turn` (bool: a delivery-only turn ran), `delivery_repairs` (placeholder, missing-file, split-delivery and text repairs), `output_chars` (length only), `total_duration_seconds` |
| time | `ms_total` (run() wall time), `ms_preflight` (key, model and search check), `ms_browser_start` (null when a keep_alive browser is reused), `ms_repl_start` (REPL worker starts and restarts), `ms_model` (model request attempts, failed ones included), `ms_ttft` (time to the first stream event, streamed OpenAI Responses requests only), `ms_cells` (python cells, parent side), `ms_helpers` (helper calls inside cells), `ms_waits` (the part of ms_helpers in `wait`, `wait_for_load`, `wait_for_network_idle`, `wait_for_element`, `solve_captcha`, `bu.settle`), `ms_cdp` (every CDP call the REPL worker made), `ms_compaction` (summary requests and context-window recovery), `ms_retry_sleep` (provider Retry-After waits), `ms_delivery` (from the delivery-only turn's start to the loop's end), `ms_shutdown` (REPL close, browser stop, cloud downloads), `ms_other` (ms_total minus preflight, browser start, model, cells, compaction, retry sleep and shutdown), `first_nav_step`, `first_nav_ms`, `first_ok_action_ms` (first cell without an error that navigated or clicked or typed) |
| model | `steps`, `model_requests`, `model_attempts` (failed attempts included), `total_input_tokens`, `total_output_tokens`, `prompt_cached_tokens`, `cache_write_tokens`, `total_tokens`, `cost_usd`, `cost_search_usd`, `cost_compaction_usd`, `tool_calls` (calls per tool name), `invalid_tool_calls`, `retry_prompts`, `retries` (cause -> count: provider_transient, model_timeout, context_overflow, compaction_unreadable, delivery_placeholder, delivery_missing_files, delivery_split, finish_expr_error, finish_schema, text_repair, text_tool_markup, text_schema, tool_args, custom_tool), `model_fails` (up to 30 `[step, ms, exception class, provider code]`), `length_finishes` (responses cut at max_tokens), `response_models` (model name a response reported -> responses, top 5; kept only when it matches `[A-Za-z0-9._:-]{1,64}` and the request went through the gateway or the name starts with the configured model's name, else `other`), `compactions` (up to 20 `[step, kind (1 client, 2 server, 3 context-window recovery), ms, tokens before, tokens after (-1 unknown), ok]`) |
| REPL | `cells`, `cell_errors`, `cell_seconds`, `cell_error_types` (class -> count; `CellTimeout`, `WorkerExited` for restarts, `custom` for a class the model's code defined), `helper_counts` (browser-harness helpers, `screenshot`, `type_secret`, `search`, `downloads`, `bu.<method>` -> calls), `helper_stats` (helper -> `[calls, errors, ms total, ms max]`; an error is a raise, even one the model's code caught), `cdp_method_counts` (the agent's own `cdp()` calls by CDP protocol method; any other string counts as `invalid`), `cdp_stats` (every CDP method the worker sent, helpers' included -> `[calls, errors, ms total, ms max]`), `imports` (top-level modules cells import; `other` when neither in the standard library nor installed), `screenshots` |
| browsing | `domains` (hostnames of pages the agent navigated to, or read with `page_info()`/`current_tab()` after its first navigation; never the tab `Browser('chrome')` attaches to before that, nor your other tabs), `domain_count`, `host_stats` (hostname -> `[steps, steps with an error, cell ms, captcha events, domain blocks, navigations, failed navigations]`, top 30), `navigations`, `revisit_navs` (navigations to a URL already seen), `nav_failures` (navigations that got Chrome's error page; that page, chrome-error://chromewebdata, is never counted as a host), `nav_errors` (Chrome net error code, such as ERR_NAME_NOT_RESOLVED, -> count, top 20; never the URL), `captcha_started`, `captcha_solved`, `captcha_failed` (Browser Use Cloud solver events), `domain_blocks` (navigations refused or blocked and tabs reset by `allowed_domains`/`prohibited_domains`), `downloads_started` (one per download, however many events announce it), `downloads` (cloud files copied; a cloud browser's copy of a JSON page it displayed is not copied), `download_exts` (extension -> count; `other` for one that is not a common file type, `none`) |
| struggle | `max_err_streak` (longest run of consecutive steps with a failing cell), `err_streaks_3` (runs of 3 or more), `streak_err`, `streak_kind`, `streak_helper` (most common error class, step kind and first helper in the longest streak), `repeat_fail_steps` (a failing step with the same error class and helpers as the previous failing one), `repeat_code_steps` (a step whose code equals the previous step's), `max_host_streak` (consecutive steps on one host without a new page), `last_progress_step` (last step without an error that opened a new page that loaded, called `checkpoint()` or delivered: finish, or the run's final text reply), `wasted_steps` (steps after it) |
| per step | parallel lists, one entry per model response, the first 50 and the last 150 of a longer run: `s_t` (ms from the run's start), `s_model_ms`, `s_ttft_ms` (-1 when not streamed), `s_in`, `s_out`, `s_cached`, `s_reason` (reasoning tokens, -1 when unknown), `s_finish` (stop, tool_call, length, content_filter, error, or empty), `s_tools` (comma-joined tool names), `s_cells`, `s_cell_ms`, `s_wait_ms`, `s_cdp_ms`, `s_err` (class of the step's last failing cell, or empty), `s_helpers` (up to 6 helpers, comma-joined, in first-use order), `s_kind` (deliver, captcha, nav, interact, search, files, wait, read, compute, none; a text reply is deliver), `s_host` (hostname the step ended on, as for `domains`), `s_nav`, `s_out_chars` (cell output length), `s_imgs` (screenshots sent to the model), `s_ev` (bits: 1 server compaction, 2 client compaction before the step, 4 after a failed attempt, 8 delivery-only turn, 16 captcha event, 32 domain block, 64 cell output cut, 128 new page, 256 same code as the previous step, 512 cell timeout or worker restart, 1024 failed navigation) |
| telemetry | `tel_build_us` (time to build this event, in the telemetry thread), `tel_bytes` (its size), `tel_steps_dropped` (steps left out of the per-step lists), `tel_prev_send_fail` (sends that failed since the last success) |

Maps and lists keep their 50 largest keys. An event over 64 KB keeps fewer steps (100, then 50, then none) and 20 keys
per map.

A run whose process was killed (out of memory, SIGKILL, a kernel restart) is sent the next time browser-use runs on that
machine, as `status` `crashed` with the configuration fields, `steps` and `ms_total` as last recorded (every other field
at its default).

## How it is sent

- On the agent path, recording is an in-memory append or add (under 2 us per call) and the end of a run only queues
  the event. A background thread builds it, gzips it and POSTs it to `https://eu.i.posthog.com/batch/` (3 s timeout,
  one retry), with the standard library only. A run never waits on the network.
- At process exit, events still queued are written to the outbox and sent by a detached `python -I -c` process, so the
  exit does not wait either.
- Files, all under `~/.config/browseruse` (`BROWSER_USE_CONFIG_DIR` moves it), and only when telemetry is on:
  `device_id`; `telemetry/inflight/<run_id>.json` while a run is in progress (its configuration fields and step count,
  rewritten every 30 s, deleted when the event is sent; left behind only by a process that died); `telemetry/outbox/`
  (events that could not be sent yet: at most 20 files and 512 KB, sent by the next process, deleted after 7 days).

## cli_event (the `browser-use` CLI)

The CLI runs browser-harness, whose `cli_event` would include the piped code, its output, helper arguments and error
text. The browser-use CLI removes those before the event is sent and keeps `command`, `action`, `exit_code`,
`duration_seconds`, `task_length`, `output_length`, `step_count`, `browser`, `cdp_url` (its kind, as above), `client`,
`client_version`, `agent_client`, `model`, `model_provider`, the browser-harness environment fields, plus
`helper_counts` (helper name -> calls), `helper_errors` and `schema_version` (2).

## Identity

Events carry one anonymous id per machine: `BROWSER_USE_DEVICE_ID` if set, else a random id stored in
`~/.config/browseruse/device_id`, else (that file cannot be written) a hash of the machine's MAC address and hostname.
PostHog derives a location from the request IP (GeoIP).
