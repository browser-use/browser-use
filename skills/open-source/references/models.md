# Models (browser-use 1.0)

`Agent(task)` with no `llm` runs `bu-fast` on the Browser Use gateway: one `BROWSER_USE_API_KEY` (or
`browser-use login`) pays for the model and the cloud browser.

## Quick reference

| What | How | Key |
|---|---|---|
| Browser Use gateway (default) | `llm=None`, `'bu-fast'`, `'bu-ultrafast'`, `'bu-smart'`, or `ChatBrowserUse(model)` | `BROWSER_USE_API_KEY` |
| OpenAI | `ChatOpenAI('gpt-6-luna')` | `OPENAI_API_KEY` |
| OpenAI-compatible server (vLLM, Ollama, DeepSeek, ...) | `ChatOpenAI(model, base_url=..., api_key=...)` | the server's |
| Anthropic | `ChatAnthropic('claude-opus-5-5')` or `'anthropic:claude-opus-5-5'` | `ANTHROPIC_API_KEY` |
| Google Gemini | `ChatGoogle('gemini-3.5-flash')` or `'google:gemini-3.5-flash'` | `GOOGLE_API_KEY` |
| Anything Pydantic AI supports | a model string: `'groq:llama-3.3-70b'`, `'openrouter:anthropic/claude-sonnet-4-6'`, `'mistral:...'`, `'bedrock:...'`, or a Pydantic AI `Model` | the provider's |

## Browser Use gateway

```python
from browser_use import Agent, ChatBrowserUse

agent = Agent('Find the top post on Hacker News')                 # bu-fast (default)
agent = Agent('Find the top post on Hacker News', llm='bu-ultrafast')  # same as ChatBrowserUse('bu-ultrafast')
```

| Model | What it is |
|---|---|
| `bu-fast` (default) | `gpt-6-luna`, medium reasoning, default tier: the configuration we evaluate (`bu-auto` is the same) |
| `bu-ultrafast` | the same model at low reasoning on the priority tier: the fastest |
| `bu-smart` | `gpt-6.1-sol`, a larger model at high reasoning |
| a listed OpenAI model, e.g. `gpt-6-luna` | that model through the gateway |

`Agent(reasoning='low' | 'medium' | 'high')` overrides the alias's own effort. Prices and the full list:
`GET https://api.browser-use.com/api/v4/llm/v1/models`. `result.cost_usd` is exactly what the gateway charged.

`bu-2-0`, `bu-2-0-mini-preview`, `bu-1-0` and `bu-latest` were the 0.x models. browser-use 1.0 rejects them before a
browser starts: keep `browser-use<1.0` for them, or switch to `bu-fast`.

## Your own model

```python
from browser_use import Agent, ChatAnthropic, ChatOpenAI

Agent(task, llm=ChatOpenAI('gpt-6-luna'))                    # api.openai.com, Responses API
Agent(task, llm=ChatOpenAI('qwen3', base_url='http://localhost:11434/v1', api_key='ollama'))  # chat completions
Agent(task, llm=ChatAnthropic('claude-opus-5-5'))
Agent(task, llm='groq:llama-3.3-70b')                        # pip install 'pydantic-ai-slim[groq]'
```

The 0.x provider classes (`ChatGroq`, `ChatOllama`, `ChatAzureOpenAI`, `ChatDeepSeek`, `ChatMistral`,
`ChatOpenRouter`, `ChatAWSBedrock`, `ChatAnthropicBedrock`, `ChatCerebras`, `ChatLiteLLM`, `ChatOCIRaw`,
`ChatOrcaRouter`, `ChatVercel`) were removed: use a Pydantic AI model string or `ChatOpenAI(model, base_url=...)`.

### Open weights (self-hosted)

`bu-30b-a3b-preview` is our open-weights browser model: 30B total, 3B active, 64K context. The gateway does not serve
it. Run it yourself and talk to it with `ChatOpenAI`:

```bash
vllm serve browser-use/bu-30b-a3b-preview --max-model-len 65536 --host 0.0.0.0 --port 8000
```

```python
from browser_use import ChatOpenAI

llm = ChatOpenAI('browser-use/bu-30b-a3b-preview', base_url='http://localhost:8000/v1', api_key='not-needed')
```

Weights: https://huggingface.co/browser-use/bu-30b-a3b-preview
