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
| Key | per provider | one Browser Use key: `browser-use auth login` or `BROWSER_USE_API_KEY` |
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
| `sensitive_data` | kept as `{'name': 'value'}`: the model types values with `type_secret('name')` and sees `<secret:name>`. Domain-scoped `{'https://site': {...}}` raises |
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
| `llm_timeout`, `step_timeout` | raises: `agent.run(timeout=seconds)` bounds the whole run |
| `fallback_llm` | raises |
| `use_judge`, `judge_llm`, `ground_truth` | raises |
| `generate_gif`, `demo_mode` | raises |
| `save_conversation_path`, `save_conversation_path_encoding` | raises: `result.messages` holds the transcript |
| `calculate_cost`, `pricing_url` | raises: `result.cost_usd` is computed when the price is known (`None` otherwise) |
| `skill_ids`, `skills`, `skill_service` | raises: Cloud Skills were removed |
| `enable_planning`, `planning_replan_on_stall`, `planning_exploration_limit`, `loop_detection_window`, `loop_detection_enabled`, `message_compaction`, `max_history_items`, `include_attributes`, `max_clickable_elements_length`, `include_recent_events`, `include_tool_call_examples`, `display_files_in_done_text`, `injected_agent_state`, `source`, `task_id`, `enable_signal_handler`, `_url_shortening_limit` | raises: these tuned the 0.x loop |
| new: `reasoning`, `mode`, `workspace` | `reasoning='medium'`; `mode='ultrafast'`; `workspace` holds the agent's files (default: a temp dir) |

## Agent methods

| 0.x | 1.0 |
|---|---|
| `await agent.run(max_steps=100)` | kept; also `timeout=1700` (seconds). `on_step_start` / `on_step_end` raise |
| `agent.run_sync()` | kept |
| `agent.add_new_task(task)` | kept: the next `run()` continues the same conversation |
| `await agent.close()`, `async with Agent(...)` | kept |
| browser stops when `run()` ends | kept, unless `Browser(keep_alive=True)` |
| `pause()`, `resume()`, `stop()`, `step()`, `multi_act()` | removed |
| `save_history()`, `load_and_rerun()`, `rerun_history()`, `detect_variables()` | removed |

## The result (AgentHistoryList)

| 0.x | 1.0 |
|---|---|
| `final_result()`, `is_done()`, `is_successful()`, `structured_output`, `errors()`, `has_errors()`, `total_duration_seconds()`, `number_of_steps()` | kept |
| `history`, `urls()`, `screenshots()`, `screenshot_paths()`, `action_names()`, `action_history()`, `action_results()`, `model_thoughts()`, `model_outputs()`, `model_actions()`, `model_actions_filtered()`, `extracted_content()`, `agent_steps()`, `last_action()`, `save_to_file()`, `load_from_file()`, `get_structured_output()`, `add_item()`, `judgement()`, `is_judged()`, `is_validated()` | raise `NotImplementedError`: there are no per-step actions. Use `result.messages`, `result.status`, `result.partial` and the files in `agent.workspace` |
| new | `status` (`completed`, `max_steps`, `timeout`, `error`), `partial` (last `checkpoint(..., partial=True)`), `usage`, `cost_usd`, `messages` |

## Browser(...)

| 0.x | 1.0 |
|---|---|
| `Browser()` / `BrowserSession()` | `Browser()` is now a cloud browser; `BrowserSession` and `BrowserProfile` imports raise |
| `Browser(use_cloud=True)` | kept (now the default) |
| local Chromium (`headless`, `user_data_dir`, `executable_path`, ...) | raises: `Browser(local=True)` drives your Chrome through browser-harness |
| `cdp_url=` | kept |
| `keep_alive=True` | kept |
| `cloud_profile_id`, `cloud_proxy_country_code`, `cloud_timeout` | kept |
| `allowed_domains`, `prohibited_domains` | raise: not in 1.0 yet |
| `proxy`, `storage_state` | raise: use `cloud_proxy_country_code` / `cloud_profile_id` |
| `Browser.from_system_chrome()` | not yet |

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

## CLI and MCP

The `browser-use` CLI (Python piped to browser-harness), `browser-use skill install` and `browser-use --cli-mcp` work
as before. `--cli-mcp` now needs `pip install 'browser-use[mcp]'`. The old `browser-use --mcp` server (tools like
`browser_navigate`, `browser_click`) ran the removed engine: `--mcp` now prints a deprecation notice and serves the
`--cli-mcp` tools (`browser_exec`, `browser_screenshot`). MCP clients that call the old tool names break; switch them
to `--cli-mcp`. `browser-use init` templates were removed.

## Trust model for secrets

The REPL worker runs model-written Python as your user. 1.0 limits what it can see by default:

- Its environment is an allowlist (`PATH`, `HOME`, locale, temp dirs, `BU_*` / `BH_*` harness settings). Variables
  whose names contain `KEY`, `TOKEN`, `SECRET`, `PASSW`, `CREDENTIAL` or `AUTH` never reach it.
- `sensitive_data` values travel over the worker's control channel, are usable only through `type_secret(name)`,
  and are replaced with `<secret:name>` in all output the model sees.

This is not a sandbox. The worker can still read files your user can read (for example
`~/.config/browser-harness/auth.json`), and a value transformed before printing (reversed, encoded) is not caught.
Run untrusted tasks in a container or VM.
