# CLAUDE.md

Guidance for coding agents working in this repository (AGENTS.md has the same content).

Browser Use 1.0 is a browser agent on [Pydantic AI](https://ai.pydantic.dev). The model does not pick one action per
step from a DOM dump: it writes Python in one persistent REPL that has the
[browser-harness](https://github.com/browser-use/browser-harness) helpers and raw CDP. The 0.x public API (`Agent`,
`Browser`, `Tools`, `run()`, `final_result()`) is kept on top; MIGRATING.md lists every 0.x option and its 1.0 answer.

## Architecture

```
Agent(task, llm, browser).run()                  browser_use/agent/service.py   0.x API, telemetry, lifecycle
  -> resolve_model(llm)                          browser_use/llm/__init__.py    bu-fast gateway default, ChatOpenAI/Anthropic/Google, model strings
  -> Browser.start() -> env for the worker       browser_use/browser/browser.py cloud (API v4, default) | 'chromium' (local.py) | 'chrome' (harness daemon) | cdp_url
  -> run(agent, task, Session)                   browser_use/agent/loop.py      Pydantic AI loop: python tool, finish / finish_from_repl,
                                                                                image pruning, delivery guards, budgets, partial results
       python(code) -> Repl.call()               browser_use/repl/session.py    parent side: spawns the worker, allowlisted env, redaction
                    -> worker process            browser_use/repl/worker.py     runs cells; helpers, screenshot, checkpoint, type_secret
                       mode='ultrafast' adds bu  browser_use/ax.py              accessibility-tree helpers (port of Browser Use Pi ax.ts)
  <- AgentHistoryList                            browser_use/agent/views.py     status, text/output, success, partial, usage, cost_usd, messages
```

- The system prompt is `browser_use/agent/prompt.py`. It is evaluated; do not edit it casually.
- The REPL worker is a child process in its own process group: a cell timeout kills the tree and restarts it. Files
  and browser state survive, Python variables do not.
- Secrets (`sensitive_data`) are redacted from specific channels (listed in "Trust model" in MIGRATING.md), not sandboxed.
- `browser-use` CLI and `--cli-mcp` (`browser_use/cli.py`, `browser_use/mcp/`) pipe Python to browser-harness.
- `browser_use/skills/` ships the `browser-use` agent skill and its installer.

## Development

```bash
uv sync --all-extras
uv run pytest tests/ci                 # no provider calls, no cloud; tests needing Chrome skip without it
uv run pytest tests/ci -m "not chrome" # what the Windows/macOS/Linux matrix runs
uv run ruff check && uv run ruff format
uv run pyright
```

## Rules

- Use `uv`, tabs, modern typing (`str | None`).
- Do not replace model names; users try models you do not know yet.
- Tests use a real REPL worker and a real headless Chrome (`tests/ci/conftest.py`), and a scripted `FunctionModel`
  instead of a provider. Never call paid APIs or create cloud browsers in tests; mock the cloud HTTP calls.
- One regression test per bug, failing before the fix.
- 0.x options 1.0 cannot honor raise a `TypeError` naming the option before any browser starts; keep MIGRATING.md in
  sync when you add or remove one.
- Never create example files to show off a feature.
