# Performance Examples

This directory contains examples focused on **speed optimization** for browser-use automation. These examples demonstrate various techniques to maximize execution speed while maintaining reliability.

## Examples

### 1. Flash Mode (`speed_flash_mode.py`)
**Focus: Ultra-fast execution with minimal overhead**

- ⚡ **Flash mode enabled** for reduced system prompt complexity
- 🚀 **Headless browser** for faster rendering
- ⏱️ **Reduced wait times** (0.1s between actions)
- 🎯 **Optimized Chrome flags** for maximum speed
- 📱 **Smaller viewport** for faster processing

**Use Case**: Simple tasks requiring maximum speed
**Expected Performance**: Sub-30 second execution for basic automation

### 2. Groq Llama (`speed_groq_llama.py`)
**Focus: Ultra-fast LLM inference with Groq**

- 🦙 **Llama-4 Maverick** on Groq infrastructure
- ⚡ **<200ms inference time** per LLM call
- 🌡️ **Zero temperature** for deterministic responses
- 🚀 **Aggressive browser optimizations**
- 💨 **Minimal wait times** (0.05s between actions)

**Use Case**: Speed-critical automation with fast decision making
**Requirements**: `GROQ_API_KEY` environment variable

### 3. Headless Optimized (`speed_headless_optimized.py`)
**Focus: Maximum speed with headless configuration**

- 👤 **Headless mode** with zero GUI overhead
- ⏱️ **Zero wait times** between actions
- 🚫 **Disabled images** and unnecessary features
- 🧠 **Optimized memory usage**
- 🔧 **Performance-tuned Chrome flags**

**Use Case**: Production environments requiring fastest possible execution
**Target**: Sub-30 second execution for simple tasks

## Configuration Patterns

### Speed Optimization Techniques

1. **Browser Settings**:
   ```python
   browser_profile=BrowserProfile(
       headless=True,                    # No GUI overhead
       wait_between_actions=0.0,         # No delays
       viewport={'width': 800, 'height': 600},  # Smaller viewport
       user_data_dir=None,               # Ephemeral profile
   )
   ```

2. **Agent Settings**:
   ```python
   agent = Agent(
       flash_mode=True,                  # Minimal system prompt
       use_thinking=False,               # Skip thinking mode
       max_actions_per_step=10,          # Batch actions
       step_timeout=30,                  # Short timeouts
   )
   ```

3. **Chrome Flags for Speed**:
   ```python
   args=[
       '--disable-images',               # Skip image loading
       '--disable-extensions',           # No extensions
       '--disable-sync',                 # No Chrome sync
       '--aggressive-cache-discard',     # Memory optimization
   ]
   ```

## Performance Metrics

| Example | Target Time | LLM Provider | Browser Mode | Wait Time |
|---------|-------------|--------------|--------------|-----------|
| Flash Mode | <30s | OpenAI GPT-4.1-mini | Headless | 0.1s |
| Groq Llama | <20s | Groq Llama-4 | Headless | 0.05s |
| Headless Optimized | <30s | OpenAI GPT-4.1-mini | Headless | 0.0s |

## Usage Tips

1. **Choose the right example**:
   - Flash Mode: General speed optimization
   - Groq Llama: When LLM inference is the bottleneck
   - Headless Optimized: Maximum speed in production

2. **Environment considerations**:
   - Ensure stable network connection
   - Use SSD storage for faster browser startup
   - Adequate RAM for multiple browser instances

3. **Trade-offs**:
   - Speed vs. reliability (fewer retries)
   - Speed vs. accuracy (lower vision detail)
   - Speed vs. debugging (headless mode)

## Getting Started

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Set up environment variables:
   ```bash
   # For OpenAI examples
   export OPENAI_API_KEY="your-api-key"
   
   # For Groq example
   export GROQ_API_KEY="your-groq-api-key"
   ```

3. Run an example:
   ```bash
   python examples/performance/speed_flash_mode.py
   ```

## Best Practices

- **Profile your automation** to identify bottlenecks
- **Use headless mode** in production environments
- **Minimize wait times** but ensure stability
- **Choose fast LLM models** for speed-critical tasks
- **Disable unnecessary browser features**
- **Monitor performance metrics** and optimize iteratively