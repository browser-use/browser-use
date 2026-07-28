# arXiv Integration

This example shows a polite browser fallback for collecting structured arXiv search results with Browser Use.

Use the official arXiv export API, OpenAlex, or Semantic Scholar first when possible. This browser workflow is useful when a research agent needs to verify arXiv result pages, collect PDF links, or recover metadata after an upstream API failure.

## Setup

Set your Browser Use API key:

```sh
export BROWSER_USE_API_KEY=your-key
```

## Run

From the repository root:

```sh
uv run python examples/integrations/arxiv/arxiv_literature_browser.py "large language model interpretability" --limit 10
```

Use `--headed` while developing selectors or reviewing extraction behavior.

## What it demonstrates

- Restricting the browser to arXiv with `BrowserProfile(allowed_domains=["*.arxiv.org", "arxiv.org"])`
- Returning structured paper metadata with a Pydantic output model
- Treating browser automation as a fallback, not a replacement for official APIs
- Stopping on CAPTCHA, login, bot-protection, or other access-control pages

The example extracts title, authors, arXiv ID, abstract, URL, PDF URL, submitted date, and subjects.
