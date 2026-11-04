# CookieGuard AI

Independent authentication-cookie security auditing for Browser Use workflows.

A login can succeed while its session cookie lacks `HttpOnly`. This example
runs a local Browser Use agent, then enforces a cookie policy with the external
[CookieGuard adapter](https://github.com/aiscihub/cookieguard-ai/tree/main/integrations/browser-use).
CookieGuard is maintained by @aiscihub as an external community integration.

Requires Python 3.11+, Node.js 24+, and a local Chrome/Chromium. Tested with
`browser-use==0.13.14` and `cookieguard-browser-use==0.1.0`.

From the Browser Use repository root, install into a separate environment:

```bash
uv venv --python 3.12 .venv-cookieguard
uv pip install --python .venv-cookieguard/bin/python \
  'browser-use==0.13.14' 'cookieguard-browser-use==0.1.0' 'pytest==9.0.2'
.venv-cookieguard/bin/browser-use install
.venv-cookieguard/bin/python examples/integrations/cookieguard/cookie_policy.py --baseline
.venv-cookieguard/bin/python examples/integrations/cookieguard/cookie_policy.py
.venv-cookieguard/bin/python examples/integrations/cookieguard/cookie_policy.py --mode secure
```

The middle command deliberately exits 1. Expected results:

| Mode | Server login | Cookie policy | Exit |
| --- | --- | --- | --- |
| Baseline, either cookie | Succeeds | NOT_AUDITED | 0 |
| CookieGuard, insecure | Succeeds | FAIL: CG001, missing HttpOnly | 1 |
| CookieGuard, secure | Succeeds | PASS | 0 |

The external package supplies the disposable loopback app and a scripted
stand-in for a model. Browser Use's real `Agent`, tools and Chromium execute the
workflow. No API key, OAuth scope, paid model, or separately started service is
needed. Telemetry, cloud sync, and default extensions are disabled. All data is
synthetic, and each run uses a fresh browser profile. Chromium accepts `Secure`
cookies on loopback HTTP; this does not test production HTTPS transport.

The integration points are `BrowserSession`, `Tools`, and the lifecycle around
`Agent.run()`. Keep the browser alive, attach before login, call `finish()` before
closing it, and enforce `assert_policy()` in developer code. Registering the
agent tool is optional; the final policy check works when it is never called.
For a model-driven workflow, use `ChatBrowserUse()` and your authorized app;
that needs a `BROWSER_USE_API_KEY` and is outside this reproducible example.

`PASS` means the configured checks passed on observed cookies. It does not prove
the app is secure or test XSS, CSRF, session fixation, theft, or exfiltration.
The developer must identify authentication-cookie names. Missing required
evidence yields `INCOMPLETE` (exit 2). The audit observes cookie values locally
in Python and its Node process; its report and tool output omit values.

Run the optional tests explicitly; the default upstream CI needs no new dependency:

```bash
.venv-cookieguard/bin/python -m pytest -o addopts='' -o log_cli=false \
  examples/integrations/cookieguard/test_cookie_policy.py -q
```

Broader fixtures, paired timing measurements and limitations live with the
[adapter's validation suite](https://github.com/aiscihub/cookieguard-ai/tree/39f6232d86276b6b5caaa114eab2654842f74750/integrations/browser-use/validation).

The [existing insecure-login versus secure-login demonstration](https://github.com/aiscihub/cookieguard-ai/blob/browser-use-v0.1.0b1/integrations/browser-use/docs/demo-and-tests.md)
includes a recording and provenance. Its November 3 model-driven run is separate
from the reproducible scripted runs above. Both demonstrate a successful login
followed by an independently enforced cookie-policy result.
