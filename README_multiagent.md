# Multi-Agent Orchestration for browser-use

An OS-Symphony-inspired multi-agent orchestration layer on top of browser-use. Adds Planner/Searcher/Critic agents that collaborate each step, while delegating all browser interaction to the standard browser-use Agent.

## Architecture

```
┌─────────────────────────────────────────────┐
│            MultiAgentOrchestrator           │
│                                             │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Searcher │ │ Planner  │ │   Critic   │  │
│  │ (intel)  │ │ (action) │ │ (review)   │  │
│  └────┬─────┘ └────┬─────┘ └─────┬──────┘  │
│       │             │             │          │
│       └─────────────┼─────────────┘          │
│                     ▼                        │
│          ┌──────────────────┐                │
│          │  browser-use     │                │
│          │  Agent.run()     │                │
│          │  (step hooks)    │                │
│          └──────────────────┘                │
└─────────────────────────────────────────────┘
```

### Per-Step Control Flow

1. **State**: browser-use Agent prepares DOM/screenshot/history (unchanged)
2. **Searcher** (conditional): gathers intel on first step or when stuck
3. **Planner**: analyzes state + intel, recommends action
4. **Critic**: reviews planner's recommendation, approves/revises/aborts
5. **Execute**: browser-use Agent executes one action (unchanged)
6. **Log**: structured per-step JSON logs saved to run directory

## Quick Start

```bash
# From the browser-use repo root
python scripts/run_multiagent.py \
  --config configs/multiagent_default.yaml \
  --task "Search for the latest Python release and extract the version number"

# With headless browser
python scripts/run_multiagent.py \
  --config configs/multiagent_default.yaml \
  --task "Find the current Bitcoin price" \
  --headless

# Override max steps and log level
python scripts/run_multiagent.py \
  --config configs/multiagent_default.yaml \
  --task "Navigate to example.com and extract the main heading" \
  --max-steps 20 \
  --log-level DEBUG
```

## Configuration

Configs live in `configs/`. Two examples are provided:

- `configs/multiagent_default.yaml` — vLLM backend (local inference)
- `configs/multiagent_azure.yaml` — Azure OpenAI backend

### YAML Structure

```yaml
agents:
  planner:
    enabled: true
    prompt_path: prompts/planner.md    # external prompt file
    provider:
      type: vllm                        # or "azure"
      model_name: Qwen3VL_32b
      base_url: http://127.0.0.1:3333/v1
      temperature: 0.2
      max_completion_tokens: 4096
    budget_max_calls: 100

  searcher:
    enabled: true
    prompt_path: prompts/searcher.md
    provider: { ... }
    budget_max_calls: 30

  critic:
    enabled: true
    prompt_path: prompts/critic.md
    provider: { ... }
    budget_max_calls: 60

orchestrator:
  max_steps: 50
  loop_detection_window: 5
  loop_detection_threshold: 3
  searcher_on_first_step: true
  always_use_critic: true
  abort_on_critic_reject_count: 3

logging:
  run_dir_base: runs/multiagent
  experiment_name: my_experiment
  save_screenshots: true
  log_level: INFO
```

### Per-Agent Providers

Each agent can use a different LLM provider:

**vLLM** (default):
- `base_url` defaults to `http://127.0.0.1:3333/v1` (override: `VLLM_BASE_URL`)
- `model_name` defaults to `Qwen3VL_32b` (override: `VLLM_MODEL_NAME`)

**Azure OpenAI**:
- `api_key`: override via `AZURE_OPENAI_API_KEY`
- `api_base`: override via `AZURE_OPENAI_ENDPOINT`
- `api_version`: override via `AZURE_OPENAI_API_VERSION`
- `proxy_url`: defaults to `http://127.0.0.1:9090` (override: `AZURE_PROXY_URL`)
- Proxy env vars are set **only during Azure API calls** via context manager, not globally.

### Adding New Agents

1. Create `multiagent/agents/my_agent.py` subclassing `BaseAgent`
2. Add a prompt file `prompts/my_agent.md`
3. Add the agent to YAML config under `agents:`
4. Reference it in the orchestrator's step hooks

## Prompts

Default prompts live in `prompts/`:
- `prompts/planner.md` — main reasoner
- `prompts/searcher.md` — information gatherer
- `prompts/critic.md` — quality reviewer

YAML config references these by path. To experiment with different prompts, copy and modify, then update the `prompt_path` in your config.

## Logs & Artifacts

Each run creates: `runs/multiagent/YYYYMMDD_HHMMSS_<experiment_name>/`

```
runs/multiagent/20260210_143022_default/
├── config.yaml              # copy of YAML used
├── config_snapshot.json     # parsed config
├── run.log                  # Python log output
├── summary.json             # final run summary
├── steps/
│   ├── step_0001.json       # per-step structured log
│   ├── step_0002.json
│   └── ...
└── artifacts/
    ├── step_0001_screenshot_*.png
    └── ...
```

## Return Type Compatibility

`MultiAgentOrchestrator.run()` returns `AgentHistoryList` — the exact same type as `Agent.run()`. This means all existing post-processing, analysis, and reporting tools work unchanged.

## Upstream Modifications

**None.** This implementation uses only:
- New files under `multiagent/`, `configs/`, `prompts/`, `scripts/`
- browser-use's public API: `Agent`, `BrowserSession`, `BrowserProfile`, LLM providers
- `Agent.run()` hooks: `on_step_start` and `on_step_end` callbacks

No files in `browser_use/` were modified.

## File Tree

```
multiagent/
├── __init__.py
├── config.py                  # YAML schema + strict validation + defaults
├── orchestrator.py            # main loop; integrates with browser-use runner
├── logging.py                 # structured logs + run dir management
├── providers/
│   ├── __init__.py
│   ├── base.py                # LLM factory from config
│   └── proxy_scope.py         # context manager for per-call proxy env
└── agents/
    ├── __init__.py
    ├── base.py                # base advisory agent
    ├── planner.py             # main reasoner + action decider
    ├── searcher.py            # information gatherer (isolated browsing)
    └── critic.py              # reviewer + loop detector

configs/
├── multiagent_default.yaml    # vLLM backend
└── multiagent_azure.yaml      # Azure OpenAI backend

prompts/
├── planner.md
├── searcher.md
└── critic.md

scripts/
└── run_multiagent.py          # CLI entrypoint
```
