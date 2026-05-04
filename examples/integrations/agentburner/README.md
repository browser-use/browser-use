# Agent Burner Integration

Disposable email for browser-use agents. No API key, no signup.

## Setup

```bash
pip install browser-use httpx
```

## Usage

```python
# Copy email_tools.py into your project, or run from the repo root
from email_tools import EmailTools

tools = EmailTools()
agent = Agent(task='...', tools=tools, llm=llm, browser=browser)
await agent.run()
```

## Tools

| Tool | Maps to | Description |
|------|---------|-------------|
| `create_inbox` | `POST /inbox` | Create a disposable inbox, returns the email address |
| `list_emails` | `GET /inbox/:key` | List received emails (id, from, subject) |
| `get_email` | `GET /inbox/:key/:id` | Get full email (body, html, urls[]) |
| `delete_inbox` | `DELETE /inbox/:key` | Delete inbox (optional — auto-expires in 1h) |

The tools mirror the API 1:1. No abstractions, no magic. The agent decides what to do with the data.

## vs AgentMail

| | Agent Burner | AgentMail |
|---|---|---|
| Auth | None | API key |
| Dependencies | `httpx` | `agentmail` SDK |
| Inbox lifespan | 1 hour | Permanent |
| Send email | No | Yes |
| Cost | Free | Per-mailbox |

Agent Burner for throwaway inboxes. AgentMail for persistent email identity.

## API docs

[agentburner.com/skill.md](https://agentburner.com/skill.md)
