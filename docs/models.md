# Model configuration

Python and TypeScript `Agent` clients and CLI tasks default to `bu-auto` through the Browser Use gateway.
Set `BROWSER_USE_API_KEY` or run `browser-use auth login` for Python and CLI authentication.
Create a key in [Browser Use Cloud](https://cloud.browser-use.com/settings?tab=api-keys&new=1).
TypeScript accepts `apiKey` or `BROWSER_USE_API_KEY`.

| Model          | Purpose                   | Default reasoning          | Default service tier       |
| -------------- | ------------------------- | -------------------------- | -------------------------- |
| `bu-auto`      | Moving recommended choice | From the selected revision | From the selected revision |
| `bu-fast`      | General browser tasks     | Medium                     | Default                    |
| `bu-ultrafast` | Lower latency             | Low                        | Priority                   |
| `bu-smart`     | Harder browser tasks      | High                       | Default                    |

The gateway selects models through evaluated releases.
It resolves a moving alias once during session creation.
The session keeps that revision for follow-ups and compaction.
A new session can select a newer revision.
Use `bu-fast-v1`, `bu-ultrafast-v1`, or `bu-smart-v1` when your application requires a fixed Browser Use revision.
These names identify Browser Use configurations, rather than upstream provider snapshots.
The result includes `resolvedModel` and `serviceTier` for inspection.
The SDK also accepts `browser-use/` before these names.

```python
from browser_use import Agent

agent = await Agent.create(model="bu-smart", service_tier="priority")
```

Model choice and service tier control different settings.
`service_tier` selects `default`, `priority`, or `ultrafast` processing when the gateway supports that combination.
`ultrafast` processing requires an eligible project and currently applies to `bu-smart`.
The catalog supplies available tiers and prices.
Explicit `reasoning` and `service_tier` override the revision defaults.
The existing `mode="ultrafast"` changes browser prompting; it does not select a service tier.

`bu-recommended` and `bu-balanced` remain hidden compatibility names with high reasoning.
New applications should use the public names above.
`bu-latest` remains a legacy gateway name and does not select the Pi agent.
BU2 does not support Pi.
Install `browser-use<1` to retain the old BU2 agent.

TypeScript `Agent.create()` supplies the same default as Python:

```typescript
import { Agent } from '@browser_use/pi';

const agent = await Agent.create();
```

An explicit `model="provider/model"` selects another provider or model.
Known provider transports accept new model IDs without catalog registration.
New transport protocols still require implementation.
Unknown provider models use conservative text-only capabilities until callers supply `modelInfo`.
Use `modelInfo` for endpoint, protocol, context, capabilities, and pricing overrides.

The gateway endpoint is `https://api.browser-use.com/api/llm/v1`.
It uses the OpenAI Chat Completions protocol.
The authenticated `/models` catalog supplies revision limits, rates, and minimum request prices.
Catalog errors stop session creation before browser allocation.
The SDK estimates costs from these rates, including long-context surcharges and minimum request prices.
The current surcharge starts above 272,000 input tokens, including cache reads and writes.
It doubles input and cache prices and multiplies output prices by 1.5.
The SDK applies the minimum request price after that surcharge.
The catalog supplies these thresholds and multipliers for each service tier.
Cloud billing records contain authoritative charges.
Provider catalog prices do not establish gateway billing.

A monetary budget requires known prices.
Direct provider premium tiers require explicit prices for monetary budgets.
Cost limits stop subsequent requests after measured usage reaches the limit.
A request can exceed the remaining budget before the SDK receives its usage.
Time and turn limits remain available when pricing is unknown.
