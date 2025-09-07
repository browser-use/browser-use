# Browser Use Cloud Examples 🚀

Welcome to the Browser Use Cloud examples! This folder contains progressively complex examples to help you get started with the Browser Use Cloud API quickly and efficiently.

## 📋 Prerequisites

1. **API Key**: Get your API key from [cloud.browser-use.com/billing](https://cloud.browser-use.com/billing)
2. **Python Environment**: Python 3.11+ with dependencies
3. **Environment Variables**: Configure your API settings

### Quick Setup

```bash
# Create virtual environment and install dependencies (from project root)
uv venv --python 3.11
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync

# Set environment variables
export BROWSER_USE_API_KEY="your_api_key_here"
export BROWSER_USE_BASE_URL="https://api.browser-use.com/api/v1"  # Optional
export BROWSER_USE_TIMEOUT="30"  # Optional: request timeout in seconds

# Or use .env file (recommended)
cp examples/cloud/env.example .env
# Edit .env with your values

# Run examples from project root
python examples/cloud/01_basic_task.py
```

## 🎯 Examples Overview

### 🚀 Easy Cloud Setup Examples

- **[01_basic_task.py](./01_basic_task.py)** - Your first cloud task (start here!)
- **[02_fast_mode_gemini.py](./02_fast_mode_gemini.py)** - ⚡ Ultra-fast mode with Gemini Flash & Fireship humor
- **[03_structured_output.py](./03_structured_output.py)** - Get structured JSON responses
- **[04_proxy_usage.py](./04_proxy_usage.py)** - 🌍 Proxy for geo-restrictions & captcha solving
- **[05_search_api.py](./05_search_api.py)** - 🔍 Search API for content extraction (BETA)

## 💰 Cost Optimization Tips

1. **Use Gemini Flash** for fastest/cheapest execution ($0.01/step)
2. **Disable proxy** when not needed for captcha solving
3. **Disable element highlighting** for better performance
4. **Set max_agent_steps** to prevent runaway costs
5. **Use structured output** to reduce parsing overhead
6. **Add timeouts and retries** for reliability in production
7. **Use domain restrictions** when working with secrets

## 🎨 Fast Mode Configuration

For maximum speed and cost efficiency:

```python
{
    "llm_model": "gemini-2.5-flash",
    "use_proxy": False,
    "highlight_elements": False,
    "use_adblock": True,
    "max_agent_steps": 50
}
```

## 🔐 Security & Advanced Features

### Using Proxy
```python
{
    "use_proxy": True,
    "proxy_country_code": "us",  # 'us', 'fr', 'it', 'jp', 'au', 'de', 'fi', 'ca'
}
```

### Passing Secrets Securely
```python
{
    "secrets": {
        "username": "your_username",
        "password": "your_password",
        "api_key": "your_api_key"
    },
    "allowed_domains": ["*.yoursite.com"]  # Recommended with secrets
}
```

## 🔍 Search API (BETA)

The Search API extracts content by actually browsing websites (not cached results):

### Simple Search (Multi-site)
```python
# Cost: 1¢ × depth × websites
{
    "query": "latest AI news",
    "max_websites": 5,
    "depth": 2
}
```

### URL Search (Single site)
```python
# Cost: 1¢ × depth  
{
    "url": "https://example.com",
    "query": "pricing information",
    "depth": 3
}
```

## 🔗 Quick Links

- [Cloud API Documentation](https://docs.browser-use.com/cloud)
- [API Reference](https://docs.browser-use.com/api-reference)
- [Pricing](https://cloud.browser-use.com/billing)
- [Discord Community](https://link.browser-use.com/discord)

## 🔧 Production Best Practices

- **Timeouts**: All examples include 30-second timeouts with retry logic
- **Error Handling**: Comprehensive error catching and status code validation
- **Security**: Use environment variables, domain restrictions with secrets
- **Reliability**: Built-in retries for network issues and rate limits
- **Automation**: CLI arguments instead of interactive prompts for CI/CD

## 🆘 Support

Need help?

- 📧 Email: support@browser-use.com
- 💬 Discord: [Join our community](https://link.browser-use.com/discord)
- 📖 Docs: <https://docs.browser-use.com>

---

**💡 Pro Tip**: Start with `01_basic_task.py` and work your way up. Each example builds on the previous ones!
