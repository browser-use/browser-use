# Integration examples

This directory is for examples that show Browser Use working with external products, APIs, and services.

## Shipped integrations

- [Anthropic Browser Use](anthropic/README.md) - Run the Anthropic SDK tool runner with Browser Use and Bash.

## Where to put integration contributions

- Use `examples/integrations/<provider>/` for small, runnable examples that demonstrate Browser Use with a specific third-party service.
- Use `examples/custom-functions/` for provider-agnostic custom tool patterns.
- Use `browser_use/integrations/<provider>/` only when the integration is shipped as part of the Browser Use package and has tests.
- Keep product-specific workflows, full applications, or large third-party projects in their own repositories.
- Add third-party projects to the community list below instead of vendoring their code into this repository.

## Example checklist

- Use `uv` in setup instructions.
- Keep the example focused on the Browser Use integration point.
- Document required environment variables, OAuth scopes, and local services.
- Do not commit secrets, tokens, generated credentials, or private account data.
- Prefer `ChatBrowserUse()` unless the example is specifically about another model.
- Include the command that runs the example from the repository root.

## Community integrations

External projects listed here are maintained outside this repository. A listing is a pointer for users, not a support guarantee from Browser Use maintainers.

Add entries in this format:

```markdown
- [Project name](https://github.com/org/project) - One sentence about what it integrates with. Maintained by @github-handle.
```

- [Agent Help Network](https://github.com/agent-help-network/agent-help-network/tree/main/examples/browser-use) - A custom tool the agent calls on a blocked page (403, login wall, CAPTCHA, 429, 5xx) that looks up what the host declares for agents and returns one next step: use the official path, ask the user, wait, or stop. It sends only the target hostname to agenthelpnetwork.com. Maintained by @agent-help-network.
