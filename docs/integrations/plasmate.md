# Plasmate SOM Integration

[Plasmate](https://github.com/plasmate-labs/plasmate) is a headless browser engine built for AI agents. Instead of raw HTML or DOM snapshots, it outputs **SOM (Semantic Object Model)** - a structured JSON format that reduces token costs by 90%+ while preserving content, structure, and interactivity.

## Why SOM?

Sending raw HTML to an LLM is expensive. A typical web page contains 300-500KB of HTML, and 80-95% of that is presentation markup (CSS classes, layout divs, script tags) with zero semantic value.

SOM compiles HTML into what matters:

```
HTML: <div class="sc-1234 flex items-center gap-2">
        <a href="/about" class="text-blue-500 hover:underline font-medium">About</a>
      </div>

SOM:  {"role": "link", "text": "About", "attrs": {"href": "/about"}, "actions": ["click"]}
```

**Benchmarks across 49 real-world websites:**
- 16.6x overall compression (HTML tokens to SOM tokens)
- 10.5x median compression
- 94% cost savings at GPT-4, GPT-4o, and Claude pricing
- Best case: 116.9x on cloud.google.com

Full benchmark: [plasmate.app/docs/benchmark-cost](https://plasmate.app/docs/benchmark-cost)

## Installation

```bash
pip install plasmate-browser-use
```

You also need the Plasmate binary:

```bash
# macOS / Linux
curl -fsSL https://plasmate.app/install.sh | sh

# Or via Cargo
cargo install plasmate
```

## Usage with Browser Use

### Basic Content Extraction

Use `PlasmateExtractor` to get token-efficient page content:

```python
from plasmate_browser_use import PlasmateExtractor

extractor = PlasmateExtractor()

# Get structured page context for LLM consumption
context = extractor.get_page_context("https://news.ycombinator.com")
print(context)
# Output:
# # Hacker News
# URL: https://news.ycombinator.com/
# ## Interactive Elements (200)
#   [e_abc123] link "Show HN: ..." (click)
#   ...
# ## Content
#   ...
# Compression: 1.3x (35018 HTML bytes -> 27076 SOM bytes)
```

### Markdown Extraction

```python
# Get readable markdown (great for RAG pipelines)
md = extractor.extract_markdown("https://example.com")
```

### Raw SOM Data

```python
# Get the full SOM dict for custom processing
som = extractor.extract("https://example.com")
print(som["meta"]["element_count"])  # 4
print(som["regions"][0]["elements"])  # structured elements
```

### Async Support

All methods have async variants:

```python
import asyncio

async def main():
    extractor = PlasmateExtractor()
    context = await extractor.get_page_context_async("https://example.com")
    print(context)

asyncio.run(main())
```

### Working with SOM Data

The `som-parser` package provides query utilities:

```python
from som_parser import parse_som, get_links, get_interactive_elements, to_markdown

# Parse raw SOM output
som = parse_som(extractor.extract("https://example.com"))

# Find all links
links = get_links(som)
for link in links:
    print(f"{link['text']} -> {link['href']}")

# Get interactive elements (buttons, inputs, links)
interactive = get_interactive_elements(som)

# Convert to markdown
md = to_markdown(som)
```

## Token Cost Comparison

| Site | HTML Tokens | SOM Tokens | Savings |
|------|------------|------------|---------|
| github.com | 94,956 | 9,005 | 90% |
| vercel.com | 198,761 | 5,565 | 97% |
| cloud.google.com | 464,616 | 3,973 | 99% |
| reuters.com | 262,746 | 19,586 | 93% |
| tailwindcss.com | 233,071 | 4,338 | 98% |

## Resources

- [SOM Spec v1.0](https://plasmate.app/docs/som-spec)
- [Cost Analysis Benchmark](https://plasmate.app/docs/benchmark-cost)
- [Why SOM](https://plasmate.app/docs/why-som)
- [Plasmate GitHub](https://github.com/plasmate-labs/plasmate)
- [som-parser (npm)](https://www.npmjs.com/package/som-parser)
- [som-parser (PyPI)](https://pypi.org/project/som-parser/)
