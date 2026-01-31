# Extraction System Overhaul — Multi-PR Plan

## Problem Summary

The current extraction pipeline (`tools/service.py:687-815`) is a single-shot, unstructured, free-text LLM call over markdownified page content. It works for one-off fact retrieval but fails at scale because: no schema enforcement, naive char-based pagination that splits tables, no retry/error recovery, no way to reuse extraction strategies across similar pages, and the agent loop rediscovers extraction intent every step.

## PR Dependency Graph

```
PR 1 (Schema Enforcement) ─────┬──→ PR 3 (Sub-Agent + Batching)
                                │
PR 2 (Content Chunking) ───────┘         │
                                          ↓
PR 4 (CSS Selector + Caching) ──→ PR 5 (Error Recovery + Multi-Page Aggregation)
```

PR 1 and PR 2 can be developed in parallel. PR 3 depends on both. PR 4 depends on PR 1. PR 5 depends on PR 1, PR 3, optionally PR 4.

---

## PR 1: Schema-Enforced Extraction

**Goal**: Let the extract action accept an optional JSON Schema and return validated, structured output instead of free-text.

### Files Modified

- **`browser_use/tools/views.py`** — Add `output_schema: dict | None = Field(default=None)` to `ExtractAction` (line 7-14)
- **`browser_use/tools/service.py`** — Branch the extract handler (lines 786-790): if `output_schema` is present, convert it to a Pydantic model and call `page_extraction_llm.ainvoke(messages, output_format=DynamicModel)` instead of the free-text path
- **`browser_use/tools/extraction/__init__.py`** — New subpackage
- **`browser_use/tools/extraction/schema_utils.py`** — New file: `schema_dict_to_pydantic_model(schema: dict) -> type[BaseModel]` converts a JSON Schema dict to a runtime Pydantic model. Handles: object, array, primitives, nested objects. Raises `ValueError` on unsupported features (anyOf, $ref loops, etc.)
- **`browser_use/tools/extraction/views.py`** — New file: `ExtractionResult` model with `data: dict | list[dict] | str`, `schema_used: dict | None`, `is_partial: bool`, `source_url: str | None`, `content_stats: dict | None`

### Key Design Decisions

- `output_schema` is a `dict` (JSON Schema), not `type[BaseModel]`, because the agent LLM emits JSON — it can't reference Python classes. Programmatic users who have a Pydantic model can call `MyModel.model_json_schema()` to get the dict.
- The existing `BaseChatModel.ainvoke(output_format=type[T])` protocol (base.py:39-40) already handles provider differences (OpenAI `response_format`, Anthropic `tool_use`, etc.). We just need to produce the `type[T]`.
- When `output_schema` is None, behavior is identical to today (backward compatible).
- On schema conversion failure or LLM validation error, fall back to free-text extraction with a warning in the result.
- System prompt gets a schema-specific addendum: "Return data matching the provided schema. Do not add fields not in the schema."

### Result Flow

Structured extraction returns `ActionResult` with:
- `extracted_content`: JSON-serialized structured data (still a string for transport)
- `metadata`: `{"extraction_result": ExtractionResult.model_dump()}`
- `long_term_memory`: compact summary of what was extracted

### Testing

`tests/ci/test_structured_extraction.py`:
1. `schema_dict_to_pydantic_model` round-trips for flat objects, nested objects, arrays, primitives
2. Extract with `output_schema=None` → free-text (backward compat)
3. Extract with valid `output_schema` → mock LLM returns JSON matching schema → validated result
4. Extract with unsupported schema features → falls back to free-text with warning
5. Use `pytest-httpserver` to serve HTML with known product data, verify extracted JSON matches

---

## PR 2: Structure-Aware Content Chunking

**Goal**: Replace the naive char-based truncation (service.py:726-741) with chunking that respects structural boundaries — never split a table row, code block, or list item.

### Files Modified

