# Supported LLM Models

Browser Use natively supports 15+ LLM providers. Most providers accept any model string — check each provider's docs to see which models are available.

## Quick Reference

| Provider | Class | Env Variable |
|----------|-------|--------------|
| Browser Use Cloud | `ChatBrowserUse` | `BROWSER_USE_API_KEY` |
| OpenAI | `ChatOpenAI` | `OPENAI_API_KEY` |
| Anthropic | `ChatAnthropic` | `ANTHROPIC_API_KEY` |
| Google Gemini | `ChatGoogle` | `GOOGLE_API_KEY` |
| Azure OpenAI | `ChatAzureOpenAI` | `AZURE_OPENAI_*` |
| AWS Bedrock | `ChatAWSBedrock` | `AWS_ACCESS_KEY_ID` |
| DeepSeek | `ChatDeepSeek` | `DEEPSEEK_API_KEY` |
| Mistral | `ChatMistral` | `MISTRAL_API_KEY` |
| Groq | `ChatGroq` | `GROQ_API_KEY` |
| Cerebras | `ChatCerebras` | `CEREBRAS_API_KEY` |
| Ollama | `ChatOllama` | — |
| OpenRouter | `ChatOpenRouter` | `OPENROUTER_API_KEY` |
| Vercel AI Gateway | `ChatVercel` | `AI_GATEWAY_API_KEY` |
| OCI (Oracle) | `ChatOCIRaw` | OCI config file |
| LiteLLM | `ChatLiteLLM` | Provider-specific |

## Recommendations by Use Case

