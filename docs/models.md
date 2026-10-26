# Model configuration

Python `Agent` and CLI tasks default to GPT-6 Luna through the Browser Use gateway.
Set `BROWSER_USE_API_KEY` for gateway authentication.
The gateway sends the exact model ID `openai/gpt-6-luna`.
An explicit `model` selects another provider or model.
Pass the exact model through `provider/model`.
A known provider transport can send a new model ID without catalog registration.
A new transport protocol still requires implementation.
The library never silently substitutes a different model.

```python
from browser_use import Agent

agent = await Agent.create()
```

TypeScript keeps `BrowserUse.create()` model-free when callers omit `model`.
Select the gateway explicitly for TypeScript agent tasks:

```typescript
import { BrowserUse, DEFAULT_MODEL } from '@browser_use/pi';

const agent = await BrowserUse.create({ model: DEFAULT_MODEL });
```

The gateway endpoint is `https://llm.api.browser-use.com/v1`.
It uses the OpenAI Chat Completions protocol.
Its default context limit is 250,000 tokens.
Its default output limit is 32,000 tokens.
Gateway prices remain unknown unless the caller supplies explicit prices.
Provider catalog prices do not establish gateway billing.

Use `modelInfo` for endpoint, protocol, context, capabilities, and pricing overrides.
Private gateways can supply a base URL and explicit credentials.
Keep credentials outside generated-code workers where possible.

Unknown model pricing remains unknown in public measurements.
A monetary budget requires known prices.
Use explicit time and turn limits when pricing is unknown.

Model metadata supplies context and image capabilities.
Incorrect metadata can cause rejected requests or early compaction.
Explicit overrides take precedence over catalog suggestions.
