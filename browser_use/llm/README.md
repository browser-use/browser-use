# Browser Use LLMs

We officially support the following LLMs:

- OpenAI
- Anthropic
- Google
- Groq
- Ollama
- DeepSeek
- OrcaRouter

- Mistral

## Mistral specifics

Use `ChatMistral` with `MISTRAL_API_KEY` (and optional `MISTRAL_BASE_URL`). Structured outputs automatically strip unsupported JSON schema keywords (`minLength`, `maxLength`, `pattern`, `format`), and generation uses `max_tokens` plus the optional `safe_prompt` flag.

- Cerebras

## OrcaRouter authentication

OrcaRouter supports an existing API key and account login. Set `ORCAROUTER_API_KEY`, pass `api_key` to `ChatOrcaRouter`, or run:

```bash
browser-use orcarouter login
browser-use orcarouter status
```

PKCE login stores the resulting durable API key in Browser Use's existing local LLM configuration. Run `browser-use orcarouter logout` to remove only that stored PKCE credential. An explicit `api_key` takes priority over the environment variable, which takes priority over the PKCE credential.


## Migrating from LangChain

Because of how we implemented the LLMs, we can technically support anything. If you want to use a LangChain model, you can use the `ChatLangchain` (NOT OFFICIALLY SUPPORTED) class.

You can find all the details in the [LangChain example](/examples/models/langchain/example.py). We suggest you grab that code and use it as a reference.
