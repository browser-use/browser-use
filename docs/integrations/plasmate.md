# Plasmate Integration

[Plasmate](https://plasmate.app) is an open-source browser engine that compiles HTML into a Semantic Object Model (SOM) - a structured representation optimized for AI agents. It can be used alongside or as a replacement for Chrome in Browser Use workflows.

## Why Use Plasmate with Browser Use?

- **16.6x fewer tokens** - SOM compresses web pages dramatically, reducing LLM costs
- **50x faster** - No rendering engine overhead
- **~30MB memory** vs Chrome's 300-500MB
- **Semantic output** - Clean structured data instead of raw DOM

## Installation

```bash
pip install plasmate browser-use
```

## Quick Start

```python
import subprocess
import json

def get_som(url: str) -> dict:
    """Get semantic representation of a web page using Plasmate."""
    result = subprocess.run(
        ["plasmate", "som", "--url", url, "--format", "json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)

# Use in your Browser Use workflow
som = get_som("https://example.com")
# som contains structured navigation, content, forms, tables
```

## When to Use Plasmate vs Chrome

| Use Case | Recommended |
|----------|-------------|
| Reading/extracting web content | Plasmate (faster, cheaper) |
| Filling forms and clicking buttons | Chrome (needs full browser) |
| Scraping at scale (1000+ pages) | Plasmate (10x less memory) |
| Screenshots | Chrome (or Plasmate with Chrome delegation) |
| JavaScript-heavy SPAs | Chrome (better JS coverage) |
| Static/server-rendered pages | Plasmate (much faster) |

## SOM Output Format

Plasmate outputs a Semantic Object Model with these node types:
- `navigation` - Site navigation links
- `content` - Main page content (headings, paragraphs, lists)
- `form` - Interactive forms with fields
- `table` - Data tables with headers and rows
- `media` - Images, videos, audio
- `metadata` - Page title, description, structured data

## Links

- [Plasmate GitHub](https://github.com/plasmate-labs/plasmate)
- [SOM Specification](https://docs.plasmate.app/som-spec)
- [Benchmarks](https://docs.plasmate.app/benchmark-cost)
- [W3C Community Group](https://www.w3.org/community/web-content-browser-ai/)
