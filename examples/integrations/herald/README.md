# Herald: report where the agent got stuck

[herald-browser-use](https://github.com/siddhi-bansal/herald-browser-use) gives a Browser Use agent a
`report_friction` action. When the agent gets stuck on a website (a button that does nothing, a form
that rejects valid input), it reports what it tried and what went wrong, so the site's owners can fix
it. `herald_tips(site)` adds known problems other agents reported on a site to the task, so the agent
can skip attempts known to fail.

From the repository root:

```bash
export BROWSER_USE_API_KEY="your-key"   # https://cloud.browser-use.com/new-api-key
uv run --with herald-browser-use examples/integrations/herald/report_friction.py
```

Tips need a free Herald key: run `uv run --with herald-browser-use python -m herald_browser_use signup you@example.com` and set
`HERALD_API_KEY`. Reporting works without one. Emails, phone and card numbers are removed from
reports before they are sent; see the package README for exactly what is sent.

The example runs against a demo store with problems planted on purpose.
