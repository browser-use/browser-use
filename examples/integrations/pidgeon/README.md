# Sign up with a verification code, using Pidgeon

The agent signs up on a website with an email address of its own, reads the verification code sent to it, and finishes the sign-up.

[Pidgeon](https://pidgeon.ai) gives the agent the address. `email_tools.py` adds two actions:

- `create_inbox` makes one address on `pidgeon.email` for the run. Asked again, it returns the same one.
- `wait_for_email` waits up to 30 seconds for the next email with a code or a verification link, and returns them already extracted. If nothing has come yet, it says so, and the model asks again.

The address stops taking mail after an hour, and the script deletes it when the run ends.

## Setup

```bash
uv pip install pidgeon
```

Environment variables:

- `PIDGEON_API_KEY`: a key from [pidgeon.ai/app/developers/keys](https://pidgeon.ai/app/developers/keys). It needs Admin access, because it creates the address.
- `BROWSER_USE_API_KEY`: for `ChatBrowserUse()`.

## Run

From the repository root:

```bash
uv run examples/integrations/pidgeon/signup.py https://example.com/signup
```

Use it only on a site whose terms allow automated sign-ups. The agent stops at a CAPTCHA instead of trying to solve it.
