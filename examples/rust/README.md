# browser_use.rust — examples

These examples drive the new Rust-backed agent (the `browser-use-terminal`
binary from [browser-use/terminal](https://github.com/browser-use/terminal))
through a Python `Agent` interface that mirrors the classic
`browser_use.Agent`.

## Prereqs

1. The standalone Rust binaries installed. From any shell:

   ```bash
   curl -fsSL https://browser-use.com/install.sh | sh
   ```

   This drops `but` (the TUI) and `browser-use-terminal` (headless CLI)
   under `~/.browser-use-terminal/...`.

2. A working provider credential — e.g. `OPENAI_API_KEY` in the env, a
   prior `codex login`, etc. Run `browser-use-terminal auth status` to
   confirm.

## What's here

| File | What it shows |
|------|---------------|
| `00_all_options.py` | Every `Agent(...)` kwarg in one place. Prints the resolved subprocess argv without spending API credits. |
| `01_simple_task.py` | The shortest possible end-to-end run. One line in main. |
| `02_follow_up.py` | Multi-turn — `follow_up()` reuses the session id and the open browser tab. |
| `03_with_llm.py` | Pass a `browser_use.llm.ChatXxx` to pick provider + model. |
| `04_stream_events.py` | Live typed-event stream (`run_streaming()`) while the agent runs. |
| `05_cancellation.py` | Cancel after 3s; cooperative `cancel <id>` → SIGINT → terminate ladder. |
| `06_output_model.py` | Hand a Pydantic class via `output_model=` and get a typed final result. |
| `eval_one_task.py` | Fetch and run one eval task locally with the Rust wrapper. |
| `eval_one_task_cloud.py` | Fetch and run one eval task through the Rust wrapper attached to a Browser Use Cloud browser. |

## Run

```bash
# from the browser-use repo root
uv run python examples/rust/01_simple_task.py
```

## Backward compatibility

`from browser_use import Agent` — unchanged. Same Python loop, same CDP
client, same kwargs. Use whichever Agent fits the task; both can run
side-by-side in the same process.
