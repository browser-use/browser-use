# Migrating from browser-use 0.x to 1.0

1.0 replaces the engine. The agent no longer picks one action per step from a DOM dump. It writes Python in a
persistent REPL with [browser-harness](https://github.com/browser-use/browser-harness) helpers and raw CDP, on
[Pydantic AI](https://ai.pydantic.dev). The common 0.x surface (`Agent`, `Browser`, `Tools`, `run()`,
`final_result()`) still works. Anything 1.0 cannot honor raises a clear error before a browser starts or anything is
billed, never a silent no-op. A 0.x feature 1.0 dropped raises one error: "`<feature>` was removed in browser-use 1.0.
Open an issue at https://github.com/browser-use/browser-use/issues if you need it. In 1.0: `<the alternative>`
Migration guide: https://github.com/browser-use/browser-use/blob/main/MIGRATING.md" (the "In 1.0" part when there is
one); [Removed in 1.0](#removed-in-10) and [Other removed modules](#other-removed-modules) list them all.

Need 0.x? Pin it: `pip install 'browser-use<1'`.

## What changes by default

| | 0.x | 1.0 |
|---|---|---|
| Model (`llm=None`) | required | `bu-fast` on the Browser Use gateway (`gpt-6-luna`, medium reasoning; `bu-ultrafast` is the same model at low reasoning on the priority tier) |
| Browser (`Browser()`) | local Chromium | Browser Use Cloud browser (`Browser('chromium')` / `local=True` for a local one) |
| Key | per provider | one Browser Use key: `browser-use login` (stored in `~/.config/browser-harness/auth.json`, shared with the CLI, the MCP server and browser-harness) or `BROWSER_USE_API_KEY` (wins when set). A `.env` in the working directory is read on import, as in 0.x |
| Python | >= 3.11 | >= 3.11 |
| Tasks with localhost / private IPs | worked | a cloud browser cannot reach them: one warning, use `Browser('chromium')` |
| Cloud proxy | the API's default, `us` | `us` (`cloud_proxy_country_code=None` turns it off) |
| Cloud live view | | off (`live_view=True` prints and opens it) |

## Agent(...) arguments

Kept: works as in 0.x. `use_vision=False` is kept: no screenshot reaches the model. The 0.x tuning knobs 1.0 has no
use for (`use_vision=True` / `'auto'`, `vision_detail_level`,
`llm_screenshot_size`, `max_actions_per_step`, `flash_mode`, `use_thinking`, `use_judge`, `max_failures`,
`final_response_after_failure`, `calculate_cost`, `highlight_elements`: use `highlight_actions`) log one warning each and are ignored. Every other 0.x argument raises
`TypeError` naming it in `Agent(...)` itself (listed in [Removed in 1.0](#removed-in-10)); an argument 0.x never had says
it is not a 1.0 option (`Agent(max_steps=...)` points to `agent.run(max_steps=...)`).

| 0.x argument | 1.0 |
|---|---|
| `task` | kept |
| `llm` | kept: `ChatBrowserUse`, `ChatOpenAI`, `ChatAnthropic`, `ChatGoogle`, a Pydantic AI model string or Model. Default `bu-fast` |
| `browser`, `browser_session` | kept: take a `Browser(...)` |
| `tools`, `controller` | kept: take `Tools()` (see below) |
| `output_model_schema` | kept: `result.structured_output` |
| `sensitive_data` | kept: `{'name': 'value'}` types anywhere; domain-scoped `{'https://site.com' or '*.site.com': {'name': 'value'}}` types only on matching pages (0.x patterns: no scheme = https only). The model types values with `type_secret('name')`; a name ending in `bu_2fa_code` holds a TOTP seed and types the current 6-digit code, as in 0.x; the 0.x `<secret>name</secret>` placeholder is not replaced: a cell that sends it (or `<secret:name>`) to the page raises naming `type_secret('name')` and sends nothing; values are replaced with `<secret:name>` in cell output, checkpoints, tool results, the task and the result. Not a sandbox: see [Trust model](#trust-model-for-secrets) for exactly what is redacted |
| `extend_system_message` | kept |
| everything else 0.x took | removed: [Removed in 1.0](#removed-in-10) |
| new: `reasoning`, `mode`, `workspace`, `web_search`, `max_context_chars`, `highlight_actions` | `reasoning='medium'` (OpenAI reasoning models, the gateway, Anthropic, Google; on the gateway a bu-* alias's own effort, a listed OpenAI model 'medium'; OpenAI-compatible chat backends ignore it with a warning: use `ChatOpenAI(..., reasoning_effort=...)`); `mode='ultrafast'` (the default on `bu-fast` and `bu-ultrafast`; `mode='default'` opts out); `workspace` holds the agent's files (default: a new temp dir `browser-use-*`, kept after the run: it holds page text, screenshots and cell output, so delete it when done, or pass your own `workspace=`); `web_search=True` gives the agent `search()` (Browser Use web search on the gateway host, `POST /api/v4/search`, with the gateway model's key or the Browser Use key; billed per search; each charge the response reports (`browser_use.charge_usd`) is added to `result.cost_usd`, a response without one adds nothing, and an unknown model cost stays `None`) off by default; `True` raises without a Browser Use key or with `allowed_domains`. Off, the system prompt is unchanged; `max_context_chars`: past 75% of this many characters of conversation the agent compacts its history into a summary checkpoint (default 4 per token of the model's context window, as Browser Use Pi, or 240k when pydantic-ai does not know the window; unused where the provider compacts server-side: OpenAI Responses, the gateway); `highlight_actions=False` turns off the orange corner brackets around what the agent clicks or types into (on by default) |

## Agent methods

| 0.x | 1.0 |
|---|---|
| `await agent.run(max_steps=...)` | kept, but the default changed from 500 to 100: one step is one model request (one Python cell, or the delivery). Also `timeout=1700`: seconds for the agent loop (model requests and cells). Browser start before it and browser stop / cloud download collection after it are not counted. As in 0.x, request `max_steps` is a delivery-only turn (the forced done), so `max_steps=N` leaves `N - 1` steps for the browser; one delivery repair request may follow it (a placeholder answer, or a structured `output_model_schema` result answered in plain text; a plain-text answer to a `str` task is the result). `max_steps < 1` or `timeout <= 0` raises `ValueError` before any browser starts, as does a `task` that is not a non-empty string. `run_sync()` inside a running event loop raises: use `await agent.run()`. Configuration errors (a missing key, a removed option, a bad argument) raise before any browser starts; after that `run()` does not raise: a rejected key or model (preflight), a browser that fails to start (cloud create 402/5xx/timeout, a daemon that cannot attach) and failures inside the run return `status='error'` with `result.error` (cancelling the task still raises `CancelledError`). `on_step_start` / `on_step_end`: removed |
| `agent.run_sync()` | kept |
| `agent.add_new_task(task)` | kept: the next `run()` continues the same conversation |
| `await agent.close()`, `async with Agent(...)` | kept; after `run_sync()` use `agent.close_sync()` |
| browser stops when `run()` ends | kept, unless `Browser(keep_alive=True)` |
| `pause()`, `resume()`, `stop()`, `step()`, `multi_act()`, `save_history()`, `load_and_rerun()`, `rerun_history()`, `detect_variables()` | removed: [Removed in 1.0](#removed-in-10) |

## The result (AgentHistoryList)

| 0.x | 1.0 |
|---|---|
| `final_result()`, `is_done()`, `structured_output`, `total_duration_seconds()`, `number_of_steps()` | kept |
| `errors()`, `has_errors()` | changed: only the error that ended the run (`result.error`). 0.x listed one entry per step; cell errors the agent recovered from are now in `result.messages` |
| `is_successful()` | kept: `None` when the run did not complete, else the agent's verdict (`result.success`). It is the agent's own claim. The verdict in `finish(result, success)` is optional (0.x `done` defaulted it to `True`): `None` when the model gave none or answered in plain text instead of calling `finish`, so a missing verdict never reads as success. `is_done()` only says the run completed. For the 0.x default, use `r.is_done() and r.success is not False` |
| `history`, `urls()`, `screenshots()`, `screenshot_paths()`, `action_names()`, `action_history()`, `action_results()`, `model_thoughts()`, `model_outputs()`, `model_actions()`, `model_actions_filtered()`, `extracted_content()`, `agent_steps()`, `last_action()`, `save_to_file()`, `load_from_file()`, `get_structured_output()`, `add_item()`, `judgement()`, `is_judged()`, `is_validated()`, `load_from_dict()`, `save_as_playwright_script()`, `input_token_usage()` (`result.usage['input']`) | removed (`AttributeError`): there are no per-step actions. Use `result.messages`, `result.status`, `result.partial` and the files in `agent.workspace` |
| new | `status` (`completed`, `max_steps`, `timeout`, `error`; a run that reaches `max_steps` or the timeout gets one forced delivery turn and still returns `completed`, with `success=False` when the agent reports the task unfinished; `max_steps` and `timeout` mean nothing was delivered: read `partial`), `success`, `partial` (last `checkpoint(..., partial=True)`; a plain `checkpoint()` is scratch and does not set it, so to ask for one name the flag in the task: "after each page, save the titles with checkpoint('titles.json', titles, partial=True)"), `usage`, `cost_usd` (model and web search charges only: the cloud browser and its proxy are billed apart, see `browserCost` and `proxyCost` in `GET /api/v4/browsers/{browser.id}`), `messages` |

## Browser(...)

| 0.x | 1.0 |
|---|---|
| `Browser()` / `BrowserSession()` | `Browser()` is now a cloud browser; `BrowserSession` and `BrowserProfile` imports raise |
| `Browser(use_cloud=True)` | kept (now the default) |
| `Browser(use_cloud=False)` | `Browser('chromium')` (`Browser(local=True)` is the same): a fresh local Chrome/Chromium/Edge with its own temp profile, launched like 0.x did, deleted when it stops |
| `headless`, `executable_path` | kept for browsers 1.0 launches (`'chromium'`, `'chrome'` with `profile=`). `headless=None` (default) is headless only without a display |
| `user_data_dir` | kept with `Browser('chromium', user_data_dir=...)`: a dedicated profile dir kept between runs. Chrome's own default dir raises: Chrome 136+ refuses remote debugging on it |
| `Browser.from_system_chrome()`, `profile_directory` | `Browser('chrome')` attaches to the Chrome you have open (enable chrome://inspect/#remote-debugging once, click Allow). `Browser('chrome', profile='Work')` launches a new Chrome on a temporary copy of that profile (display name or directory such as `'Profile 1'`): your logins, Chrome sync off, nothing is written back. Your Chrome can stay open (Windows: quit it first, Chrome locks its cookies there) |
| `keep_alive=True` | kept; a cloud browser that ended between runs (`cloud_timeout`, stopped from the dashboard) is replaced by a new one at the next run, with a warning |
| `await browser.close()`, `await browser.kill()` | kept: they stop the browser, as `await browser.stop()` does (also a `keep_alive=True` one). `stop_session()` raises: use `stop()`. `Agent.run()` stops the browser unless `keep_alive=True` |
| `cdp_url` | kept. `headers` (0.x: sent on the `cdp_url` connect request, e.g. for AWS Bedrock AgentCore SigV4) raises until the browser daemon can send them on the WebSocket handshake: use a `cdp_url` that needs no headers |
| `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` | kept (the 0.x aliases `profile_id`, `proxy_country_code`, `timeout` and `cloud_browser=True` raise naming these) |
| `cloud_browser_params` | raises: use `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` |

`Browser(local=True)` meant "your Chrome" in the 1.0 pre-releases; it now means `Browser('chromium')`. For your own
Chrome, write `Browser('chrome')`. Options that do not fit the browser (`headless` on a cloud browser, `profile` on
`'chromium'`, `cloud_profile_id` on a local one, ...) raise `ValueError` naming the right call.

`Browser('chrome')` attaches where browser-harness does: its running default daemon, else the first browser with
remote debugging on, Google Chrome first. When several are on and none is Google Chrome it raises instead of guessing.

Every other 0.x `BrowserProfile` / `BrowserSession` option raises `TypeError` naming it, and every other 0.x `BrowserSession` / `BrowserContext` method or attribute (0.1 to 0.13: `get_current_page`, `navigate_to`, `get_tabs`, `take_screenshot`, `get_state_summary`, `get_or_create_cdp_session`, `new_context`, `cookies`, ...) raises `AttributeError` naming the 1.0 answer: the agent drives pages in Python (browser-harness helpers and raw CDP). What to do instead for the options:

| 0.x options | 1.0 |
|---|---|
| other launch options: `channel`, `args`, `ignore_default_args`, `env`, `chromium_sandbox`, `devtools`, `enable_default_extensions`, `disable_security`, `is_local` | raise. `channel`: pass `executable_path=`. `--no-sandbox` is added on Linux as root or in a container, and once more if Chrome reports no usable sandbox |
| servers / Docker / CI (`browser-use install`, the 0.x Dockerfile) | `Browser('chromium')` is headless there by default (no display); or `Browser()` (cloud). `browser-use install` still downloads Playwright's Chromium (with system deps on Linux), which `Browser('chromium')` finds when no Chrome is installed; or point `BH_CHROME_PATH` / `CHROME_PATH` at a binary |
| window and identity: `window_size`, `window_width`, `window_height`, `window_position`, `viewport`, `no_viewport`, `screen`, `device_scale_factor`, `user_agent`; the 0.6 Playwright-era `locale`, `timezone_id`, `color_scheme`, `contrast`, `forced_colors`, `reduced_motion`, `is_mobile`, `has_touch`, `extra_http_headers`, `offline`, `java_script_enabled`, `bypass_csp`, `ignore_https_errors`, `service_workers`, `base_url` | say it in the task: the agent can send `Emulation.setUserAgentOverride` and, on a local browser, `Emulation.setDeviceMetricsOverride` itself. Headless launches use a 1440x900 window. A cloud browser accepts `Emulation.setDeviceMetricsOverride` and `Network.setUserAgentOverride` but changes nothing: the page keeps its viewport and user agent. Use `Emulation.setUserAgentOverride` there, and `Browser('chromium')` for another viewport |
| downloads: `downloads_path`, `accept_downloads`, `auto_download_pdfs` | cloud: files the browser downloaded are copied to `agent.workspace/downloads` when the run ends (also with `keep_alive=True`). `Browser('chromium')` and `Browser('chrome', profile=...)`: downloads land in `agent.workspace/downloads` directly. `result.downloads` lists the files the run added there. Mid-run the agent checks finished downloads with `downloads()` (cloud: the API's list). `Browser('chrome')` (your Chrome) and `cdp_url`: the browser's own download folder, no `downloads()` |
| `permissions` | say it in the task: the agent can send `Browser.grantPermissions` |
| `proxy` (`server`, `bypass`, `username`, `password`) | cloud: `cloud_proxy_country_code`. Local: not yet |
| `storage_state`, `cookie_whitelist_domains` | cloud: `cloud_profile_id` keeps logins. Local: `Browser('chrome')` / `Browser('chrome', profile=...)` have yours; `Browser('chromium', user_data_dir=...)` keeps its own |
| recording: `record_video_dir`, `record_video_size`, `record_video_framerate`, `record_har_path`, `record_har_content`, `record_har_mode`, `record_har_omit_content`, `record_har_url_filter`, `traces_dir` | removed. `result.messages` is the transcript; `live_view=True` shows a cloud browser live |
| `highlight_elements`, `interaction_highlight_color`, `interaction_highlight_duration` | removed: actions are highlighted by default (orange corner brackets for 1 s, never in the agent's screenshots); `Agent(highlight_actions=False)` turns it off |
| 0.x engine tuning: `dom_highlight_elements`, `filter_highlight_ids`, `paint_order_filtering`, `cross_origin_iframes`, `max_iframes`, `max_iframe_depth`, `minimum_wait_page_load_time`, `wait_for_network_idle_page_load_time`, `wait_between_actions`, `deterministic_rendering`, `demo_mode`; 0.1/0.6 `maximum_wait_page_load_time`, `viewport_expansion`, `include_dynamic_attributes`, `cached_state`, `default_timeout`, `default_navigation_timeout`, `slow_mo`, `strict_selectors` | removed: they tuned the 0.x DOM engine. Delete them |
| 0.6 `handle_sigint`, `handle_sigterm`, `handle_sighup`; `stealth`; `cookies_file`; `context` | removed: a browser 1.0 started is stopped when the process exits; cloud browsers run with stealth settings (`Browser()`); `cookies_file` as `storage_state`; `context`: pass options to `Browser(...)` |
| `allowed_domains`, `prohibited_domains`, `block_ip_addresses` | kept, in every mode, with the 0.x patterns: see [Domain restrictions](#domain-restrictions) |
| `captcha_solver` | kept for cloud browsers: they solve captchas automatically, and `Browser(captcha_solver=False)` turns the solver off when the browser starts and keeps it off (the agent is told to handle captchas itself; `solve_captcha()` reports the solver unavailable). Other browsers have no solver: `captcha_solver=False` raises `ValueError` |

Parallel agents (the 0.x `parallel_agents.py` pattern): give each its own `Browser()` or `Browser('chromium')`; each
has its own browser and daemon. A second Agent's `run()` on a `Browser` another Agent is running on raises
`RuntimeError`; one `Browser(keep_alive=True)` can serve several Agents one after another. `Browser('chrome')` is one at a time: every one in a process shares the
browser-harness default daemon and its one attached tab, so two at once move each other's tab. A server (FastAPI) creates a `Browser()` per request, not one
at module level.

## Models

| 0.x | 1.0 |
|---|---|
| `ChatBrowserUse(model=...)` | kept: `bu-fast` (default), `bu-ultrafast`, `bu-smart` or a listed OpenAI model on the new gateway, over the stateless Responses API with server-side compaction. The 0.x gateway models `bu-2-0`, `bu-2-0-mini-preview`, `bu-1-0` and `bu-latest` are rejected: keep `browser-use<1.0` for them, or use `bu-fast`. The 0.x gateway also served other vendors (`'anthropic/claude-sonnet-4-6'`, `'google/gemini-3-pro'`): the preflight error names `ChatAnthropic(...)` / `ChatGoogle(...)` with your own key. `'openai/gpt-5.5'` is sent as `gpt-5.5`. Before the browser starts, the agent reads the gateway's model list (free): a gateway that is not there, a rejected key or a model it does not list ends the run with `result.error` and no browser created. Gateway errors (400/401/402/403/404) come back as one actionable line in `result.error`; `result.cost_usd` is what the gateway charged. Another gateway URL: `ChatBrowserUse(base_url=...)` (0.x's `BROWSER_USE_LLM_URL` is not read) |
| `ChatOpenAI(model, api_key, base_url, temperature, reasoning_effort)` | kept. api.openai.com uses the Responses API; the gateway URL (`https://api.browser-use.com/api/v4/llm/v1`) is served as `ChatBrowserUse` (key: `api_key`, else a `bu_` key in `OPENAI_API_KEY`, else the Browser Use key); any other `base_url` uses plain chat completions. Other 0.x arguments raise `TypeError` |
| `ChatAnthropic(model, api_key)`, `ChatGoogle(model, api_key)` | kept, built in (no extra needed). Other 0.x arguments raise `TypeError` naming the answer: `ChatAnthropic(temperature=...)`: delete it (Anthropic's API answers 400 to `temperature` on Claude 4.x models); the rest: a Pydantic AI model with `settings=`, e.g. `GoogleModel('gemini-flash-latest', settings={'temperature': 0.5})` (`from pydantic_ai.models.google import GoogleModel`) or `AnthropicModel('claude-...', settings={'max_tokens': 8000})` |
| LangChain chat models (`langchain_openai.ChatOpenAI`, `langchain_anthropic.ChatAnthropic`, ...) | not supported: `Agent(llm=...)` raises `TypeError`. Use `from browser_use import ChatOpenAI` (same `model=`), or a Pydantic AI model string like `'openai:gpt-4o'` |
| a rejected key or unknown model on OpenAI, Anthropic or Google | before any browser starts, the agent reads the model from the provider (free): a rejected key or a 404 ends the run with `result.error` and no browser created |
| `ChatAzureOpenAI(model, api_key, azure_endpoint, api_version)` | removed (the import raises): `llm='azure:<deployment>'` with `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` and `OPENAI_API_VERSION` set. 0.x's `AZURE_OPENAI_KEY` is not read (renamed `AZURE_OPENAI_API_KEY`), and `OPENAI_API_VERSION` is now required (0.x default: `2024-12-01-preview`) |
| `ChatAWSBedrock`, `ChatAnthropicBedrock` | removed: `llm='bedrock:<model id>'` (e.g. `'bedrock:us.anthropic.claude-...'`) after `pip install 'pydantic-ai-slim[bedrock]'`; AWS credentials and `AWS_DEFAULT_REGION` |
| `ChatDeepSeek`, `ChatOpenRouter`, `ChatCerebras`, `ChatVercel` | removed: `llm='deepseek:deepseek-chat'`, `'openrouter:<vendor>/<model>'`, `'cerebras:<model>'`, `'vercel:<vendor>/<model>'` with `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `CEREBRAS_API_KEY` or `VERCEL_AI_GATEWAY_API_KEY` set |
| `ChatGroq`, `ChatMistral` | removed: `llm='groq:<model>'` or `'mistral:<model>'` after `pip install 'pydantic-ai-slim[groq]'` (or `[mistral]`); `GROQ_API_KEY` or `MISTRAL_API_KEY` |
| `ChatOllama` | removed: `ChatOpenAI('<model>', base_url='http://localhost:11434/v1', api_key='ollama')` |
| `ChatLiteLLM`, `ChatOCIRaw`, `ChatOrcaRouter` | removed: `ChatOpenAI(model, base_url=...)` for its OpenAI-compatible endpoint |

## Tools

| 0.x | 1.0 |
|---|---|
| `tools = Tools()`, `Controller()` | kept (the 0.x methods `act()`, `exclude_action()`, `get_output_model()`, `use_structured_output_action()`, `set_coordinate_clicking()` raise naming the answer). `Tools(exclude_actions=...)` (no built-in actions), `Tools(output_model=...)` (`Agent(output_model_schema=...)`), `display_files_in_done_text` and the 0.1 `Controller(headless=..., keep_open=..., disable_security=..., cookies_path=..., browser_config=...)` raise naming the answer |
| `@tools.action('description')` on a plain function | kept: the function becomes a model tool |
| `param_model=Model` | kept |
| returning `ActionResult(extracted_content=...)` or any value | kept: the model sees it |
| an action that raises | kept: the model gets `ActionResult(error='<Type>: <message>')` and can recover; the run goes on (`ModelRetry` asks the model to call it again) |
| injected parameters (`browser_session`, `page_extraction_llm`, `file_system`, `available_file_paths`, `has_sensitive_data`, `cdp_client`, `page_url`, ...) | removed: actions get only what the model passes; the model drives the browser itself |
| `domains=`, `allowed_domains=`, `page_filter=` | removed: `Browser(allowed_domains=...)` limits where the whole browser navigates |
| `requires_browser=`, `terminates_sequence=` | removed: actions get only what the model passes, and each step is one Python cell. Delete them |
| `<secret>name</secret>` in an action's arguments, replaced with the value | removed: the action is not run and the model gets an error; secrets are typed in the browser with `type_secret(name)` |
| `ActionResult(is_done=True, ...)`, `attachments=[...]`, `images=[...]` | removed: the model ends the run with `finish(result)` (optional `success`); save files in the workspace; the agent takes screenshots itself. An action whose source returns one raises `TypeError` when `@tools.action` registers it, before any browser starts; one without readable source raises when it returns it, ending the run. The 0.x defaults (`is_done=False`, `success=...` without `is_done=True`, `attachments=None`) are dropped |
| `ActionResult(include_in_memory=...)`, `ActionResult(include_extracted_content_only_once=...)` | ignored (warns once): every result stays in the conversation; `long_term_memory` is passed to the model next to `extracted_content` |

## Removed in 1.0

Each raises the one error above (the tuning knobs marked "ignored" warn instead; `TypeError` for arguments, `AttributeError` for `Agent` and result methods, `ImportError` for imports, an MCP tool error for old tool names) before a browser starts.

| 0.x | Status | In 1.0 |
|---|---|---|
| step callbacks: `register_new_step_callback`, `register_done_callback`, `register_external_agent_status_raise_error_callback`, `register_should_stop_callback`, `run(on_step_start=...)`, `run(on_step_end=...)` | removed | live: each step logs one INFO line (`step N: <first line of the cell> -> <error>`) to `logging.getLogger('browser_use')`, after a `Task: ... (workspace ...)` line and before `completed in N steps`; add a `logging.Handler` to it to stream progress to an MCP client or web UI (`BROWSER_USE_LOGGING_LEVEL=warning` silences it). After the run: `result.messages`; the result `run()` returns; to stop early, cancel the task awaiting `run()` or pass `run(timeout=...)` |
| `agent.pause()`, `resume()`, `stop()`, `step()`, `take_step()`, `multi_act()` | removed | `task = asyncio.create_task(agent.run())`, then `task.cancel()` (from another thread: `loop.call_soon_threadsafe(task.cancel)`); `run()` raises `CancelledError` and the browser stops. For a partial result, bound the run: `run(timeout=..., max_steps=...)` |
| history replay: `save_history()`, `load_and_rerun()`, `rerun_history()`, `detect_variables()`, `AgentHistoryList.save_to_file()` / `load_from_file()` | removed | `result.messages` holds the transcript; run the task again |
| judge: `use_judge` (ignored), `judge_llm`, `ground_truth`, `AgentHistoryList.judgement()` / `is_judged()` / `is_validated()` | removed | `result.success`, the agent's own verdict |
| `generate_gif`, `demo_mode` | removed | none (`live_view=True` shows a cloud browser live) |
| planner and vision tuning: `use_vision=True` / `'auto'` (ignored; `False` is kept), `vision_detail_level` (ignored), `llm_screenshot_size` (ignored), `sample_images`, `enable_planning`, `planning_replan_on_stall`, `planning_exploration_limit`, `planner_llm`, `planner_interval`, `is_planner_reasoning`, `extend_planner_system_message`, `use_vision_for_planner`, `max_actions_per_step` (ignored), `flash_mode` (ignored) | removed | the agent takes screenshots when it needs them; each step is one Python cell; `mode='ultrafast'` |
| other 0.x loop tuning: `loop_detection_window`, `loop_detection_enabled`, `message_compaction`, `max_history_items`, `include_attributes`, `max_clickable_elements_length`, `include_recent_events`, `include_tool_call_examples`, `display_files_in_done_text`, `injected_agent_state`, `source`, `task_id`, `enable_signal_handler`, `_url_shortening_limit`, `max_failures` (ignored), `final_response_after_failure` (ignored) | removed | failed cells are retried by the model within `max_steps` |
| `use_thinking` | ignored | `reasoning='low' / 'medium' / 'high'` |
| `override_system_message` | removed | `extend_system_message` |
| 0.1 to 0.8 arguments: `browser_context`, `context`, `page`, `validate_output`, `system_prompt_class`, `message_context`, `enable_memory`, `memory_config`, `memory_interval`, `max_input_tokens`, `images_per_step`, `retry_delay`, `save_playwright_script_path`, `cloud_sync`, `preload`, `max_error_length`, `tool_calling_method`, `tool_call_in_content` | removed | `browser=Browser(...)` for the first three; `result.success`; `extend_system_message` / the task; history is compacted on its own (`max_context_chars`); the rest: delete them |
| Agent internals: `set_task()`, `wait_until_resumed()`, `get_next_action()`, `get_model_output()`, `set_tool_calling_method()`, `create_history_gif()`, `get_trace_object()`, `authenticate_cloud_sync()`, `save_file_system_state()`, `log_completion()`, `logger`, `current_llm_model`, `is_using_fallback_llm`, `browser_context` | removed (`AttributeError`) | `add_new_task(task)`; cancel the task; `logging.getLogger('browser_use')`; `agent.llm`; `agent.browser` |
| `browser_profile` | removed | pass options to `Browser(...)` |
| `page_extraction_llm`, `extraction_schema` | removed | the agent extracts with Python |
| `file_system_path`, `available_file_paths`, the `upload_file` action | removed, no file allowlist | `workspace=`: put the files in it and name them in the task; the agent calls `upload_file(selector, path)`, also on cloud browsers. The agent can read and upload any file your user can read (see [Trust model](#trust-model-for-secrets)); run untrusted tasks in a container or VM |
| `initial_actions`, `directly_open_url` | removed | say it in the task |
| `llm_timeout`, `step_timeout` | removed | `agent.run(timeout=seconds)` bounds the agent loop (model requests and cells; browser start and stop are not counted) |
| `fallback_llm` | removed | none |
| `save_conversation_path`, `save_conversation_path_encoding` | removed | `result.messages` |
| `calculate_cost` (ignored), `pricing_url` | removed | `result.cost_usd` is computed when the price is known (`None` otherwise); it covers model and web search charges, not the cloud browser or proxy |
| `skill_ids`, `skills`, `skill_service` (Cloud Skills) | removed | none |
| tool injected parameters (`browser_session`, `page_url`, `cdp_client`, ...) | removed | actions get only what the model passes |
| `@tools.action(domains=...)`, `@tools.action(allowed_domains=...)` | removed | `Browser(allowed_domains=...)` |
| `ChatAzureOpenAI`, `ChatAWSBedrock`, `ChatDeepSeek`, `ChatGroq`, `ChatOllama` and the other provider classes | removed | each import error names its replacement: see [Models](#models) |
| `browser-use --mcp` tool names (`browser_navigate`, `browser_click`, `browser_type`, `browser_get_state`, `browser_extract_content`, `browser_get_html`, `browser_scroll`, `browser_go_back`, `browser_list_tabs`, `browser_switch_tab`, `browser_close_tab`, `retry_with_browser_use_agent`, `browser_list_sessions`, `browser_close_session`, `browser_close_all`) | removed | `browser_exec` (Python with the browser-harness helpers) and `browser_screenshot` |

## Domain restrictions

`Browser(allowed_domains=[...])`, `Browser(prohibited_domains=[...])` and `Browser(block_ip_addresses=True)` work in
every mode with the 0.x patterns. The 0.x `BROWSER_USE_ALLOWED_DOMAINS` environment variable is not read: `Browser()`
raises while it is set.

| Pattern | Matches |
|---|---|
| `'example.com'` | example.com and www.example.com (www only for a one-dot domain), http and https, any port. In `prohibited_domains` also every subdomain (new: 0.x let `en.example.com` through) |
| `'mail.example.com'` | exactly that host |
| `'*.example.com'` | example.com and every subdomain, http and https |
| `'https://example.com'` | that scheme and host on the default port (in `prohibited_domains`: on every port); a path in the pattern is a path prefix |
| `'https://*.example.com'`, `'http*://example.com/*'`, `'brave://*'` | globs on scheme, host and path |
| `'localhost:8080'` | that host and port (new: 0.x never matched a port) |

As in 0.x: `about:blank`, the new tab page, `data:` and `blob:` URLs are always allowed; URLs without a host
(`file:`, `javascript:`) are blocked; hosts compare case-insensitively and `user@host` URLs use the real host; when
both lists are set `prohibited_domains` is ignored (a warning says so); `block_ip_addresses` blocks IP-literal hosts
(also `http://0x7f.1/`-style forms) even if they are allowed; `[]` means no restriction. Fixed in 1.0: a
scheme-qualified pattern compares the parsed host and port, so `'https://example.com'` no longer allows
`https://example.com.evil.com` or `https://example.com@evil.com`; international domains match in either form,
converted as Chrome converts them (`münchen.de` = `xn--mnchen-3ya.de`, `faß.de` = `xn--fa-hia.de`, full-width dots
are dots); 0.x's fast path for lists of 100+ entries (exact hosts only) is gone: patterns
work at any length.

How it is enforced:

1. The REPL helpers refuse a disallowed URL before anything navigates: `goto_url`, `new_tab`, `http_get` (and every redirect it
   follows), and the agent's raw `cdp('Page.navigate')` / `cdp('Target.createTarget')`. The model sees `PermissionError: blocked:
   evil.com is not in allowed_domains (example.com)`.
2. The browser blocks every main-frame navigation to a disallowed host, whoever starts it: link clicks, redirects,
   `target=_blank`, `window.open`, meta refresh, JavaScript `location` changes, `Target.createTarget(url=...)`. browser-use
   holds its own CDP connection with browser-wide `Fetch.enable` for document requests and fails them
   (`net::ERR_BLOCKED_BY_CLIENT`); the request never leaves the browser, and the error page it leaves is replaced by
   `about:blank`. A page that commits without a request Chrome lets it intercept (a speculation-rules prefetch or
   prerender, which Chrome fetches in a separate network context; the back/forward cache) is caught the moment the tab
   shows it: the same connection navigates that tab to `about:blank` (about 50 ms on a local Chrome). The agent's
   `cdp('Fetch.disable')` cannot turn it off (it is not the agent's connection). The next cell output starts with what
   was blocked.
3. After every cell, browser-use checks every tab (in `Browser('chrome')`: only the tabs the agent created, switched to
   or opened popups from; never a tab you opened yourself): one still showing a disallowed page is navigated to
   `about:blank` and the cell output says so. A tab already open on a disallowed page when the `Browser` first started is left alone
   while it still shows that page (your tabs, in `Browser('chrome')`); once it navigates, it is reset like any other.
4. The system prompt gets one line listing the domains (only when set).

| Mode | Helpers refuse (1) | Browser blocks (2) | Tabs reset after each cell (3) |
|---|---|---|---|
| `Browser()` (cloud) | yes | yes | yes |
| `Browser('chromium')`, `Browser('chrome', profile=...)` | yes | yes | yes |
| `Browser(cdp_url=...)` | yes | yes (a second CDP connection to that endpoint; it applies these rules to every tab in that browser) | yes (every tab) |
| `Browser('chrome')` (your open Chrome) | yes | no: a second connection would raise Chrome's "Allow remote debugging?" prompt again | yes (the agent's tabs only) |

Not blocked (a guard for an aligned model, not a sandbox):

- Subresources: `fetch()`/XHR, images, scripts, iframes and websockets an allowed page loads from other hosts. Pages
  need their CDNs; a page on an allowed domain can still send data anywhere.
- The REPL's own Python networking (`requests`, sockets, `subprocess curl`): only `http_get` is checked (its URL and
  every redirect); a raw `urllib.request.urlopen` gets its redirects checked, not its first URL.
- Speculative requests: a page's speculation-rules prefetch/prerender (and `<link rel=prefetch>`) of a disallowed URL
  is sent; if the agent then opens it, layer 2 resets the tab right after it commits.
- An iframe of a disallowed site inside an allowed page, including one the agent's own code injects: it loads and can
  be read.
- Navigations from the agent's Python that skip the helpers (`Runtime.evaluate` that sets `location`, a click) are
  caught by layer 2, except in `Browser('chrome')`, where only the after-cell reset (3) catches them, after the page
  loaded and could be read in that cell. The system prompt says so there instead of claiming the browser blocks.
- Model code that goes around browser-use on purpose: closing or crashing the browser, opening its own CDP
  connection. Run untrusted tasks in a container or VM.
- Layer 2 adds one round trip to browser-use per document request (on a cloud browser, your network's latency to it).
  If its connection drops it reconnects; meanwhile only layers 1 and 3 apply. If it cannot start, `Browser.start()`
  raises instead of running unguarded.

Domain-scoped `sensitive_data` still limits where each secret is typed, independently of these lists.

## Other removed modules

Every 0.x module path (0.1 to 0.13) 1.0 does not have, and every public name of a 0.x module 1.0 kept, raises the
removed error naming its replacement (`ModuleNotFoundError` for a module, `ImportError` for a name; both are
`ImportError`, so `except ImportError` fallbacks still work). Import from the top level: `from browser_use import Agent, Browser, Tools,
ActionResult, ChatBrowserUse, ChatOpenAI, ChatAnthropic, ChatGoogle`.

| 0.x | 1.0 |
|---|---|
| `browser_use.llm.openai`, `.anthropic`, `.google`, `.browser_use` (`.chat`) | `from browser_use import ChatOpenAI, ChatAnthropic, ChatGoogle, ChatBrowserUse` |
| `browser_use.llm.aws` (`ChatAWSBedrock`, `ChatAnthropicBedrock`), `.azure`, `.deepseek`, `.groq`, `.mistral`, `.openrouter`, `.cerebras`, `.vercel`, `.ollama`, `.litellm`, `.oci_raw`, `.orcarouter` | each names its model string, as in [Models](#models): e.g. `llm='bedrock:<model id>'`, `llm='azure:<deployment>'` |
| `browser_use.llm.messages` (`UserMessage`, `SystemMessage`, ...), `.base` (`BaseChatModel`), `.views`, `.schema`, `.exceptions`, `llm.ainvoke(...)`, `llm.get_client()` | the agent calls the model itself. To call one directly: `await pydantic_ai.Agent(llm.pydantic_model()).run(prompt)` (`output_type=YourModel` for structured output). `llm.model_name` / `llm.name`: `llm.model` |
| `browser_use.llm.models`, the 0.x model instances `browser_use.llm.openai_gpt_4o`, `.google_gemini_2_5_flash`, `.anthropic_claude_sonnet_4_0`, `.azure_*`, `.mistral_*`, `.cerebras_*`, `.bu_*`, `get_llm_by_name()` | a Pydantic AI model string, e.g. `llm='openai:gpt-6-luna'`, or the Chat class: each error names it (`ChatOpenAI('gpt-4o')` for `openai_gpt_4o`) |
| `browser_use.browser.session`, `.profile`, `.views`, `.watchdogs`, `.session_manager`, `.context` (`BrowserContext`, `BrowserContextConfig`), `ProxySettings` | `from browser_use import Browser`, options passed to `Browser(...)`; a proxy is `cloud_proxy_country_code` on cloud browsers (`Browser('chromium')` has no proxy yet) |
| `Browser.list_chrome_profiles()` | `Browser('chrome', profile='Work')` takes a profile's display or directory name; a name that matches none raises with the list of your profiles |
| `browser_use.browser.events` (`ScreenshotEvent`, ...), `agent.service.AgentHookFunc` | each step logs one INFO line to `logging.getLogger('browser_use')`; add a `logging.Handler` to stream progress, and read `result.messages` after the run |
| `browser_use.browser.cloud` | `Browser()` is a cloud browser (`cloud_profile_id=`, `cloud_proxy_country_code=`, `cloud_timeout=`) |
| `browser_use.controller`, `browser_use.tools.service`, `.registry`, `.views` | `from browser_use import Tools, ActionResult` (`Controller` is the same class) |
| `browser_use.agent.views`: `AgentOutput`, `AgentBrain`, `AgentState`, `AgentHistory`, `AgentStepInfo`, `StepMetadata`, `AgentError`, `AgentStructuredOutput` | `AgentHistoryList` and `ActionResult` are kept. The rest: the result `run()` returns (`status`, `text`, `output`, `error`, `usage`, `number_of_steps()`, `messages`); `Agent(output_model_schema=...)` for structured output |
| `CodeAgent`, `browser_use.code_use` | `Agent(...)`: the 1.0 agent writes Python itself |
| top-level `ActionModel`, `DomService`, `SystemPrompt` | `@tools.action(...)` on a plain function; the agent reads pages with Python; `Agent(extend_system_message=...)` |
| `browser_use.skill_cli` | the `browser-use` CLI (Python piped to browser-harness) and `browser-use --cli-mcp` |
| `browser_use.agent.prompts`, `.message_manager`, `.memory`, `.judge`, `.gif`, `.variable_detector` | removed: the 0.x loop internals. `Agent(extend_system_message=...)` adds to the fixed prompt; `result.success` is the agent's verdict |
| `browser_use.observability` (`observe`, `observe_debug`, Laminar) | see [Observability](#observability) |
| `browser_use.mcp.client` (`MCPClient`), `browser_use.mcp.controller` | call the MCP server from a plain `@tools.action` function |
| `browser_use.mcp.server` (`BrowserUseServer`) | `browser-use --cli-mcp` (see [CLI and MCP](#cli-and-mcp)) |
| `browser_use.dom`, `browser_use.actor` (`Page`, `Element`, `Mouse`) | the agent drives the page with Python and raw CDP in its REPL |
| `browser_use.filesystem` | `Agent(workspace=...)`, a plain directory |
| `browser_use.tokens` | `result.usage` and `result.cost_usd` |
| `browser_use.exceptions.LLMException` | `result.error`: `run()` returns `status='error'` for a provider failure instead of raising |
| `browser_use.config` (`load_browser_use_config`, ...), `browser_use.utils` (`time_execution_async`, ...), `browser_use.logging_config` (`addLoggingLevel`, ...) | 0.x internals: `Agent(...)` / `Browser(...)` arguments, `BROWSER_USE_LOGGING_LEVEL`; copy a helper you need |
| `browser_use.beta`, `browser_use.sandbox`, `browser_use.sync`, `browser_use.screenshots`, `browser_use.skills.service`, `browser_use.init_cmd` | removed (`screenshot()` in the agent's REPL replaces `screenshots`) |
| `browser_use.integrations` (Anthropic / OpenAI hosted-browser tools, Gmail) | none yet: they come back on the new `Browser` in a later release |

### Observability

0.x traced its own functions with Laminar (`browser_use.observability.observe`). 1.0 runs on Pydantic AI, which emits
OpenTelemetry spans for every model request and tool call (`invoke_agent`, `chat <model>`, `execute_tool python`) once
instrumentation is on: `pydantic_ai.Agent.instrument_all()` sends them to the global OpenTelemetry tracer provider
(Laminar, Langfuse, Datadog and others accept OTLP), and `logfire.instrument_pydantic_ai()` sends them to Logfire.
Spans carry prompts and cell output; pass `InstrumentationSettings(include_content=False)` to leave those out.

## CLI and MCP

The `browser-use` CLI (Python piped to browser-harness), `browser-use skill install` and `browser-use --cli-mcp` work
as before. New: `browser-use login` / `logout` (same as `browser-use auth login` / `logout`), and a `browser_login`
MCP tool that opens the browser to approve and stores the same key. The old `browser-use --mcp` server (tools like
`browser_navigate`, `browser_click`) ran the removed engine: `--mcp` now prints a deprecation notice and serves the
`--cli-mcp` tools (`browser_exec`, `browser_screenshot`). Calls to the old tool names return the removed error with the
`browser_exec` alternative; switch those clients to `--cli-mcp`. Locally `--mcp` still runs its own Chromium on a temp
profile, as 0.x did, while `--cli-mcp` drives your own Chrome with your logins. `--mcp` (and `python -m browser_use.mcp`)
keeps the `allowed_domains` / `prohibited_domains` of the default `browser_profile` in the 0.x `config.json` and
`BROWSER_USE_ALLOWED_DOMAINS`; a configured proxy (`proxy`, `BROWSER_USE_PROXY_*`) exits 2 instead of being dropped. `browser-use init` templates were removed.

The `bu` and `browser` command aliases were removed (`uv tool install` aborts when another tool already owns a name):
run `browser-use` or `browseruse`. Extras: `browser-use[cli]`, `[mcp]`, `[anthropic]`, `[google]` and `[all]` still
resolve (everything they added is now a core dependency). `[core]`, `[aws]`, `[oci]`, `[cli-oci]`, `[video]`,
`[examples]`, `[eval]` and `[openai-tools]` were removed: pip and uv warn that the extra does not exist and install
browser-use without it. For Bedrock install `pydantic-ai-slim[bedrock]` (see [Models](#models)).

Cloud browsers in the CLI and MCP server: after `start_remote_daemon(name)` (anywhere in the code) the rest of that
call, and every later MCP call, drives that cloud browser. A daemon name that ran a cloud browser never falls back to
your local Chrome once it ends: calls fail and say to start a new one (`BU_NAME=<name> browser-use --reload` lets the
name drive a local Chrome again). The MCP server stops the cloud browsers it started when it exits (also when killed)
and starts them with a 30-minute timeout unless `timeout=` is passed. The live view and CDP URLs (each grants control
of the browser) are neither opened nor returned unless `BH_OPEN_LIVE_URL=1`, and cloud tabs get no title marker.
`upload_file` sends the file's bytes through the page on a cloud browser. `stop_remote_daemon(name)` stops the cloud
browser even after its daemon was killed (again on a stopped one: a no-op), and a new `start_remote_daemon(name)` first stops one still recorded.

## Trust model for secrets

The REPL worker runs model-written Python as your user. 1.0 limits what it can see by default:

- Its environment is an allowlist (`PATH`, `HOME`, locale, temp dirs, `BU_*` / `BH_*` harness settings, and the proxy
  and CA settings `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `SSL_CERT_FILE`, ... that `http_get()` needs, with any
  password a proxy URL holds). Variables whose names contain `KEY`, `TOKEN`, `SECRET`, `PASSW`, `CREDENTIAL` or `AUTH`
  are not in its environment. That is all the allowlist does: see the last bullets below for how the worker can still
  reach your keys.
- `search()` (`web_search`) and `downloads()` ask the parent over the control channel; the parent sends the request,
  so the Browser Use key never enters the worker.
- `sensitive_data` values are sent to the worker over its control channel. The model is told only their names and
  types a value with `type_secret(name)`.
- A domain-scoped secret (`{'https://site.com': {...}}`) is typed only while the frame that receives the text (the
  focused frame, followed into iframes and shadow roots) has a matching URL, as the browser reports it (not page
  JavaScript); when that frame cannot be established it is not typed. A prompt-injected page cannot get it typed on
  another site, or into another site's iframe on the right page. The page can still move focus between that check and
  the key events.

Redaction replaces a secret value, its JSON-, `repr()`- and HTML-escaped forms, its lower- and upper-case forms, and its
reversed, base64 (also inside a longer base64 string, such as a Basic auth header), hex and URL-encoded forms, with
`<secret:name>` in exactly these places (a value under 4 characters only where it stands alone, not inside a
longer word or number; `Agent` warns about such values):

- what a cell returns to the model: its stdout/stderr (subprocesses included), its error, a `finish_from_repl` value,
  and the cell's output file in `workspace/.browser-use/cells/`
- files written by `checkpoint()` (and the partial result)
- results and retry messages of your own `Tools` actions
- the task, follow-up tasks (`add_new_task`) and `extend_system_message`, before the model sees them
- `result.final_result()`, `result.output` / `result.structured_output` (field by field), `result.partial`,
  `result.error`, and the error `Agent.run` logs. Telemetry never sends these texts at all
- `result.messages`: the model's text, thinking and tool-call arguments, and the retry messages that quote them back (a follow-up task continues the unredacted
  transcript, since providers reject edited signed thinking; screenshots in it stay unredacted)

Nothing else is redacted. This is not a sandbox:

- The values live in the worker process, so model-written Python can read them. A transform redaction does not know
  (rot13, splitting a value) passes every channel above, and a file the code writes itself (`open()`, pandas, ...) is
  never redacted.
- Screenshots are images and are not redacted: a typed value in a visible field (an email, a token, a "show
  password" field) reaches the model in a screenshot. Model-written `js()` can read a field's value back.
- A cloud browser's live view (`live_view=True`, or anyone with that URL) and any recording of the session show what
  was typed, as in any browser.
- The worker can read files your user can read (for example `~/.config/browser-harness/auth.json`, and the `.env`
  the parent loaded from its working directory).
- The worker can read the environment of other processes your user runs, including the Python process that runs
  the agent and the browser-harness daemon (`ps -E -p <pid>` on macOS, `/proc/<pid>/environ` on Linux). Every
  provider and Browser Use key set there (`OPENAI_API_KEY`, `BROWSER_USE_API_KEY`, ...) is readable that way.

Run untrusted tasks in a container or VM.

`Browser('chrome')` and `Browser('chrome', profile=...)` drive your real logins: model-written CDP can read their
cookies and (attached) your open tabs. `Browser('chromium')` and the cloud browser start with no cookies. Model code
still runs as your user and can attach to any browser on this machine with a debugging port open: other runs'
`Browser('chromium')` need no approval, your Chrome asks "Allow remote debugging?". Once the browser is gone and
cannot be reattached, the agent runs no more cells and delivers what it has.

Other users on the same machine can attach too: `Browser('chromium')` and `Browser('chrome', profile=...)` listen on
a 127.0.0.1 debugging port with no authentication, so any local account can attach to that browser, read its cookies
and drive it for as long as it runs (with `keep_alive=True`, after the run too). On a shared machine, use a container, a
VM or Browser Use Cloud.
