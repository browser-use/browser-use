# Guide: Building a Chat Interface

Build a conversational UI where users chat with a Browser Use agent and watch it work in real-time.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [SDK Setup](#sdk-setup)
- [Creating a Session](#creating-a-session)
- [Polling Messages](#polling-messages)
- [Sending Follow-ups](#sending-follow-ups)
- [Stopping Tasks](#stopping-tasks)
- [Live Browser View](#live-browser-view)
- [Python Equivalent](#python-equivalent)
- [SDK Methods Summary](#sdk-methods-summary)

---

## Prerequisites

- You have a web app (or are building one) — Next.js/React shown, but the SDK calls work from any backend
- You're using the **Cloud API** because you need `liveUrl` for real-time browser streaming
- `BROWSER_USE_API_KEY` from https://cloud.browser-use.com/new-api-key

## Architecture

Two pages:
1. **Home** — user types a task → app creates an idle session → navigates to session page → fires task
2. **Session** — polls for messages, shows live browser in iframe, lets user send follow-ups

All SDK calls live in a single API file. The key pattern: create session first (instant), dispatch task second (fire-and-forget), navigate immediately so the user sees the browser while the task starts.

## SDK Setup

Uses both SDK versions — v3 for sessions/messages, v2 for profiles (not on v3 yet).

```typescript
// api.ts
import { BrowserUse as BrowserUseV3 } from "browser-use-sdk/v3";
import { BrowserUse as BrowserUseV2 } from "browser-use-sdk";

const apiKey = process.env.NEXT_PUBLIC_BROWSER_USE_API_KEY ?? "";
const v3 = new BrowserUseV3({ apiKey });
const v2 = new BrowserUseV2({ apiKey });
```

> **Warning:** `NEXT_PUBLIC_` exposes the key to the browser. In production, move SDK calls to server actions or API routes.

## Creating a Session

Two functions: one creates an idle session, another dispatches a task into it.

```typescript
// api.ts
export async function createSession(opts: {
  model: string;
  profileId?: string;
  proxyCountryCode?: string;
}) {
  return v3.sessions.create({
    model: opts.model as "bu-mini" | "bu-max",
    keepAlive: true,  // Keep session open for follow-ups
    ...(opts.profileId && { profileId: opts.profileId }),
    ...(opts.proxyCountryCode && { proxyCountryCode: opts.proxyCountryCode }),
  });
}

export async function sendTask(sessionId: string, task: string) {
  return v3.sessions.create({ sessionId, task, keepAlive: true });
}
```

### Page flow — fire-and-forget for instant navigation

```typescript
// page.tsx
async function handleSend(message: string) {
  // 1. Create idle session
  const session = await createSession({ model });

  // 2. Navigate immediately (user sees browser while task dispatches)
  router.push(`/session/${session.id}`);

  // 3. Fire-and-forget the task
  sendTask(session.id, message).catch(console.error);
}
```

### Populate dropdowns

```typescript
export async function listProfiles() {
  return v2.profiles.list({ pageSize: 100 });
}

export async function listWorkspaces() {
  return v3.workspaces.list({ pageSize: 100 });
}
```

## Polling Messages

Poll session status and messages at 1s intervals. Stop when terminal.

```typescript
// api.ts
export async function getSession(id: string) {
  return v3.sessions.get(id);
}

export async function getMessages(id: string, limit = 100) {
  return v3.sessions.messages(id, { limit });
}
```

### React Query polling

```typescript
// session-context.tsx
const TERMINAL = new Set(["stopped", "error", "timed_out"]);

// Poll session status every 1s
const { data: session } = useQuery({
  queryKey: ["session", sessionId],
  queryFn: () => api.getSession(sessionId),
  refetchInterval: (query) => {
    const s = query.state.data?.status;
    return s && TERMINAL.has(s) ? false : 1000;
  },
});

const isTerminal = !!session && TERMINAL.has(session.status);
const isActive = !!session && !isTerminal;

// Poll messages every 1s while active
const { data: rawResponse } = useQuery({
  queryKey: ["messages", sessionId],
  queryFn: () => api.getMessages(sessionId),
  refetchInterval: isActive ? 1000 : false,
});
```

## Sending Follow-ups

Reuse `sendTask` with optimistic updates so messages appear instantly:

```typescript
const sendMessage = useCallback(async (task: string) => {
  const tempMsg = {
    id: `opt-${Date.now()}`,
    role: "user",
    content: task,
    createdAt: new Date().toISOString(),
  };
  setOptimistic((prev) => [...prev, tempMsg]);

  try {
    await api.sendTask(sessionId, task);
  } catch (err) {
    setOptimistic((prev) => prev.filter((m) => m.id !== tempMsg.id));
  }
}, [sessionId]);
```

## Stopping Tasks

Stop the current task but keep the session alive for follow-ups:

```typescript
export async function stopTask(id: string) {
  await v3.sessions.stop(id, { strategy: "task" });
}
```

`strategy: "task"` stops only the running task. `strategy: "session"` would destroy the sandbox entirely.

## Live Browser View

Every session has a `liveUrl`. Embed it in an iframe — no X-Frame-Options or CSP restrictions:

```tsx
<iframe
  src={session?.liveUrl}
  width="100%"
  height="720"
  style={{ border: "none" }}
/>
```

Updates in real-time, no polling needed. The user can also interact with the browser directly via the iframe.

## Python Equivalent

Same pattern with asyncio polling:

```python
import asyncio
from browser_use_sdk.v3 import AsyncBrowserUse

async def main():
    client = AsyncBrowserUse()

    # Create session and dispatch task
    session = await client.sessions.create(task="Find the top HN post", keep_alive=True)
    print(f"Live: {session.live_url}")

    # Poll messages
    seen = set()
    while True:
        s = await client.sessions.get(str(session.id))
        msgs = await client.sessions.messages(str(session.id), limit=100)

        for m in msgs.messages:
            if str(m.id) not in seen:
                seen.add(str(m.id))
                print(f"[{m.role}] {m.data[:200]}")

        if s.status.value in ("idle", "stopped", "error", "timed_out"):
            print(f"\nDone — {s.output}")
            break
        await asyncio.sleep(2)

asyncio.run(main())
```

## SDK Methods Summary

| Method | Purpose |
|--------|---------|
| `v3.sessions.create()` | Create session, dispatch tasks |
| `v3.sessions.get()` | Poll session status |
| `v3.sessions.messages()` | Get conversation history |
| `v3.sessions.stop()` | Stop current task |
| `v3.workspaces.list()` | Populate workspace dropdown |
| `v2.profiles.list()` | Populate profile dropdown |

Full source: [github.com/browser-use/chat-ui-example](https://github.com/browser-use/chat-ui-example)
