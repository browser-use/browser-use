# Mobilebox

[Mobilebox](https://mobilebox.dev) runs Android phones in the cloud behind a REST API. This example gives one Browser Use agent a phone next to its browser through two custom actions:

- `phone_screen` reads the screen as numbered elements with text and coordinates.
- `phone_act` runs a JSON list of actions (`open_app`, `tap`, `type`, `swipe`, ...) and returns the new screen.

The script creates a phone, asks the agent to read the Android version in Settings > About phone and then find that version's release date on Wikipedia, and deletes the phone in `finally`, also when the run fails.

## Setup

```bash
uv sync
export MOBILESANDBOX_API_KEY=...  # https://mobilebox.dev/dashboard
export OPENAI_API_KEY=...
```

`MODEL` picks another OpenAI model (default `gpt-5.4-mini`). Mobilebox bills per ready phone-minute.

## Run

From the repository root:

```bash
uv run examples/integrations/mobilebox/phone_agent.py
```

Actions and errors are documented at https://mobilebox.dev/docs/reference.
