# NVIDIA ChatNvidia Integration (Brev-Based)

OpenAI-compatible integration for NVIDIA NIM models via **Brev.dev**.

## Why Brev?

✅ **Access to powerful Nemotron models** not available on public API:
- `nvidia/llama-3.1-nemotron-70b-instruct` - 70B instruction model
- `nvidia/llama-3.3-nemotron-super-49b-v1` - 49B super model
- `nvidia/llama-3.1-nemotron-nano-8b-v1` - Efficient 8B model

✅ **Better performance** - Dedicated GPU instances (no rate limits)
✅ **Flexible deployment** - Choose your GPU configuration
✅ **OpenAI-compatible** - Works seamlessly with this integration

## Setup

### 1. Deploy a Model on Brev

1. Go to [brev.dev](https://brev.dev) and sign in
2. Navigate to **Deployments**
3. Click **Create Deployment**
4. Choose a model (e.g., `nvidia/llama-3.1-nemotron-70b-instruct`)
5. Select GPU configuration
6. Copy your **deployment ID** (format: `nvcf:nvidia/model-name:dep-XXXXX`)
7. Copy your **Brev API key** (format: `brev_api_-XXXXX`)

### 2. Configure Environment

Create a `.env` file in this directory:

```bash
NVIDIA_API_KEY=brev_api_-XXXXX  # Your Brev API key
```

### 3. Update Model ID

When initializing ChatNvidia, use your deployment ID:

```python
from browser_use.llm import ChatNvidia

llm = ChatNvidia(
    api_key="brev_api_-XXXXX",
    model="nvcf:nvidia/llama-3.1-nemotron-70b-instruct:dep-XXXXX",  # Your deployment
)
```

## Usage Examples

### Basic Chat

```python
import asyncio
from browser_use.llm import ChatNvidia
from browser_use.llm.messages import UserMessage

async def main():
    llm = ChatNvidia(
        api_key="brev_api_-XXXXX",
        model="nvcf:nvidia/llama-3.1-nemotron-70b-instruct:dep-XXXXX",
        temperature=0.2,
        max_tokens=1024,
    )

    response = await llm.ainvoke(
        messages=[UserMessage(content="Hello!")]
    )
    print(response.completion)

asyncio.run(main())
```

### Browser Automation

```python
import asyncio
from browser_use import Agent
from browser_use.llm import ChatNvidia

async def main():
    llm = ChatNvidia(
        api_key="brev_api_-XXXXX",
        model="nvcf:nvidia/llama-3.1-nemotron-70b-instruct:dep-XXXXX",
        temperature=0.7,
        max_tokens=1024,
    )

    agent = Agent(
        task="Find the number of GitHub stars for browser-use",
        llm=llm,
    )

    result = await agent.run()
    print(result)

asyncio.run(main())
```

### Using Default Settings

The integration has sensible defaults for Brev. Just update the model to your deployment:

```python
# Uses default base_url: https://api.brev.dev/v1
llm = ChatNvidia(
    api_key="brev_api_-XXXXX",
    model="your-deployment-id",  # Update this
)
```

## Available Models on Brev

### Text-Only Models

These are available for deployment on Brev:

1. **`nvidia/llama-3.1-nemotron-70b-instruct`** ⭐ **RECOMMENDED**
   - GPUs: 2xH100, 4xH100, 8xH100, 4xA100, 8xA100
   - Best balance of performance and capability

2. **`nvidia/llama-3.3-nemotron-super-49b-v1`**
   - GPUs: 1xH200, 2xH200, 4xH200, 1xH100, 2xH100, 4xH100, 8xH100
   - High accuracy model

3. **`nvidia/llama-3.1-nemotron-nano-8b-v1`**
   - GPUs: 1xH200, 2xH200, 1xH100, 2xH100, 1xA100, 2xA100
   - Efficient and fast

4. **`meta/llama-3.3-70b-instruct`**
   - GPUs: 4xH100, 8xH100, 4xA100, 8xA100

5. **`meta/llama-3.1-405b-instruct`**
   - GPUs: 8xH100, 16xH100, 16xA100
   - Most capable (but expensive)

6. **`deepseek/deepseek-r1-distill-qwen-14b`**
   - GPUs: 1xH200, 1xH100, 1xL40S
   - Reasoning-focused

**Note:** None of these are multimodal (vision). For vision tasks, you'd need to use NVIDIA's public API with `nvidia/nemotron-nano-12b-v2-vl` instead.

## Configuration

### Required Parameters
- `api_key`: Your Brev API key
- `model`: Your Brev deployment ID (format: `nvcf:vendor/model:dep-XXXXX`)

### Optional Parameters
- `base_url`: API endpoint (default: `https://api.brev.dev/v1`)
- `temperature`: Sampling temperature (0.0-2.0)
- `max_tokens`: Maximum tokens to generate
- `top_p`: Nucleus sampling parameter
- `seed`: Random seed for reproducibility
- `frequency_penalty`: Penalize frequent tokens
- `presence_penalty`: Penalize present tokens

## Switching Between Brev and NVIDIA Public API

If you want to use NVIDIA's public API instead of Brev:

```python
# Brev (default)
llm = ChatNvidia(
    api_key="brev_api_-XXXXX",
    base_url="https://api.brev.dev/v1",
    model="nvcf:nvidia/llama-3.1-nemotron-70b-instruct:dep-XXXXX",
)

# NVIDIA Public API (for multimodal)
llm = ChatNvidia(
    api_key="nvapi-XXXXX",
    base_url="https://integrate.api.nvidia.com/v1",
    model="nvidia/nemotron-nano-12b-v2-vl",  # Vision model
)
```

## Getting Your Deployment ID

Your Brev deployment ID is in this format:
```
nvcf:nvidia/llama-3.1-nemotron-70b-instruct:dep-35fbb28ZU7i7wmP1q1cSvS7JA6U
     └─────────┬────────────────────────┘ └──────────┬─────────────────────┘
               model name                           deployment ID
```

To get it:
1. Go to your Brev dashboard
2. Click on your deployment
3. Look for the "Model ID" or use the code snippet provided
4. Copy the full `nvcf:...` string

## Test Files

Run these to test the integration:
- `simple_test.py` - Quick API test
- `test_nemotron_nano_vl.py` - Specific model tests
- `test_nvidia.py` - Full browser automation

**Note:** Make sure your deployment is active on Brev before running tests!
