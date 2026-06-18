# Nimble search engine

Use [Nimble](https://nimbleway.com) as an API-backed search engine for Browser Use's
built-in `search` action.

## What & why

The built-in `search` action navigates the browser to Google/Bing/DuckDuckGo and
scrapes the rendered results page. With `engine="nimble"` it instead calls Nimble's
search API and returns structured results (title, URL, snippet) in a single call — no
page navigation, no CAPTCHA risk.

Reach for it when you want clean, structured results without the agent browsing a
SERP — for example research and extraction tasks where scraping Google is brittle. The
browser-navigation engines (`duckduckgo`, the default, plus `google`/`bing`) stay
available for when you actually want the agent to browse the results page.

## Setup

```bash
uv pip install 'browser-use[nimble]'
export NIMBLE_API_KEY='your-key'   # get a key from Nimble
```

If the `nimble` extra isn't installed or `NIMBLE_API_KEY` is unset, the engine returns a
friendly error instead of raising.

## Run

From the repository root:

```bash
uv run python examples/integrations/nimble/nimble_search.py
```

## How it works

The agent calls the normal `search` action with `engine="nimble"`; the action routes the
query to Nimble's `/v1/search` and returns the results inline as the action's
`extracted_content`. Nothing else in the agent loop changes. The API key is read from the
environment only — no secrets are committed.
