# Bilig WorkPaper

This example gives a Browser Use agent a custom tool for exact formula readback with
[`@bilig/workpaper`](https://github.com/proompteng/bilig). The browser agent can gather
quote inputs from a page, then delegate the formula workbook calculation to Bilig instead
of doing arithmetic in the LLM.

The tool starts Bilig's local formula-readback server, writes a conversion-rate input,
reads dependent forecast formulas, verifies persistence/restore behavior, and returns a
structured JSON proof.

## Requirements

- Node.js and npm, for `npm exec --package @bilig/workpaper`
- Browser Use development environment installed with `uv sync`
- `BROWSER_USE_API_KEY` only for the full browser-agent run

## Run the no-key smoke test

From the repository root:

```bash
uv run python examples/integrations/bilig_workpaper/bilig_workpaper_example.py --smoke
```

The smoke test does not call an LLM. It directly runs the custom tool path and should
print a `verified: true` JSON object with before/after ARR values.

## Run with a Browser Use agent

```bash
export BROWSER_USE_API_KEY=...
uv run python examples/integrations/bilig_workpaper/bilig_workpaper_example.py
```

The agent opens a small quote-input page, reads the conversion rate, calls the Bilig
tool, and reports the computed WorkPaper output.
