# Getting Started Examples

This directory contains progressive examples to help you get started with Browser Use. Each example builds upon the previous one, introducing new concepts and capabilities.

## Examples Overview

### 1. Basic Search (`01_basic_search.py`)
**What you'll learn:** Basic agent setup and simple web search
- Initialize an agent with OpenAI GPT-4.1-mini
- Perform a Google search
- Extract search results

### 2. Form Filling (`02_form_filling.py`)
**What you'll learn:** Interacting with web forms
- Navigate to form pages
- Fill input fields with data
- Submit forms and handle responses
- Basic form interactions

### 3. Data Extraction (`03_data_extraction.py`)
**What you'll learn:** Extracting structured data from websites
- Navigate to data-rich pages
- Use structured data extraction
- Save extracted data to files
- Handle complex page content

### 4. Multi-Step Tasks (`04_multi_step_task.py`)
**What you'll learn:** Complex workflows with multiple steps
- Plan and execute multi-step tasks
- Use the file system for progress tracking
- Handle task coordination
- Manage complex workflows

### 5. Speed-Optimized (`05_speed_optimized.py`) ⚡
**What you'll learn:** Maximum performance configuration
- **Flash Mode**: Disables thinking/evaluation for speed
- **Fast LLM**: Llama 4 on Groq for ultra-fast inference
- **Reduced Wait Times**: 0.1s between actions (vs 0.5s default)
- **Headless Mode**: Optional for maximum rendering speed
- **Concise System Prompt**: Encourages efficient responses
- **Multi-Actions**: Up to 10 actions per step

## Running the Examples

1. Set up your environment:
```bash
# Install dependencies
uv pip install browser-use

# Install browser
uvx playwright install chromium --with-deps
```

2. Set up your API keys in `.env`:
```bash
# For examples 1-4
OPENAI_API_KEY=your_openai_api_key

# For speed-optimized example
GROQ_API_KEY=your_groq_api_key
```

3. Run any example:
```bash
python examples/getting_started/01_basic_search.py
python examples/getting_started/05_speed_optimized.py
```

## Speed Optimization Guide

The speed-optimized example (`05_speed_optimized.py`) demonstrates how to achieve **3-5x faster execution** through:

### 🚀 Flash Mode
Disables thinking and evaluation steps for immediate action execution.

### ⚡ Fast LLM Integration
Uses Llama 4 on Groq's infrastructure for ultra-fast inference (sub-second response times).

### ⏱️ Optimized Wait Times
- `wait_between_actions`: 0.1s (vs 0.5s default)
- `minimum_wait_page_load_time`: 0.1s (vs 0.25s default)
- `wait_for_network_idle_page_load_time`: 0.25s (vs 0.5s default)
- `maximum_wait_page_load_time`: 3.0s (vs 5.0s default)

### 🎯 Efficiency Settings
- `max_actions_per_step`: 10 (execute multiple actions per step)
- `vision_detail_level`: 'low' (faster image processing)
- `max_failures`: 2 (fewer retry attempts)
- `retry_delay`: 5s (faster retry cycles)

### 🖥️ Headless Mode
Set `headless=True` for maximum rendering speed (disabled by default for visibility).

### 📝 Concise System Prompt
Extended system prompt that instructs the model to:
- Be extremely concise and direct
- Skip unnecessary explanations
- Use multi-action sequences
- Prioritize efficiency over detailed reasoning

## Next Steps

After completing these examples, explore:
- [Custom Functions](/examples/custom-functions/) - Add your own browser actions
- [Use Cases](/examples/use-cases/) - Real-world automation scenarios
- [Model Integration](/examples/models/) - Different LLM providers
- [Browser Customization](/docs/customize/browser-settings) - Advanced browser configuration