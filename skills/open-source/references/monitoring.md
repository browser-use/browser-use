# Monitoring & Observability

## Table of Contents
- [Cost Tracking](#cost-tracking)
- [Laminar](#laminar)
- [OpenLIT (OpenTelemetry)](#openlit-opentelemetry)
- [Telemetry](#telemetry)

---

## Cost Tracking

```python
agent = Agent(task="...", llm=llm, calculate_cost=True)
history = await agent.run()

# Access usage data
usage = history.usage
# Or via service
summary = await agent.token_cost_service.get_usage_summary()
```

## Laminar

Native integration for AI agent monitoring with browser session video replay.

### Setup

```bash
pip install lmnr
```

```python
from lmnr import Laminar

Laminar.initialize()  # Set LMNR_PROJECT_API_KEY env var
```

### Features

- Agent execution step capture with timeline
- Browser session recordings (full video replay)
- Cost and token tracking
- Trace visualization

### Authentication

Use `browser-use auth` for cloud sync (OAuth Device Flow), or self-host Laminar.

## OpenLIT (OpenTelemetry)

Zero-code OpenTelemetry instrumentation:

### Setup

```bash
pip install openlit browser-use
```

```python
import openlit

openlit.init()  # That's it — auto-instruments browser-use
```

### Features

- Execution flow visualization
- Cost and token tracking
- Debug failures with agent thought process
- Performance optimization insights

### Custom OTLP Endpoint

```python
openlit.init(otlp_endpoint="http://your-collector:4318")
```

### Integrations

Works with: Jaeger, Prometheus, Grafana, Datadog, New Relic, Elastic APM.

### Self-Hosted

```bash
docker run -d -p 3000:3000 -p 4318:4318 openlit/openlit
```

## Telemetry

Browser Use collects anonymous usage data via PostHog.

### Opt Out

```bash
ANONYMIZED_TELEMETRY=false
```

Or in Python:

```python
import os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
```

Zero performance impact. Source: [telemetry service](https://github.com/browser-use/browser-use/tree/main/browser_use/telemetry).