Based on our [benchmark of real-world browser tasks](https://browser-use.com/posts/what-model-to-use):

- **Maximum performance**: Browser Use Cloud `bu-ultra` — 78% accuracy, ~14 tasks/hour
- **Best open-source + cloud LLM**: `ChatBrowserUse(model='bu-2-0')` — 63.3% accuracy, outperforms every standalone frontier model
- **Best standalone model**: `claude-opus-4-6` — 62% accuracy, excels at custom JavaScript and structured data extraction
- **Best value**: `claude-sonnet-4-6` — 59% accuracy, near-opus quality at lower cost
- **Fast + capable**: `gemini-3-1-pro` — 59.3% accuracy

## Table of Contents
- [Browser Use Cloud (Recommended)](#browser-use-cloud)
- [OpenAI](#openai)
- [Anthropic](#anthropic)
- [Google Gemini](#google-gemini)
- [Azure OpenAI](#azure-openai)
- [AWS Bedrock](#aws-bedrock)
- [DeepSeek](#deepseek)
- [Mistral](#mistral)
- [Groq](#groq)
- [Cerebras](#cerebras)
- [Ollama (Local)](#ollama-local)
- [OpenRouter](#openrouter)
- [Vercel AI Gateway](#vercel-ai-gateway)
- [OCI (Oracle)](#oci-oracle)
- [LiteLLM (100+ Providers)](#litellm-100-providers)
- [OpenAI-Compatible APIs](#openai-compatible-apis)

---

## Browser Use Cloud

Optimized for browser automation — highest accuracy, fastest speed, lowest token cost.

```python
from browser_use import Agent, ChatBrowserUse

llm = ChatBrowserUse()                    # bu-latest (default)
llm = ChatBrowserUse(model='bu-2-0')      # Premium model
```

**Env:** `BROWSER_USE_API_KEY` — get at https://cloud.browser-use.com/new-api-key

**Models & Pricing (per 1M tokens):**
| Model | Input | Cached | Output |
|-------|-------|--------|--------|
| bu-1-0 / bu-latest (default) | $0.20 | $0.02 | $2.00 |
| bu-2-0 (premium) | $0.60 | $0.06 | $3.50 |
| browser-use/bu-30b-a3b-preview (OSS) | — | — | — |

## OpenAI

```python
from browser_use import Agent, ChatOpenAI

llm = ChatOpenAI(model="gpt-5")
```

**Env:** `OPENAI_API_KEY` | [Available models](https://platform.openai.com/docs/models)

Supports custom `base_url` for OpenAI-compatible APIs.

## Anthropic

```python
from browser_use import Agent, ChatAnthropic

llm = ChatAnthropic(model='claude-sonnet-4-6', temperature=0.0)
```

**Env:** `ANTHROPIC_API_KEY` | [Available models](https://docs.anthropic.com/en/docs/about-claude/models)

Coordinate clicking is automatically enabled for `claude-sonnet-4-*` and `claude-opus-4-*` models.

## Google Gemini

```python
from browser_use import Agent, ChatGoogle

llm = ChatGoogle(model="gemini-2.5-flash")
llm = ChatGoogle(model="gemini-3-pro-preview")
```

**Env:** `GOOGLE_API_KEY` (free at https://aistudio.google.com/app/u/1/apikey) | [Available models](https://ai.google.dev/api/models)

Supports Vertex AI via `ChatGoogle(model="...", vertexai=True)`.

Note: `GEMINI_API_KEY` is deprecated, use `GOOGLE_API_KEY`.

## Azure OpenAI

Supports the Responses API for codex and computer-use models.

```python
from browser_use import Agent, ChatAzureOpenAI

llm = ChatAzureOpenAI(
    model="gpt-5",
    api_version="2025-03-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)
```

**Env:** `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` | [Available models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure)

## AWS Bedrock

```python
from browser_use import Agent, ChatAWSBedrock

llm = ChatAWSBedrock(model="us.anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")

# Or via Anthropic wrapper
from browser_use import ChatAnthropicBedrock
llm = ChatAnthropicBedrock(model="us.anthropic.claude-sonnet-4-20250514-v1:0", aws_region="us-east-1")
```

**Env:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | [Available models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-ids.html)

Supports profiles, IAM roles, SSO via standard AWS credential chain. Install with `pip install "browser-use[aws]"`.

## DeepSeek

```python
from browser_use import Agent, ChatDeepSeek

llm = ChatDeepSeek(model="deepseek-chat")
```

**Env:** `DEEPSEEK_API_KEY` | [Available models](https://api-docs.deepseek.com/quick_start/pricing)

## Mistral

```python
from browser_use import Agent, ChatMistral

llm = ChatMistral(model="mistral-large-latest")
```

**Env:** `MISTRAL_API_KEY` | [Available models](https://docs.mistral.ai/getting-started/models/models_overview/)

## Groq

```python
from browser_use import Agent, ChatGroq

llm = ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct")
```

**Env:** `GROQ_API_KEY` | [Available models](https://console.groq.com/docs/models)

## Cerebras

```python
from browser_use import Agent, ChatCerebras

llm = ChatCerebras(model="llama3.3-70b")
```

**Env:** `CEREBRAS_API_KEY` | [Available models](https://inference-docs.cerebras.ai/models/overview)

## Ollama (Local)

```python
from browser_use import Agent, ChatOllama

llm = ChatOllama(model="llama3", num_ctx=32000)
```

[Available models](https://ollama.com/library). Requires `ollama serve` running locally. Use `num_ctx` for context window (default may be too small).

## OpenRouter

Access 300+ models from any provider through a single API.

```python
from browser_use import Agent, ChatOpenRouter

llm = ChatOpenRouter(model="anthropic/claude-sonnet-4-6")
```

**Env:** `OPENROUTER_API_KEY` | [Available models](https://openrouter.ai/models)

## Vercel AI Gateway

Proxy to multiple providers with automatic fallback:

```python
from browser_use import Agent, ChatVercel

llm = ChatVercel(
    model='anthropic/claude-sonnet-4-6',
    provider_options={
        'gateway': {
            'order': ['vertex', 'anthropic'],  # Fallback order
        }
    },
)
```

**Env:** `AI_GATEWAY_API_KEY` (or `VERCEL_OIDC_TOKEN` on Vercel) | [Available models](https://vercel.com/ai-gateway/models)

## OCI (Oracle)

```python
from browser_use import Agent, ChatOCIRaw

llm = ChatOCIRaw(
    model="meta.llama-3.1-70b-instruct",
    service_endpoint="https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
    compartment_id="your-compartment-id",
)
```

Requires `~/.oci/config` setup and `pip install "browser-use[oci]"`. [Available models](https://docs.oracle.com/en-us/iaas/Content/generative-ai/imported-models.htm). Auth types: `API_KEY`, `INSTANCE_PRINCIPAL`, `RESOURCE_PRINCIPAL`.

## LiteLLM (100+ Providers)

Requires separate install (`pip install litellm`).

```python
from browser_use.llm.litellm import ChatLiteLLM

llm = ChatLiteLLM(model="openai/gpt-5")
llm = ChatLiteLLM(model="anthropic/claude-sonnet-4-6")
```

Supports any [LiteLLM model string](https://docs.litellm.ai/docs/providers). Useful when you need a provider not covered by the native integrations above.

## OpenAI-Compatible APIs

Any provider with an OpenAI-compatible endpoint works via `ChatOpenAI`:

### Qwen (Alibaba)
```python
llm = ChatOpenAI(model="qwen-vl-max", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
```
**Env:** `ALIBABA_CLOUD`

### ModelScope
```python
llm = ChatOpenAI(model="Qwen/Qwen2.5-VL-72B-Instruct", base_url="https://api-inference.modelscope.cn/v1")
```
**Env:** `MODELSCOPE_API_KEY`

### Novita
```python
llm = ChatOpenAI(model="deepseek/deepseek-r1", base_url="https://api.novita.ai/v3/openai")
```
**Env:** `NOVITA_API_KEY`

### LangChain
See example at [examples/models/langchain](https://github.com/browser-use/browser-use/tree/main/examples/models/langchain).