- **`browser_use/dom/markdown_extractor.py`** — Add `chunk_markdown_by_structure(content: str, max_chunk_size: int = 100000, overlap_lines: int = 3) -> list[MarkdownChunk]`
- **`browser_use/dom/views.py`** — Add `MarkdownChunk` dataclass: `content`, `start_char`, `end_char`, `structural_context` (e.g. "## Products (rows 1-50 of 200)"), `has_more`
- **`browser_use/tools/service.py`** — Replace lines 726-744 (truncation block) with a call to `chunk_markdown_by_structure`. Use first chunk, set `next_start_char` from chunk metadata. Add `structural_context` to `content_stats`.
- **`browser_use/dom/serializer/html_serializer.py`** — Add table normalization preprocessing: synthesize `<thead>` from first `<tr>` when missing, pad short rows with empty `<td>` cells. This fixes the input to `markdownify` so it produces valid markdown tables.

### Chunking Algorithm

Split priority (highest to lowest):
1. Between top-level sections (`#` headers)
2. Between sub-sections (`##` headers)
3. Between paragraphs (`\n\n`)
4. After complete table rows (lines ending with `|`)
5. After list items (lines starting with `- ` or `* `)
6. At sentence boundaries (`. ` followed by uppercase)

Never split inside: table rows, code blocks (``` ... ```), list item continuations (indented lines).

`overlap_lines` adds context from the end of the previous chunk to the start of the next — important for tables where column headers are in chunk N but data continues in chunk N+1.

### Testing

`tests/ci/test_content_chunking.py`:
1. `chunk_markdown_by_structure` with a markdown table — no row split
2. With nested headers — chunks respect header boundaries
3. With code blocks — code blocks not split
4. End-to-end: `pytest-httpserver` serves a 200-row HTML table, extract + chunk, verify first chunk has complete rows only
5. Table normalization: malformed HTML table → valid markdown table output

---

## PR 3: Extraction Sub-Agent with Batched Pagination

**Goal**: For large pages or schema-driven extraction, run an autonomous extraction loop that chunks content, processes chunks in parallel, merges and deduplicates results.

### Files Created/Modified

- **`browser_use/tools/extraction/service.py`** — New file: `ExtractionSubAgent` class

```python
class ExtractionSubAgent:
    def __init__(self, llm: BaseChatModel, max_concurrent_chunks: int = 3, max_retries_per_chunk: int = 2): ...

    async def extract(self, content: str, query: str, output_schema: dict | None = None) -> ExtractionResult:
        chunks = chunk_markdown_by_structure(content)
        if len(chunks) == 1:
            return await self._extract_single(chunks[0], query, output_schema)
        # Parallel extraction with semaphore
        results = await asyncio.gather(*[self._extract_chunk(c, query, output_schema) for c in chunks])
        return self._merge_results(results, output_schema)
```

- **`browser_use/tools/extraction/views.py`** — Add `ExtractionConfig` (concurrency, retries, dedup strategy), `ChunkExtractionResult` (per-chunk data + error + retry count)
- **`browser_use/tools/service.py`** — Modify extract handler: if content > 30K chars or `output_schema` is provided, delegate to `ExtractionSubAgent` instead of single LLM call. Below threshold with no schema → current fast path.
- **`browser_use/agent/views.py`** — Add `extraction_config: ExtractionConfig | None = None` to `AgentSettings` (after line 51)

### Merge Strategy

- Array schemas: concatenate arrays, deduplicate by exact field match
- Object schemas: deep merge, prefer later chunks for conflicting scalars
- Free-text: concatenate with `---` separators and chunk context headers

### Key Design Decision

This is NOT a full `Agent` instance. It doesn't navigate, click, or manage browser state. It's a stateless function: markdown in → structured data out. The outer agent handles navigation; the sub-agent handles content processing. This avoids the complexity of nested agent loops.

### Testing

`tests/ci/test_extraction_sub_agent.py`:
1. Single chunk (small content) → single `ainvoke` call
2. Multi-chunk → parallel processing, results merged
3. Deduplication: overlapping products from two chunks → no duplicates
4. One chunk fails, others succeed → partial result with `is_partial=True`
5. Retry: mock LLM fails then succeeds → verify retry count

---

## PR 4: CSS Selector Targeting + Extraction Strategy Cache

**Goal**: Let the agent narrow extraction to a specific DOM subtree via CSS selector, and cache successful extraction strategies for reuse on similar pages.

### Files Created/Modified

