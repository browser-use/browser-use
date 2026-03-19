# Agent Burner Integration

Disposable email for browser-use agents. No API key, no signup, no SDK.

## Setup

```bash
pip install browser-use httpx
```

That's it. No API key needed.

## How it works

Agent Burner provides throwaway email inboxes via REST API. The agent creates an inbox, uses the address for signup, polls for verification emails, and extracts OTP codes or verification links automatically.

```python
from examples.integrations.agentburner.email_tools import EmailTools

tools = EmailTools()
agent = Agent(task="Sign up for ...", tools=tools, llm=llm, browser=browser)
await agent.run()
```

## Available tools

| Tool | Description |
|------|-------------|
| `create_email` | Create a disposable email address |
| `get_email_address` | Get the current email address (creates one if needed) |
| `get_verification_email` | Poll for and return the latest email with extracted OTP codes and URLs |
| `get_verification_link` | Get just the first URL from the latest email |
| `delete_inbox` | Delete the inbox (optional — auto-expires in 1 hour) |

## Comparison with AgentMail integration

| | Agent Burner | AgentMail |
|---|---|---|
| API key required | No | Yes |
| pip install | `httpx` (standard HTTP) | `agentmail` (custom SDK) |
| Email creation | `POST /inbox` | SDK call + API key |
| URL extraction | Built in (`urls[]`) | Manual parsing |
| Inbox lifespan | 1 hour (auto-expires) | Permanent |
| Send email | No | Yes |
| Cost | Free | Per-mailbox |

Use Agent Burner for throwaway signups and verification flows. Use AgentMail if you need persistent inboxes or outbound email.

## API docs

Full reference: [agentburner.com/skill.md](https://agentburner.com/skill.md)
