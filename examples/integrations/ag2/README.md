# AG2 Multi-Agent Web Research

Multi-agent web research system using [AG2](https://docs.ag2.ai) for agent coordination and [browser-use](https://docs.browser-use.com) for autonomous web browsing.

## What It Does

Three AG2 agents collaborate via GroupChat to research a topic:

```
User Question
     |
     v
+---------------------------+
|  Planner Agent            |  Decomposes question into 2-4 browsing tasks
+---------------------------+
     |
     v
+---------------------------+
|  Browser Agent            |  Calls browse_web() for each task
|                           |       |
|  browse_web(task) ------->|  browser-use Agent autonomously:
|                           |    - navigates to websites
|                           |    - extracts relevant data
|                           |    - returns findings as text
+---------------------------+
     |
     v
+---------------------------+
|  Synthesizer Agent        |  Combines all results into a report
|                           |  Says TERMINATE when done
+---------------------------+
```

The `browse_web` tool bridges AG2 (sync) and browser-use (async) — each call spins up a fresh browser-use Agent with its own headless Chromium instance.

## Prerequisites

- Python 3.11+
- `OPENAI_API_KEY` environment variable
- Playwright browsers installed

## Install

```bash
pip install browser-use "ag2[openai]>=0.11.4,<1.0" langchain-openai
playwright install chromium
```

## Run

```bash
export OPENAI_API_KEY=sk-...
python main.py
```

## Configuration

| Environment Variable      | Default       | Description                          |
|---------------------------|---------------|--------------------------------------|
| `OPENAI_API_KEY`          | (required)    | OpenAI API key                       |
| `OPENAI_MODEL`            | `gpt-4o-mini` | Model for both AG2 and browser-use   |
| `BROWSER_USE_HEADLESS`    | `true`        | Set to `false` to see the browser UI |

## How It Works

1. **UserProxy** sends the research question to the GroupChat
2. **Planner** breaks it into specific browsing tasks (e.g., "Go to provider X's pricing page and find GPU costs")
3. **Browser Agent** calls `browse_web(task)` for each task — browser-use launches Chromium, navigates, extracts data, and returns results
4. **Synthesizer** reads all browsing results and writes a structured report
5. Synthesizer says `TERMINATE` to end the conversation

Each `browse_web` call creates an isolated browser session that is cleaned up after use.

## Links

- [AG2 Documentation](https://docs.ag2.ai)
- [browser-use Documentation](https://docs.browser-use.com)
