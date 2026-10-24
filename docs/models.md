# Model configuration

Pass the exact model through `provider/model`.
A known provider transport can send a new model ID without catalog registration.
A new transport protocol still requires implementation.
The library never silently substitutes a different model.

```python
from browser_use import Agent

agent = await Agent.create(model="openai/gpt-6-luna")
```

Use `modelInfo` for endpoint, protocol, context, capabilities, and pricing overrides.
Private gateways can supply a base URL and explicit credentials.
Keep credentials outside generated-code workers where possible.

Unknown model pricing remains unknown in public measurements.
A monetary budget requires known prices.
Use explicit time and turn limits when pricing is unknown.

Model metadata supplies context and image capabilities.
Incorrect metadata can cause rejected requests or early compaction.
Explicit overrides take precedence over catalog suggestions.
