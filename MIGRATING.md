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
| Model (`llm=None`) | required | `bu-ultrafast` on the Browser Use gateway (`gpt-6-luna`, low reasoning, priority tier; `bu-auto` is the same model at medium) |
| Browser (`Browser()`) | local Chromium | Browser Use Cloud browser (`Browser('chromium')` / `local=True` for a local one) |
| Key | per provider | one Browser Use key: `browser-use login` (stored in `~/.config/browser-harness/auth.json`, shared with the CLI, the MCP server and browser-harness) or `BROWSER_USE_API_KEY` (wins when set). A `.env` in the working directory is read on import, as in 0.x |
| Python | >= 3.11 | >= 3.11 |
| Tasks with localhost / private IPs | worked | raise with a cloud browser; use `Browser('chromium')` |
| Cloud proxy | off | `us` (`cloud_proxy_country_code=None` turns it off) |
| Cloud live view | | off (`live_view=True` prints and opens it) |

## Agent(...) arguments

Kept: works as in 0.x. Raises: `TypeError` naming the argument, raised in `Agent(...)` itself.

| 0.x argument | 1.0 |
|---|---|
| `task` | kept |
| `llm` | kept: `ChatBrowserUse`, `ChatOpenAI`, `ChatAnthropic`, `ChatGoogle`, a Pydantic AI model string or Model. Default `bu-ultrafast` |
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
| new: `reasoning`, `mode`, `workspace` | `reasoning='medium'` (OpenAI reasoning models, the gateway, Anthropic, Google; on the gateway the default is the alias's own effort; OpenAI-compatible chat backends ignore it with a warning: use `ChatOpenAI(..., reasoning_effort=...)`); `mode='ultrafast'`; `workspace` holds the agent's files (default: a temp dir) |

## Agent methods

| 0.x | 1.0 |
|---|---|
| `await agent.run(max_steps=...)` | kept, but the default changed from 500 to 100: one step is one model request (one Python cell, or the delivery). Also `timeout=1700`: seconds for the agent loop (model requests and cells). Browser start before it and browser stop / cloud download collection after it are not counted. Request `max_steps - 1` is a delivery-only turn and the last is kept for one delivery repair. `max_steps < 1` or `timeout <= 0` raises `ValueError` before any browser starts. `on_step_start` / `on_step_end` raise |
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
| `is_successful()` | kept: `None` when the run did not complete, else the agent's verdict (`result.success`). Like 0.x `done(result, success)`, `finish(result, success)` requires the verdict: `success=False` for a task that was blocked, impossible, not found, refused or only partly done. `None` also when the model answered in plain text instead of calling `finish`. `is_done()` only says the run completed |
| `history`, `urls()`, `screenshots()`, `screenshot_paths()`, `action_names()`, `action_history()`, `action_results()`, `model_thoughts()`, `model_outputs()`, `model_actions()`, `model_actions_filtered()`, `extracted_content()`, `agent_steps()`, `last_action()`, `save_to_file()`, `load_from_file()`, `get_structured_output()`, `add_item()`, `judgement()`, `is_judged()`, `is_validated()` | raise `NotImplementedError`: there are no per-step actions. Use `result.messages`, `result.status`, `result.partial` and the files in `agent.workspace` |
| new | `status` (`completed`, `max_steps`, `timeout`, `error`), `success`, `partial` (last `checkpoint(..., partial=True)`), `usage`, `cost_usd`, `messages` |

## Browser(...)

| 0.x | 1.0 |
|---|---|
| `Browser()` / `BrowserSession()` | `Browser()` is now a cloud browser; `BrowserSession` and `BrowserProfile` imports raise |
| `Browser(use_cloud=True)` | kept (now the default) |
| `Browser(use_cloud=False)` | `Browser('chromium')` (`Browser(local=True)` is the same): a fresh local Chrome/Chromium/Edge with its own temp profile, launched like 0.x did, deleted when it stops |
| `headless`, `executable_path` | kept for browsers 1.0 launches (`'chromium'`, `'chrome'` with `profile=`). `headless=None` (default) is headless only without a display |
| `user_data_dir` | kept with `Browser('chromium', user_data_dir=...)`: a dedicated profile dir kept between runs. Chrome's own default dir raises: Chrome 136+ refuses remote debugging on it |
| `Browser.from_system_chrome()`, `profile_directory` | `Browser('chrome')` attaches to the Chrome you have open (enable chrome://inspect/#remote-debugging once, click Allow). `Browser('chrome', profile='Work')` launches a new Chrome on a temporary copy of that profile (display name or directory such as `'Profile 1'`): your logins, Chrome sync off, nothing is written back. Your Chrome can stay open (Windows: quit it first, Chrome locks its cookies there) |
| `keep_alive=True` | kept |
| `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` | kept |
| `cloud_browser_params` | raises: use `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` |

`Browser(local=True)` meant "your Chrome" in the 1.0 pre-releases; it now means `Browser('chromium')`. For your own
Chrome, write `Browser('chrome')`. Options that do not fit the browser (`headless` on a cloud browser, `profile` on
`'chromium'`, `cloud_profile_id` on a local one, ...) raise `ValueError` naming the right call.

`Browser('chrome')` attaches where browser-harness does: its running default daemon, else the first browser with
remote debugging on, Google Chrome first. When several are on and none is Google Chrome it raises instead of guessing.

Every other 0.x `BrowserProfile` / `BrowserSession` option raises `TypeError` naming it. What to do instead:

| 0.x options | 1.0 |
|---|---|
| other launch options: `channel`, `args`, `ignore_default_args`, `env`, `chromium_sandbox`, `devtools`, `enable_default_extensions`, `disable_security`, `is_local` | raise. `channel`: pass `executable_path=`. `--no-sandbox` is added on Linux as root or in a container, and once more if Chrome reports no usable sandbox |
| servers / Docker / CI (`browser-use install`, the 0.x Dockerfile) | `Browser('chromium')` is headless there by default (no display); or `Browser()` (cloud). `browser-use install` no longer downloads a browser: install Chrome or Chromium (`BH_CHROME_PATH` / `CHROME_PATH` point at a binary) |
| window and identity: `window_size`, `window_width`, `window_height`, `window_position`, `viewport`, `no_viewport`, `screen`, `device_scale_factor`, `user_agent`, `headers` | say it in the task: the agent can send `Emulation.setDeviceMetricsOverride`, `Network.setUserAgentOverride`, `Network.setExtraHTTPHeaders` itself. Headless launches use 1440x900. Viewport emulation does not work on cloud browsers yet: `Emulation.setDeviceMetricsOverride` is accepted there but the page keeps its 1440 px width; use `Browser('chromium')` for another viewport |
| downloads: `downloads_path`, `accept_downloads`, `auto_download_pdfs` | cloud: files the browser downloaded are copied to `agent.workspace/downloads` when it stops. Local: the browser's own download folder; the agent can set `Browser.setDownloadBehavior` |
| `permissions` | say it in the task: the agent can send `Browser.grantPermissions` |
| `proxy` (`server`, `bypass`, `username`, `password`) | cloud: `cloud_proxy_country_code`. Local: not yet |
| `storage_state`, `cookie_whitelist_domains` | cloud: `cloud_profile_id` keeps logins. Local: `Browser('chrome')` / `Browser('chrome', profile=...)` have yours; `Browser('chromium', user_data_dir=...)` keeps its own |
| `allowed_domains`, `prohibited_domains`, `block_ip_addresses` | raise: not in 1.0 yet. Domain-scoped `sensitive_data` still limits where secrets are typed |
| recording: `record_video_dir`, `record_video_size`, `record_video_framerate`, `record_har_path`, `record_har_content`, `record_har_mode`, `traces_dir` | removed. `result.messages` is the transcript; `live_view=True` shows a cloud browser live |
| 0.x engine tuning: `highlight_elements`, `dom_highlight_elements`, `filter_highlight_ids`, `paint_order_filtering`, `interaction_highlight_color`, `interaction_highlight_duration`, `cross_origin_iframes`, `max_iframes`, `max_iframe_depth`, `minimum_wait_page_load_time`, `wait_for_network_idle_page_load_time`, `wait_between_actions`, `deterministic_rendering`, `demo_mode` | removed: they tuned the 0.x DOM engine. Delete them |
| `captcha_solver` | kept for cloud browsers: they solve captchas automatically, and `Browser(captcha_solver=False)` turns the solver off when the browser starts (the agent is told to handle captchas itself). Other browsers have no solver: `captcha_solver=False` raises `ValueError` |

Parallel agents (the 0.x `parallel_agents.py` pattern): give each its own `Browser()` or `Browser('chromium')`; each
has its own browser and daemon. `Browser('chrome')` is one at a time: every one in a process shares the
browser-harness default daemon and its one attached tab, so two at once move each other's tab.

## Models

| 0.x | 1.0 |
|---|---|
| `ChatBrowserUse(model=...)` | kept: `bu-ultrafast` (default), `bu-auto`, `bu-smart` or a listed OpenAI model on the new gateway, over the stateless Responses API with server-side compaction. The 0.x gateway models `bu-2-0`, `bu-2-0-mini-preview`, `bu-1-0` and `bu-latest` are rejected: keep `browser-use<1.0` for them, or use `bu-ultrafast`. Before the browser starts, the agent reads the gateway's model list (free): a gateway that is not there, a rejected key or a model it does not list ends the run with `result.error` and no browser created. Gateway errors (400/401/402/403/404) come back as one actionable line in `result.error`; `result.cost_usd` is what the gateway charged. Another gateway URL: `ChatBrowserUse(base_url=...)` (0.x's `BROWSER_USE_LLM_URL` is not read) |
| `ChatOpenAI(model, api_key, base_url, temperature, reasoning_effort)` | kept. api.openai.com uses the Responses API; the gateway URL is served as `ChatBrowserUse`; any other `base_url` uses plain chat completions. Other 0.x arguments raise `TypeError` |
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
as before. New: `browser-use login` / `logout` (same as `browser-use auth login` / `logout`), and a `browser_login`
MCP tool that opens the browser to approve and stores the same key. The old `browser-use --mcp` server (tools like
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
  `result.error`, and the error `Agent.run` logs. Telemetry never sends these texts at all (TELEMETRY.md)

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

`Browser('chrome')` and `Browser('chrome', profile=...)` drive your real logins: model-written CDP can read their
cookies and (attached) your open tabs. `Browser('chromium')` and the cloud browser start with no cookies, so CDP cannot
reach yours; the worker itself still runs as your user (see above). Use them for untrusted tasks.
