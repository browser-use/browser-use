# Browser Use LLMs

We officially support the following LLMs:

- OpenAI
- Anthropic
- Google
- Groq
- Ollama
- DeepSeek

## Using Ollama with browser-use

When using Ollama with browser-use version 0.4.2+, use our special wrapper class `BrowserUseOllama` instead of `ChatOllama` directly:

```python
from browser_use.llm.ollama import BrowserUseOllama

agent = Agent(
    task="Your task here",
    llm=BrowserUseOllama(  # Use this instead of ChatOllama
        model='qwen3:14b',
        num_ctx=32000,
    ),
    browser=browser
)
```

See the [Ollama README](/workspaces/browser-use/browser_use/llm/ollama/README.md) for more details.

## Migrating from LangChain

Because of how we implemented the LLMs, we can technically support anything. If you want to use a LangChain model, you can use the `ChatLangchain` (NOT OFFICIALLY SUPPORTED) class.

You can find all the details in the [LangChain example](examples/models/langchain/example.py). We suggest you grab that code and use it as a reference.
