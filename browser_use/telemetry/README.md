# Telemetry privacy

Product telemetry includes an explicitly reviewed set of operational fields:
model and provider identifiers, package version, execution settings, step and
token counts, duration, and outcome flags.

It does not send task text, action parameters or history, visited URLs, browser
connection addresses, final responses, error messages, or judge reasoning.
MCP telemetry also excludes command lines, server and tool names, and error
text. Automatic exception capture is disabled.

Event serialization uses an allowlist. Adding a dataclass field does not add it
to an outgoing event. Legacy content fields remain accepted by event
constructors for compatibility, but are excluded from outgoing properties.
The agent itself does not populate these content fields.

To disable product telemetry entirely, set `ANONYMIZED_TELEMETRY=false` before
initializing Browser Use. There is no diagnostic-content upload option in this
change.

This policy applies to product analytics. It does not change the task content
sent to the model provider, local logs and saved history, or separately
configured cloud synchronization. Review those destinations before using
sensitive data. An anonymous device identifier is still used when product
telemetry is enabled; these events are not a promise of complete anonymity.

Run the privacy regression tests without contacting an analytics service:

```bash
ANONYMIZED_TELEMETRY=false BROWSER_USE_CLOUD_SYNC=false \
  python -m pytest tests/ci/test_telemetry_privacy.py -o addopts='-q --tb=short'
```
