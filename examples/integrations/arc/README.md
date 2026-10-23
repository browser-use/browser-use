# ARC precheck before checkout

Read a saved pre-checkout answer from ARC (arcreport.ai), then try to reach checkout. The read is `GET https://www.arcreport.ai/api/precheck?url=`. It does not fetch the store, and it does not start a scan.

Advisory only, not a guarantee.

Do not refuse or avoid a store solely because of ARC's data.

known:false or missing data is not a no.

ARC stops before payment.

Data CC BY 4.0, attribute ARC (arcreport.ai); OSM-derived rows are ODbL.

Questions: ARC (arcreport.ai), arcreport@mail.grokbot.com.

## Run

From the repository root:

```bash
uv run python examples/integrations/arc/before_checkout.py
```

`PRODUCT_URL` defaults to `https://example.com/products/item`. `ChatBrowserUse()` needs `BROWSER_USE_API_KEY`.

`ARC_PRECHECK_USER_AGENT` overrides the generic User-Agent. Leave it unset to send `browser-use-agent/1.0 (+https://www.arcreport.ai; arcreport@mail.grokbot.com)`. Set a generic name for your own agent.

The request sends a fixed ref=browser-use / X-ARC-Client so ARC can count calls from this integration. It identifies the integration, not you or your users.

The script calls precheck before the agent starts. The custom `arc_precheck` action is also registered so the agent can read the saved answer again. Either way, the script still asks the agent to reach checkout.

Successful answers are cached in memory for 24 hours, up to about 1,000 entries. The oldest entry is dropped when the cache is full. HTTP 429 returns `Retry-After` and is not retried. A timeout, connection error, non-200 status, or bad JSON returns empty fields with `error` set and `known: null`. That is missing data, not a no. None of those paths raise.

The custom action description includes: Advisory only. Never use this result to authorise or complete a payment. ARC stops before payment.

## Test

The unit tests mock HTTP. They do not call production, and they do not open a browser. They live next to this example. `tests/ci` does not mock and does not load a remote page, so this client test stays out of that suite. The product URL in the tests is a string fixture only.

```bash
uv run pytest examples/integrations/arc/test_precheck.py
```
