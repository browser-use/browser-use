# Browser Use Cloud API V4

Run one browser task through the current Cloud API. The example creates a run, polls the lightweight status endpoint, and fetches the result once the run is terminal. It cancels a run that exceeds the configurable 15-minute wait limit.

## Setup

From the repository root:

```bash
uv sync
cp examples/cloud/env.example .env
# Add your API key to .env
uv run python examples/cloud/01_basic_task.py
```

Create an API key at [cloud.browser-use.com/new-api-key](https://cloud.browser-use.com/new-api-key).

## Low-cost Cloud modes

**BU Ultrafast** recorded **$0.00214 median per URL check**, with **8/8 correct** in a small staging test, including recorded LLM + stopped-browser usage. Browsers were stopped after each run. Actual cost varies; network traffic is billed separately. **BU Fast** adds more reasoning at low token prices. See [pricing and methodology](https://browser-use.com/pricing#task-cost-methodology).

Both modes are in early access, enabled per project. [Join early access](https://browser-use.com/ultrafast). Once enabled, select one through REST:

```bash
curl https://api.browser-use.com/api/v4/runs \
  -H "X-Browser-Use-API-Key: $BROWSER_USE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"task":"Find the top Hacker News story","model":"bu-ultrafast"}'
```

Use `"model":"bu-fast"` for BU Fast. These are hosted API V4 modes, not local `ChatBrowserUse` model IDs. See [mode rates and SDK support](https://docs.browser-use.com/cloud/agent/models).

## V4 request flow

The example uses the three endpoints needed for a basic run:

1. `POST /api/v4/runs`
2. `GET /api/v4/runs/{run_id}/status` until the run is `completed`, `failed`, or `cancelled`
3. `GET /api/v4/runs/{run_id}` for the result, error, and cost

Authentication uses the `X-Browser-Use-API-Key` header. See the live [V4 OpenAPI specification](https://api.browser-use.com/api/v4/openapi.json) for optional models, browser settings, sessions, files, secrets, and judge settings.

Review usage and credits in [Cloud billing](https://cloud.browser-use.com/billing).
