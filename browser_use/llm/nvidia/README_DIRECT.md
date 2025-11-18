# ChatNvidiaDirect - Direct NVIDIA API Integration

This is an alternative NVIDIA integration using the direct NVIDIA API instead of Brev.

## Key Differences from Brev Integration

| Feature | ChatNvidia (Brev) | ChatNvidiaDirect |
|---------|-------------------|------------------|
| **Base URL** | `https://api.brev.dev/v1` | `https://integrate.api.nvidia.com/v1` |
| **Streaming** | Required (`stream=True`) | Optional |
| **Multimodal** | ❌ No (text only) | ✅ Yes (vision models supported) |
| **Content Format** | String only | String or array (with images) |
| **Function Calling** | ❌ No | Depends on model |
| **Usage Tracking** | ❌ No | ✅ Yes |

## When to Use Direct API

Use **ChatNvidiaDirect** when you need:
- **Vision/multimodal capabilities** - Send images to vision models
- **Usage tracking** - Get token counts
- **Standard OpenAI format** - Full multi-part content support
- **Access to all NVIDIA models** - Not limited to Brev deployments

Use **ChatNvidia (Brev)** when you need:
- **Custom deployments** - Use your own Brev deployments
- **Lower latency** - If Brev is closer to your infrastructure

## Setup

### 1. Get NVIDIA API Key

Visit https://build.nvidia.com/explore/discover and:
1. Sign in with your NVIDIA account
2. Select a model you want to use
3. Click "Get API Key"
4. Copy your API key

### 2. Configure Environment

Add to `browser_use/llm/nvidia/.env`:

```bash
NVIDIA_DIRECT_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 3. Usage Example

```python
from browser_use import Agent
from browser_use.llm.nvidia.chat_direct import ChatNvidiaDirect

# Text-only model
llm = ChatNvidiaDirect(
    api_key="nvapi-xxxxx",
    model="nvidia/llama-3.1-nemotron-70b-instruct",
    temperature=0.7,
    max_tokens=1024,
)

# Vision model (with image support)
llm_vision = ChatNvidiaDirect(
    api_key="nvapi-xxxxx",
    model="microsoft/phi-3-vision-128k-instruct",
    temperature=0.5,
)

agent = Agent(task="Your task here", llm=llm)
result = await agent.run()
```

## Available Models

Common models on NVIDIA Direct API:
- `nvidia/llama-3.1-nemotron-70b-instruct` - Strong general model
- `meta/llama-3.1-70b-instruct` - Meta's Llama 3.1
- `microsoft/phi-3-vision-128k-instruct` - Vision model
- `google/deplot` - Chart/plot understanding
- Many more at https://build.nvidia.com/explore/discover

List available models:
```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="nvapi-xxxxx",
)

models = await client.models.list()
for model in models.data:
    print(model.id)
```

## Testing

Run the test:
```bash
uv run python browser_use/llm/nvidia/test_nvidia_direct.py
```

## Multimodal Support

The direct API supports sending images to vision models:

```python
from browser_use.llm.messages import UserMessage, ContentPartTextParam, ContentPartImageParam

# The agent will automatically include screenshots when using vision models
# Images are sent as data URLs in the standard OpenAI format:
# [
#     {"type": "text", "text": "What's in this image?"},
#     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
# ]
```

## API Reference

### ChatNvidiaDirect

**Parameters:**
- `model` (str): NVIDIA model identifier
- `api_key` (str): Your NVIDIA API key from build.nvidia.com
- `base_url` (str): Default is `https://integrate.api.nvidia.com/v1`
- `temperature` (float): Sampling temperature (0.0 to 1.0)
- `max_tokens` (int): Maximum tokens to generate
- `top_p` (float): Nucleus sampling threshold
- `seed` (int): Random seed for reproducibility
- `frequency_penalty` (float): Frequency penalty
- `presence_penalty` (float): Presence penalty
- `timeout` (float): Request timeout in seconds

## Limitations

- **Rate limits**: NVIDIA's free tier has rate limits (check your account)
- **Model availability**: Not all models support all features (e.g., some don't support vision)
- **Function calling**: Limited to models that support it (check model documentation)

## Troubleshooting

### "Model not found" error
- Verify the model name is correct
- Check model availability at https://build.nvidia.com/explore/discover
- Some models require special access

### "Unauthorized" error
- Verify your API key is correct
- Check if your key has expired
- Ensure you're using the right environment variable

### Vision features not working
- Verify you're using a vision-capable model
- Check that images are being sent in the correct format
- Some models have image size limitations
