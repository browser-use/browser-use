# Model configuration

Python `Agent` and CLI tasks default to `bu-recommended` through the Browser Use gateway.
Set `BROWSER_USE_API_KEY` for gateway authentication.
Create a key in [Browser Use Cloud](https://cloud.browser-use.com/settings?tab=api-keys&new=1).

| Public alias     | Purpose                           |
| ---------------- | --------------------------------- |
| `bu-recommended` | Default Browser Use model preset  |
| `bu-balanced`    | Balanced Browser Use model preset |
| `bu-smart`       | Smart Browser Use model preset    |

The gateway owns each alias's physical model.
The SDK sends the alias unchanged.
The aliases default to high reasoning.
The SDK also accepts `browser-use/` before each alias.
Gateway deployment must enable these aliases before public release.

```python
from browser_use import Agent

agent = await Agent.create(model="bu-smart")
```

An explicit `model="provider/model"` selects another provider or model.
Known provider transports accept new model IDs without catalog registration.
New transport protocols still require implementation.
The library never silently substitutes a different model.

BU2 does not support Pi.
Use `bu-recommended` with the Pi agent.
Install `browser-use<1` to retain the old BU2 agent.

TypeScript keeps deterministic browser sessions model-free when callers omit `model`.
Select a public alias for TypeScript agent tasks:

```typescript
import { BrowserUse } from '@browser_use/pi';

const agent = await BrowserUse.create({ model: 'bu-recommended' });
```

The gateway endpoint is `https://api.browser-use.com/api/llm/v1`.
It uses the OpenAI Chat Completions protocol.
Its conservative context limit is 250,000 tokens.
Its conservative output limit is 32,000 tokens.
Gateway prices remain unknown unless callers supply explicit prices.
Provider catalog prices do not establish gateway billing.

Use `modelInfo` for endpoint, protocol, context, capabilities, and pricing overrides.
Private gateways can supply a base URL and explicit credentials.
Keep credentials outside generated-code workers where possible.

A monetary budget requires known prices.
Use explicit time and turn limits when pricing is unknown.

Model metadata supplies context and image capabilities.
Incorrect metadata can cause rejected requests or early compaction.
Explicit overrides take precedence over catalog suggestions.
