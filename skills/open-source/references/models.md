# Supported LLM Models

## Table of Contents
- [Browser Use (Recommended)](#browser-use)
- [Google Gemini](#google-gemini)
- [OpenAI](#openai)
- [Anthropic](#anthropic)
- [Azure OpenAI](#azure-openai)
- [AWS Bedrock](#aws-bedrock)
- [Groq](#groq)
- [OCI (Oracle)](#oci-oracle)
- [Ollama (Local)](#ollama-local)
- [Vercel AI Gateway](#vercel-ai-gateway)
- [OpenAI-Compatible APIs](#openai-compatible-apis)

---

## Browser Use

Optimized for browser automation — highest accuracy, fastest speed, lowest token cost.

```python
from browser_use import ChatBrowserUse
llm = ChatBrowserUse()                    # bu-latest (default)
llm = ChatBrowserUse(model='bu-2-0')      # Premium model
```

**Env:** `BROWSER_USE_API_KEY` — get at https://cloud.browser-use.com/new-api-key

**Models & Pricing (per 1M tokens):**
| Model | Input | Cached | Output |
|-------|-------|--------|--------|
| bu-1-0 (default) | $0.20 | $0.02 | $2.00 |
| bu-2-0 (premium) | $0.60 | $0.06 | $3.50 |

## Google Gemini

```python
from browser_use import ChatGoogle
llm = ChatGoogle(model="gemini-flash-latest")
```

**Env:** `GOOGLE_API_KEY` (free at https://aistudio.google.com/app/u/1/apikey)

Note: `GEMINI_API_KEY` is deprecated, use `GOOGLE_API_KEY`.

## OpenAI

```python
from browser_use import ChatOpenAI
llm = ChatOpenAI(model="gpt-4.1-mini")
# o3 recommended for complex tasks
llm = ChatOpenAI(model="o3")
```

**Env:** `OPENAI_API_KEY`

Supports custom `base_url` for OpenAI-compatible APIs.

## Anthropic

```python
from browser_use import ChatAnthropic
llm = ChatAnthropic(model='claude-sonnet-4-0', temperature=0.0)
```

**Env:** `ANTHROPIC_API_KEY`

## Azure OpenAI

```python
from browser_use import ChatAzureOpenAI
llm = ChatAzureOpenAI(
    model="gpt-4o",
    api_version="2025-03-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
)
```

**Env:** `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`

Supports Responses API for models like `gpt-5.1-codex-mini`.

## AWS Bedrock

```python
from browser_use import ChatAWSBedrock
llm = ChatAWSBedrock(model="us.anthropic.claude-sonnet-4-20250514-v1:0", region="us-east-1")

# Or via Anthropic wrapper
from browser_use import ChatAnthropicBedrock
llm = ChatAnthropicBedrock(model="us.anthropic.claude-sonnet-4-20250514-v1:0", aws_region="us-east-1")
```

**Env:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`

Supports profiles, IAM roles, SSO via standard AWS credential chain.

## Groq

```python
from browser_use import ChatGroq
llm = ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct")
```

**Env:** `GROQ_API_KEY`

## OCI (Oracle)

```python
from browser_use import ChatOCIRaw
llm = ChatOCIRaw(
    model="meta.llama-3.1-70b-instruct",
    service_endpoint="https://inference.generativeai.us-chicago-1.oci.oraclecloud.com",
    compartment_id="your-compartment-id",
)
```

Requires `~/.oci/config` setup. Auth types: `API_KEY`, `INSTANCE_PRINCIPAL`, `RESOURCE_PRINCIPAL`.

## Ollama (Local)

```python
from browser_use import ChatOllama
llm = ChatOllama(model="llama3", num_ctx=32000)
```

Requires `ollama serve` running locally. Use `num_ctx` for context window (default may be too small).

## Vercel AI Gateway

Proxy to multiple providers with automatic fallback:

```python
from browser_use import ChatVercel
llm = ChatVercel(
    model='anthropic/claude-sonnet-4',
    provider_options={
        'gateway': {
            'order': ['vertex', 'anthropic'],  # Fallback order
        }
    },
)
```

**Env:** `AI_GATEWAY_API_KEY` (or `VERCEL_OIDC_TOKEN` on Vercel)

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

### DeepSeek
```python
llm = ChatOpenAI(model="deepseek-chat", base_url="https://api.deepseek.com")
```
**Env:** `DEEPSEEK_API_KEY`

### Novita
```python
llm = ChatOpenAI(model="deepseek/deepseek-r1", base_url="https://api.novita.ai/v3/openai")
```
**Env:** `NOVITA_API_KEY`

### OpenRouter
```python
llm = ChatOpenAI(model="deepseek/deepseek-r1", base_url="https://openrouter.ai/api/v1")
```
**Env:** `OPENROUTER_API_KEY`

### Langchain
See example at [examples/models/langchain](https://github.com/browser-use/browser-use/tree/main/examples/models/langchain).
