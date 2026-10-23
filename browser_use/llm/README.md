# Browser Use LLMs

We officially support the following LLMs:

- OpenAI
- Anthropic
- Google
- Groq
- Ollama
- DeepSeek
- Mistral
- Cerebras
- Browser Use

## Browser Use specifics

Use `ChatBrowserUse` with `BROWSER_USE_API_KEY` (and optional `BROWSER_USE_LLM_URL`, which defaults to `https://llm.api.browser-use.com`). Pass either a `bu-*` alias (`bu-latest`, `bu-1-0`, `bu-2-0`, `bu-2-0-mini-preview`, `bu-qa-1`) or a provider-prefixed id the gateway resolves, such as `anthropic/claude-sonnet-4-6`. `bu-latest` resolves to the current default rather than to a preview model.

## Mistral specifics

Use `ChatMistral` with `MISTRAL_API_KEY` (and optional `MISTRAL_BASE_URL`). Structured outputs automatically strip unsupported JSON schema keywords (`minLength`, `maxLength`, `pattern`, `format`), and generation uses `max_tokens` plus the optional `safe_prompt` flag.


## Migrating from LangChain

Because of how we implemented the LLMs, we can technically support anything. If you want to use a LangChain model, you can use the `ChatLangchain` (NOT OFFICIALLY SUPPORTED) class.

You can find all the details in the [LangChain example](/examples/models/langchain/example.py). We suggest you grab that code and use it as a reference.