- **`browser_use/tools/views.py`** — Add to `ExtractAction`: `css_selector: str | None = Field(default=None)`, `extraction_id: str | None = Field(default=None)`
- **`browser_use/tools/extraction/cache.py`** — New file: `ExtractionStrategy` model (id, url_pattern, css_selector, output_schema, query_template, success/failure counts) + `ExtractionCache` class (register, get, find_matching by URL glob)
- **`browser_use/tools/service.py`** — When `css_selector` is provided, use `Runtime.evaluate` via CDP to get `document.querySelector(selector).outerHTML`, then feed that narrowed HTML through the extraction pipeline instead of full page content. When `extraction_id` is provided, look up cached strategy and reuse its selector + schema.
- **`browser_use/agent/service.py`** — Add `ExtractionCache` instance to Agent, pass through registry as injectable param
- **`browser_use/tools/registry/service.py`** — Add `extraction_cache: ExtractionCache` to special param types (~line 56-71)

### Auto-Caching

After a successful extraction with `output_schema`, the handler auto-registers an `ExtractionStrategy` in the cache. The `extraction_id` is returned in `ActionResult.metadata` so the agent LLM can reference it on subsequent pages. The system prompt gets guidance: "If you see an extraction_id from a previous extraction and are on a structurally similar page, reuse it."

### Testing

`tests/ci/test_extraction_cache.py`:
1. Cache register/get round-trip
2. `find_matching` with URL glob patterns
3. Extract with `css_selector` → only selected element's content extracted (serve page with `div#target`)
4. Extract with `extraction_id` → cached schema and selector reused
5. Auto-registration after successful extraction

---

## PR 5: Error Recovery + Multi-Page Aggregation

**Goal**: Add retry logic to extraction calls and an aggregation layer that merges results across multiple extract actions (multiple pages, pagination).

### Files Created/Modified

- **`browser_use/tools/extraction/service.py`** — Add `_extract_with_retry` to `ExtractionSubAgent`: retry on `ValidationError` (stricter prompt), empty data (hint prompt), timeout (split chunk in half), rate limit (exponential backoff)
- **`browser_use/tools/extraction/aggregator.py`** — New file: `ExtractionAggregator` class that maintains running collection of `ExtractionResult` objects. Methods: `add(result)`, `aggregate() -> ExtractionResult`, `summary -> str`. Keyed by `extraction_id` on the `ExtractionCache`.
- **`browser_use/tools/extraction/views.py`** — Add `ExtractionError` model (error_type enum, message, chunk_index, retries_exhausted, fallback_used), `ExtractionRetryConfig` model
- **`browser_use/tools/service.py`** — Wire aggregator: if `extraction_id` exists in cache and has an active aggregator, add current result to it. Return both current-page data and running aggregate summary in `ActionResult.long_term_memory`.

### Aggregation Flow

1. Agent calls `extract(query="Get products", extraction_id="abc")` on page 1
2. Result: "20 products extracted. extraction_id=abc. Navigate to next page and reuse."
3. Agent navigates to page 2, calls `extract(extraction_id="abc")`
4. Aggregator merges: "40 unique products from 2 pages"
5. Agent calls `done` with aggregate result

### Testing

`tests/ci/test_extraction_recovery.py`:
1. Retry on ValidationError: fail then succeed
2. Retry on empty result: empty then populated
3. Split on timeout: large chunk times out, sub-chunks succeed
4. Aggregation: three sequential extracts with same extraction_id → deduplicated merge
5. Aggregate summary in `long_term_memory`

---

## New File Structure

```
browser_use/tools/extraction/
    __init__.py           # PR 1
    schema_utils.py       # PR 1: JSON Schema ↔ Pydantic conversion
    views.py              # PR 1, PR 3, PR 5: ExtractionResult, ExtractionConfig, etc.
    service.py            # PR 3: ExtractionSubAgent
    cache.py              # PR 4: ExtractionCache, ExtractionStrategy
    aggregator.py         # PR 5: ExtractionAggregator
```

## Verification

After all PRs merged, run:
```bash
uv run pytest -vxs tests/ci/test_structured_extraction.py
uv run pytest -vxs tests/ci/test_content_chunking.py
uv run pytest -vxs tests/ci/test_extraction_sub_agent.py
uv run pytest -vxs tests/ci/test_extraction_cache.py
uv run pytest -vxs tests/ci/test_extraction_recovery.py
uv run pytest -vxs tests/ci/  # full suite, verify no regressions
uv run pyright
uv run ruff check --fix && uv run ruff format
```
