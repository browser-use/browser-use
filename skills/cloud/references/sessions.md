# Sessions, Profiles & Authentication

## Table of Contents
- [Sessions](#sessions)
- [Profiles](#profiles)
- [Profile Sync](#profile-sync)
- [Authentication Strategies](#authentication-strategies)
- [1Password Integration](#1password-integration)
- [Social Media Automation](#social-media-automation)

---

## Sessions

Sessions are stateful browser environments. Each has one browser, runs agents sequentially.

### Auto-Created Sessions

Most tasks auto-create a session:
```python
result = await client.run("Find top HN post")  # Session auto-created
```

### Manual Sessions

For multi-step workflows or custom config:

```python
session = await client.sessions.create(
    profile_id="uuid",           # Persistent profile
    proxy_country_code="us",     # Residential proxy
    start_url="https://example.com",
)

# Run multiple tasks in same session
await client.run("First task", session_id=session.id)
await client.run("Follow-up task", session_id=session.id)

# Get live URL for monitoring
session_info = await client.sessions.get(session.id)
print(session_info.live_url)  # Watch agent in real-time

await client.sessions.stop(session.id)
```

### Live View & Sharing

Every session has a `liveUrl` for real-time monitoring. Create public share links:

```python
share = await client.sessions.create_share(session.id)
print(share.share_url)  # Anyone with link can view
```

## Profiles

Profiles persist browser state (cookies, localStorage, passwords) across sessions.

### CRUD

```python
# Create
profile = await client.profiles.create(name="my-profile")

# List
profiles = await client.profiles.list()

# Update
await client.profiles.update(profile.id, name="new-name")

# Delete
await client.profiles.delete(profile.id)
```

### Usage Patterns

- **Per-user**: One profile per end-user for personalized sessions
- **Per-site**: One profile per website (e.g., "github-profile", "gmail-profile")
- **Warm-up**: Login once, reuse across all future tasks

**Important:**
- Profile state saved when session ends — always call `sessions.stop()`
- Concurrent sessions read from snapshot at start — won't see each other's changes
- Refresh profiles older than 7 days

## Profile Sync

Upload local browser cookies to cloud profiles:

```bash
export BROWSER_USE_API_KEY=your_key
curl -fsSL https://browser-use.com/profile.sh | sh
```

Opens a browser where you log into sites. Returns a `profile_id` to use in tasks.

## Authentication Strategies

### 1. Profile Sync (Easiest)

Log in locally, sync cookies to cloud:
```bash
curl -fsSL https://browser-use.com/profile.sh | sh
```

### 2. Secrets (Domain-Scoped)

Pass credentials as key-value pairs, scoped to domains:

```python
result = await client.run(
    task="Login and check dashboard",
    secrets={
        "username": "my-user",
        "password": "my-pass",
    },
    allowed_domains=["*.example.com"],
)
```

Supports wildcards and multiple domains for OAuth/SSO flows.

### 3. Profiles + Secrets (Combined)

Use profile for cookies (skip login flow) with secrets as fallback:

```python
session = await client.sessions.create(profile_id="uuid")
await client.run(
    task="Check dashboard",
    session_id=session.id,
    secrets={"password": "backup-pass"},
)
await client.sessions.stop(session.id)  # Save profile state
```

## 1Password Integration

Auto-fill passwords and TOTP/2FA codes from 1Password vault:

### Setup
1. Create a dedicated vault in 1Password
2. Create a service account with vault access
3. Connect to Browser Use Cloud (settings page)
4. Use `op_vault_id` param in tasks

```python
result = await client.run(
    task="Login to GitHub",
    op_vault_id="vault-uuid",
    allowed_domains=["*.github.com"],
)
```

Credentials never appear in logs — filled programmatically by 1Password.

## Social Media Automation

Anti-bot detection requires consistent fingerprint + IP + cookies:

### Setup
1. Create blank profile
2. Open session with profile + proxy → manually log in via `liveUrl`
3. Stop session (saves profile state)

### Ongoing
- Always use same profile + same proxy country
- Refresh profiles older than 7 days

```python
session = await client.sessions.create(
    profile_id="social-profile-uuid",
    proxy_country_code="us",  # Always same country
)
await client.run("Post update to Twitter", session_id=session.id)
await client.sessions.stop(session.id)
```

## Cloud recording behavior

The Cloud recorder uses a video canvas separate from the browser viewport. The driver defaults to 1920×1080 and scales frames to fit while preserving aspect ratio, adding black bars when needed. Setting the browser viewport does not by itself set the recording resolution.

The recorder selects an initial page and follows explicit CDP tab activation (`Target.activateTarget` or `Page.bringToFront`). Sending automation commands to another tab does not necessarily make that tab the recording target. Activate the tab you want captured; do not infer recording focus from the tab your code last addressed.

A downloadable recording depends on successful video encoding and upload finalization. If it remains unavailable after the session ends, report the session ID and UTC stop time so support can distinguish processing from encoder/upload failure or an interrupted session. Repeatedly polling for a file cannot recover a recording that was never finalized.

## CAPTCHA and anti-bot troubleshooting

A site block, a solver failure, and an expired browser session need different recovery actions. The CAPTCHA vendor or an HTTP 403 alone does not identify the cause.

- **Explicit IP/reputation block:** collect the actual block reason. If the driver reports an IP hard block, retrying the same challenge on the same exit is unlikely to help. Test a different exit separately; keep the profile and proxy location consistent during a login transaction.
- **Challenge integration/readiness failure:** invalid solver input, a missing checkbox, an iframe without layout, or a challenge outside the viewport require investigating page state or the solver integration. A waiting room is a queue, not a CAPTCHA to solve.
- **Cancellation or timeout:** correlate the solver timestamp with navigation, tab closure, browser disconnect, and task cancellation before changing proxies. A cancelled attempt does not prove that the challenge was unsolvable.
- **Possible fingerprint mismatch:** capture the browser version, profile, viewport, timezone, and fingerprint-selection warning. A warning or a failed challenge alone does not prove a fingerprint leak; compare one variable at a time.

After solver success, verify that the challenge disappeared and the intended page or form submission actually succeeded. Avoid unlimited retries: use a bounded retry/cost policy and surface the failure reason to the caller.

For support, include the domain, UTC timestamp, run/session ID, SDK/browser version, CAPTCHA vendor, relevant error, profile/proxy configuration, and terminal task result. Include a screenshot with sensitive information removed; do not include credentials, cookies, or API keys.
