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
