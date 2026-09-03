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

## V4 request flow

The example uses the three endpoints needed for a basic run:

1. `POST /api/v4/runs`
2. `GET /api/v4/runs/{run_id}/status` until the run is `completed`, `failed`, or `cancelled`
3. `GET /api/v4/runs/{run_id}` for the result, error, and cost

Authentication uses the `X-Browser-Use-API-Key` header. See the live [V4 OpenAPI specification](https://api.browser-use.com/api/v4/openapi.json) for optional models, browser settings, sessions, files, secrets, and judge settings.

Review usage and credits in [Cloud billing](https://cloud.browser-use.com/billing).
