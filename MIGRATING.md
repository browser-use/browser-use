# Migrating from browser-use 0.x to 1.0

1.0 replaces the engine. The agent no longer picks one action per step from a DOM dump. It writes Python in a
persistent REPL with [browser-harness](https://github.com/browser-use/browser-harness) helpers and raw CDP, on
[Pydantic AI](https://ai.pydantic.dev). The common 0.x surface (`Agent`, `Browser`, `Tools`, `run()`,
`final_result()`) still works. Anything 1.0 cannot honor raises a clear error before a browser starts or anything is
billed, never a silent no-op.

Need 0.x? Pin it: `pip install 'browser-use<1'`.

## What changes by default

| | 0.x | 1.0 |
|---|---|---|
| Model (`llm=None`) | required | `bu-auto` on the Browser Use gateway |
| Browser (`Browser()`) | local Chromium | Browser Use Cloud browser (`Browser(local=True)` for your Chrome) |
| Key | per provider | one Browser Use key: `browser-use auth login` or `BROWSER_USE_API_KEY`. A `.env` in the working directory is read on import, as in 0.x |
| Python | >= 3.11 | >= 3.11 |
| Tasks with localhost / private IPs | worked | raise with a cloud browser; use `Browser(local=True)` |
| Cloud proxy | off | `us` (`cloud_proxy_country_code=None` turns it off) |
| Cloud live view | | off (`live_view=True` prints and opens it) |

## Agent(...) arguments

Kept: works as in 0.x. Raises: `TypeError` naming the argument, raised in `Agent(...)` itself.

| 0.x argument | 1.0 |
|---|---|
| `task` | kept |
| `llm` | kept: `ChatBrowserUse`, `ChatOpenAI`, `ChatAnthropic`, `ChatGoogle`, a Pydantic AI model string or Model. Default `bu-auto` |
| `browser`, `browser_session` | kept: take a `Browser(...)` |
| `tools`, `controller` | kept: take `Tools()` (see below) |
| `output_model_schema` | kept: `result.structured_output` |
| `sensitive_data` | kept: `{'name': 'value'}` types anywhere; domain-scoped `{'https://site.com' or '*.site.com': {'name': 'value'}}` types only on matching pages (0.x patterns: no scheme = https only). The model types values with `type_secret('name')`; a name ending in `bu_2fa_code` holds a TOTP seed and types the current 6-digit code, as in 0.x; values are replaced with `<secret:name>` in cell output, checkpoints, tool results, the task and the result. Not a sandbox: see [Trust model](#trust-model-for-secrets) for exactly what is redacted |
| `extend_system_message` | kept |
| `use_vision`, `max_actions_per_step`, `vision_detail_level`, `llm_screenshot_size`, `sample_images` | raises: screenshots are taken when needed; each step is one Python cell |
| `flash_mode` | raises: try `mode='ultrafast'` |
| `use_thinking` | raises: use `reasoning='low' / 'medium' / 'high'` |
| `override_system_message` | raises: use `extend_system_message` |
| `browser_profile` | raises: pass options to `Browser(...)` |
| `page_extraction_llm`, `extraction_schema` | raises: the agent extracts with Python |
| `file_system_path` | raises: use `workspace=` |
| `available_file_paths` | raises: put files in the workspace |
| `initial_actions`, `directly_open_url` | raises: say it in the task |
| `register_new_step_callback`, `register_done_callback`, `register_external_agent_status_raise_error_callback`, `register_should_stop_callback` | raises: read `result.messages` after the run |
| `max_failures`, `final_response_after_failure` | raises: failed cells are retried within `max_steps` |
| `llm_timeout`, `step_timeout` | raises: `agent.run(timeout=seconds)` bounds the agent loop (model requests and cells; browser start and stop are not counted) |
| `fallback_llm` | raises |
| `use_judge`, `judge_llm`, `ground_truth` | raises |
| `generate_gif`, `demo_mode` | raises |
| `save_conversation_path`, `save_conversation_path_encoding` | raises: `result.messages` holds the transcript |
| `calculate_cost`, `pricing_url` | raises: `result.cost_usd` is computed when the price is known (`None` otherwise) |
| `skill_ids`, `skills`, `skill_service` | raises: Cloud Skills were removed |
| `enable_planning`, `planning_replan_on_stall`, `planning_exploration_limit`, `loop_detection_window`, `loop_detection_enabled`, `message_compaction`, `max_history_items`, `include_attributes`, `max_clickable_elements_length`, `include_recent_events`, `include_tool_call_examples`, `display_files_in_done_text`, `injected_agent_state`, `source`, `task_id`, `enable_signal_handler`, `_url_shortening_limit` | raises: these tuned the 0.x loop |
| new: `reasoning`, `mode`, `workspace` | `reasoning='medium'` (OpenAI reasoning models, Anthropic, Google; OpenAI-compatible chat backends such as the gateway ignore it with a warning: use `ChatOpenAI(..., reasoning_effort=...)`); `mode='ultrafast'`; `workspace` holds the agent's files (default: a temp dir) |

## Agent methods

| 0.x | 1.0 |
|---|---|
| `await agent.run(max_steps=...)` | kept, but the default changed from 500 to 100: one step is one model request (one Python cell, or the delivery). Also `timeout=1700`: seconds for the agent loop (model requests and cells). Browser start before it and browser stop / cloud download collection after it are not counted. `on_step_start` / `on_step_end` raise |
| `agent.run_sync()` | kept |
| `agent.add_new_task(task)` | kept: the next `run()` continues the same conversation |
| `await agent.close()`, `async with Agent(...)` | kept; after `run_sync()` use `agent.close_sync()` |
| browser stops when `run()` ends | kept, unless `Browser(keep_alive=True)` |
| `pause()`, `resume()`, `stop()`, `step()`, `multi_act()` | removed |
| `save_history()`, `load_and_rerun()`, `rerun_history()`, `detect_variables()` | removed |

## The result (AgentHistoryList)

| 0.x | 1.0 |
|---|---|
| `final_result()`, `is_done()`, `structured_output`, `total_duration_seconds()`, `number_of_steps()` | kept |
| `errors()`, `has_errors()` | changed: only the error that ended the run (`result.error`). 0.x listed one entry per step; cell errors the agent recovered from are now in `result.messages` |
| `is_successful()` | kept: `None` when the run did not complete, else the agent's verdict (`result.success`). The model reports a task it could not do with `finish(result, success=False)`, like 0.x `done(success=False)`. `is_done()` only says the run completed |
| `history`, `urls()`, `screenshots()`, `screenshot_paths()`, `action_names()`, `action_history()`, `action_results()`, `model_thoughts()`, `model_outputs()`, `model_actions()`, `model_actions_filtered()`, `extracted_content()`, `agent_steps()`, `last_action()`, `save_to_file()`, `load_from_file()`, `get_structured_output()`, `add_item()`, `judgement()`, `is_judged()`, `is_validated()` | raise `NotImplementedError`: there are no per-step actions. Use `result.messages`, `result.status`, `result.partial` and the files in `agent.workspace` |
| new | `status` (`completed`, `max_steps`, `timeout`, `error`), `success`, `partial` (last `checkpoint(..., partial=True)`), `usage`, `cost_usd`, `messages` |

## Browser(...)

| 0.x | 1.0 |
|---|---|
| `Browser()` / `BrowserSession()` | `Browser()` is now a cloud browser; `BrowserSession` and `BrowserProfile` imports raise |
| `Browser(use_cloud=True)` | kept (now the default) |
| `Browser(use_cloud=False)` | `Browser(local=True)`: your desktop Chrome and its real profile, through browser-harness |
| `cdp_url=` | kept |
| `keep_alive=True` | kept |
| `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` | kept |
| `cloud_browser_params` | raises: use `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` |
| `Browser.from_system_chrome()` | not yet |

Every other 0.x `BrowserProfile` / `BrowserSession` option raises `TypeError` naming it. What to do instead:

| 0.x options | 1.0 |
|---|---|
| launching Chromium: `headless`, `executable_path`, `channel`, `user_data_dir`, `profile_directory`, `args`, `ignore_default_args`, `env`, `chromium_sandbox`, `devtools`, `enable_default_extensions`, `disable_security`, `is_local` | 1.0 never launches a browser with options. Desktop: `Browser(local=True)` uses your Chrome. Anything custom: start Chrome yourself with the flags you want (`chrome --remote-debugging-port=9222 --user-data-dir=/tmp/p --headless=new ...`) and pass `Browser(cdp_url='http://127.0.0.1:9222')`. Or use the cloud browser |
| headless / servers / Docker (`headless=True`, `browser-use install`, the 0.x Dockerfile) | `Browser()` (cloud, always headless), or run `chromium --headless=new --remote-debugging-port=9222` in the container and pass `cdp_url=`. `Browser(local=True)` needs a desktop Chrome. `browser-use install` no longer downloads a browser |
| window and identity: `window_size`, `window_width`, `window_height`, `window_position`, `viewport`, `no_viewport`, `screen`, `device_scale_factor`, `user_agent`, `headers` | Chrome flags (`--window-size=1280,800`, `--user-agent=...`) on a Chrome you start + `cdp_url=`, or say it in the task: the agent can send `Emulation.setDeviceMetricsOverride`, `Network.setUserAgentOverride`, `Network.setExtraHTTPHeaders` itself |
| downloads: `downloads_path`, `accept_downloads`, `auto_download_pdfs` | cloud: files the browser downloaded are copied to `agent.workspace/downloads` when it stops. Local / `cdp_url`: the browser's own download folder; the agent can set `Browser.setDownloadBehavior` |
| `permissions` | say it in the task: the agent can send `Browser.grantPermissions` |
| `proxy` (`server`, `bypass`, `username`, `password`) | cloud: `cloud_proxy_country_code`. Your own Chrome: `--proxy-server=...` + `cdp_url=` |
| `storage_state`, `cookie_whitelist_domains` | cloud: `cloud_profile_id` keeps logins. Local: your Chrome profile already has them |
| `allowed_domains`, `prohibited_domains`, `block_ip_addresses` | raise: not in 1.0 yet. Domain-scoped `sensitive_data` still limits where secrets are typed |
| recording: `record_video_dir`, `record_video_size`, `record_video_framerate`, `record_har_path`, `record_har_content`, `record_har_mode`, `traces_dir` | removed. `result.messages` is the transcript; `live_view=True` shows a cloud browser live |
| 0.x engine tuning: `highlight_elements`, `dom_highlight_elements`, `filter_highlight_ids`, `paint_order_filtering`, `interaction_highlight_color`, `interaction_highlight_duration`, `cross_origin_iframes`, `max_iframes`, `max_iframe_depth`, `minimum_wait_page_load_time`, `wait_for_network_idle_page_load_time`, `wait_between_actions`, `deterministic_rendering`, `demo_mode`, `captcha_solver` | removed: they tuned the 0.x DOM engine. Delete them |

One local agent at a time: every `Browser(local=True)` in a process shares one browser-harness daemon and its one
attached tab, so two local agents running at once (the 0.x `parallel_agents.py` pattern) move each other's tab. Run
parallel agents on cloud browsers (`Browser()` each) or on separate Chromes via `cdp_url=`.

## Models

| 0.x | 1.0 |
|---|---|
| `ChatBrowserUse(model=...)` | kept: `bu-auto` (default), `bu-smart`, ... on the new gateway. 401/402/403/404 come back as one actionable line in `result.error` |
| `ChatOpenAI(model, api_key, base_url, temperature, reasoning_effort)` | kept. api.openai.com uses the Responses API; any other `base_url` uses plain chat completions. Other 0.x arguments raise `TypeError` |
| `ChatAnthropic(model, api_key)`, `ChatGoogle(model, api_key)` | kept; need `browser-use[anthropic]` / `browser-use[google]` |
| `ChatGroq`, `ChatOllama`, `ChatAzureOpenAI`, `ChatDeepSeek`, `ChatMistral`, `ChatOpenRouter`, `ChatAWSBedrock`, `ChatAnthropicBedrock`, `ChatCerebras`, `ChatLiteLLM`, `ChatOCIRaw`, `ChatOrcaRouter`, `ChatVercel` | import raises: use a Pydantic AI model string (`'groq:llama-3.3-70b'`, `'mistral:...'`, `'bedrock:...'`) or `ChatOpenAI(model, base_url=...)` |

## Tools

| 0.x | 1.0 |
|---|---|
| `tools = Tools()`, `Controller()` | kept |
| `@tools.action('description')` on a plain function | kept: the function becomes a model tool |
| `param_model=Model` | kept |
| returning `ActionResult(extracted_content=...)` or any value | kept: the model sees it |
| injected parameters (`browser_session`, `page_extraction_llm`, `file_system`, `available_file_paths`, `sensitive_data`, `has_sensitive_data`, `cdp_client`, `page_url`, ...) | raises: actions get only what the model passes; the model drives the browser itself |
| `domains=`, `allowed_domains=` | raises |
| `ActionResult(is_done=True)` ending the run | not supported: the model ends the run with `finish` |

## Other removed modules

`browser_use.dom`, `browser_use.actor`, `browser_use.beta`, `browser_use.sandbox`, `browser_use.sync`,
`browser_use.filesystem`, `browser_use.screenshots`, `browser_use.tokens`, `browser_use.mcp.client` and the
Anthropic / OpenAI hosted-browser integrations (`browser_use.integrations`). The integrations come back on the new
`Browser` in a later release.

Deep imports of 0.x internals raise `ModuleNotFoundError`; import from the top level instead:

| 0.x import | 1.0 |
|---|---|
| `browser_use.llm.openai.chat`, `browser_use.llm.anthropic.chat`, `browser_use.llm.google.chat`, `browser_use.llm.browser_use.chat`, `browser_use.llm.messages`, `browser_use.llm.base` | `from browser_use import ChatOpenAI, ChatAnthropic, ChatGoogle, ChatBrowserUse` (or `browser_use.llm`) |
| `browser_use.browser.session`, `browser_use.browser.profile`, `browser_use.browser.events`, `browser_use.browser.watchdogs` | `from browser_use import Browser` (BrowserSession / BrowserProfile are gone) |
| `browser_use.controller`, `browser_use.tools.service`, `browser_use.tools.registry` | `from browser_use import Tools, Controller` |
| `browser_use.agent.views` | kept for `AgentHistoryList` and `ActionResult`; `AgentState`, `AgentOutput`, `AgentStepInfo`, ... are gone |
| `browser_use.agent.prompts`, `browser_use.agent.message_manager`, `browser_use.agent.judge` | removed: the 0.x loop internals |

## CLI and MCP

The `browser-use` CLI (Python piped to browser-harness), `browser-use skill install` and `browser-use --cli-mcp` work
as before. The old `browser-use --mcp` server (tools like
`browser_navigate`, `browser_click`) ran the removed engine: `--mcp` now prints a deprecation notice and serves the
`--cli-mcp` tools (`browser_exec`, `browser_screenshot`). MCP clients that call the old tool names break; switch them
to `--cli-mcp`. `browser-use init` templates were removed.

## Trust model for secrets

The REPL worker runs model-written Python as your user. 1.0 limits what it can see by default:

- Its environment is an allowlist (`PATH`, `HOME`, locale, temp dirs, `BU_*` / `BH_*` harness settings). Variables
  whose names contain `KEY`, `TOKEN`, `SECRET`, `PASSW`, `CREDENTIAL` or `AUTH` never reach it.
- `sensitive_data` values are sent to the worker over its control channel. The model is told only their names and
  types a value with `type_secret(name)`.
- A domain-scoped secret (`{'https://site.com': {...}}`) is typed only while the frame that receives the text (the
  focused frame, followed into iframes and shadow roots) has a matching URL, as the browser reports it (not page
  JavaScript); when that frame cannot be established it is not typed. A prompt-injected page cannot get it typed on
  another site, or into another site's iframe on the right page. The page can still move focus between that check and
  the key events.

Redaction replaces a secret value, its JSON- and `repr()`-escaped forms, and its reversed, base64, hex and URL-encoded
forms, with `<secret:name>` in exactly these places:

- what a cell returns to the model: its stdout/stderr (subprocesses included), its error, a `finish_from_repl` value,
  and the cell's output file in `workspace/.browser-use/cells/`
- files written by `checkpoint()` (and the partial result)
- results and retry messages of your own `Tools` actions
- the task, follow-up tasks (`add_new_task`) and `extend_system_message`, before the model sees them
- `result.final_result()`, `result.output` / `result.structured_output` (field by field), `result.partial`,
  `result.error`, the error `Agent.run` logs, and telemetry

Nothing else is redacted. This is not a sandbox:

- The values live in the worker process, so model-written Python can read them. A transform redaction does not know
  (rot13, splitting a value) passes every channel above, and a file the code writes itself (`open()`, pandas, ...) is
  never redacted.
- Screenshots are images and are not redacted: a typed value in a visible field (an email, a token, a "show
  password" field) reaches the model in a screenshot. Model-written `js()` can read a field's value back.
- A cloud browser's live view (`live_view=True`, or anyone with that URL) and any recording of the session show what
  was typed, as in any browser.
- The worker can read files your user can read (for example `~/.config/browser-harness/auth.json`).

Run untrusted tasks in a container or VM.

`Browser(local=True)` drives your real Chrome profile: model-written CDP can read its cookies and open tabs. Use a
cloud browser or your own Chrome with a throwaway profile (`--user-data-dir=...` + `cdp_url=`) for untrusted tasks.
