# Supported Models

Browser Use supports multiple LLM providers. Below is a comprehensive list of supported models and their configurations.

## Quick Reference

| Provider | Class | Recommended Model | API Key |
|----------|-------|-------------------|---------|
| Browser Use Cloud | `ChatBrowserUse()` | `bu-2-0` (premium) | `BROWSER_USE_API_KEY` |
| OpenAI | `ChatOpenAI()` | `o3` | `OPENAI_API_KEY` |
| Anthropic | `ChatAnthropic()` | `claude-sonnet-4-0` | `ANTHROPIC_API_KEY` |
| Google Gemini | `ChatGoogle()` | `gemini-flash-latest` | `GOOGLE_API_KEY` |
| Azure OpenAI | `ChatAzure()` | `gpt-4o` | `AZURE_OPENAI_*` |
| OpenAI Compatible | `ChatOpenAI(base_url=...)` | Any | Provider-specific |

## Browser Use Cloud

Our optimized in-house model, matching top model accuracy while completing tasks **3-5x faster**.

```python
from browser_use import Agent, ChatBrowserUse

# Default model (bu-latest)
llm = ChatBrowserUse()

# Premium model
llm = ChatBrowserUse(model='bu-2-0')
```

**Available Models:**
- `bu-latest` or `bu-1-0`: Default model
- `bu-2-0`: Latest premium model with improved capabilities

## OpenAI

```python
from browser_use import Agent, ChatOpenAI

llm = ChatOpenAI(model="o3")
```

**Available Models:**
- `o3`: Recommended for best accuracy
- `gpt-4.1`: High performance
- `gpt-4.1-mini`: Cost-effective option
- `gpt-4o`: Previous generation flagship
- `gpt-4o-mini`: Budget-friendly

## Anthropic

```python
from browser_use import Agent, ChatAnthropic

llm = ChatAnthropic(model='claude-sonnet-4-0', temperature=0.0)
```

**Available Models:**
- `claude-sonnet-4-0`: Recommended balanced model
- `claude-opus-4-0`: Maximum capability
- `claude-haiku-4-0`: Fast and affordable

## Google Gemini

```python
from browser_use import Agent, ChatGoogle

llm = ChatGoogle(model='gemini-flash-latest')
```

**Available Models:**
- `gemini-flash-latest`: Recommended for speed
- `gemini-pro-latest`: For complex tasks

> **Note:** Use `GOOGLE_API_KEY` (not `GEMINI_API_KEY` which is deprecated).

## Azure OpenAI

```python
from browser_use import Agent, ChatAzure

llm = ChatAzure(model="gpt-4o")
```

Configure with environment variables:
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`

## OpenAI Compatible Providers

You can use any OpenAI-compatible API by specifying a custom `base_url`:

```python
from browser_use import Agent, ChatOpenAI

llm = ChatOpenAI(
    model="your-model-name",
    base_url="https://your-api-endpoint.com/v1",
    api_key="your-api-key"
)
```

This works with providers like:
- Ollama (local models)
- LM Studio
- Together AI
- Groq
- DeepSeek
- And many more

## Tips

- **Best accuracy**: Use `o3` (OpenAI) or `bu-2-0` (Browser Use Cloud)
- **Best speed**: Use `ChatBrowserUse()` or `gemini-flash-latest`
- **Best value**: Use `gpt-4.1-mini` or `claude-haiku-4-0`
- Set `temperature=0.0` for deterministic behavior

For more examples, see the [models examples directory](https://github.com/browser-use/browser-use/tree/main/examples/models).
