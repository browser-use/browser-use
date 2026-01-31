# Extraction System Overhaul — Multi-PR Plan (v2)

## Problem Summary

The current extraction pipeline (`tools/service.py:687-815`) is a single-shot, unstructured, free-text LLM call over markdownified page content. It fails at scale because: no schema enforcement, lossy markdown conversion, naive pagination, no reuse across similar pages, and no error recovery.

## Key Insight: Two Extraction Paths

The system should have two complementary extraction paths:

1. **Markdown path** (existing, improved) — DOM → markdown → LLM reads text → extracts data. Good for prose-heavy pages, simple queries, fallback.
2. **JS-codegen path** (new) — HTML structure → LLM writes JS extractor → CDP executes JS → structured JSON. Good for structured data (tables, lists, product grids), scale (generate script once, run N times for free).

The JS-codegen approach exists in embryonic form in CodeAgent (`browser_use/code_use/namespace.py:175-253` — `evaluate()` uses `cdp_client.send.Runtime.evaluate`). But CodeAgent is a heavyweight full agent loop. What we need is a single blocking LLM call that returns a JS script, not a multi-step agent.

## PR Dependency Graph

```
PR 1 (Schema Enforcement) ───┬──→ PR 3 (Markdown Chunking)
                              │
                              └──→ PR 2 (JS-Codegen Extraction) ──→ PR 4 (Strategy Cache)
                                                                        │
                                                                        └──→ PR 5 (Recovery + Aggregation)
```

PR 1 is the foundation. PR 2 and PR 3 can be developed in parallel after PR 1. PR 4 depends on PR 2. PR 5 depends on PR 2 and PR 4.

---

## PR 1: Schema-Enforced Extraction

**Goal**: Add optional `output_schema` to the extract action. When present, use LLM structured output (`ainvoke(output_format=...)`) to return validated JSON instead of free-text.

### Files Modified

- **`browser_use/tools/views.py`** — Add `output_schema: dict | None = Field(default=None)` to `ExtractAction`
- **`browser_use/tools/service.py`** (lines 786-790) — Branch: if `output_schema` present, convert to Pydantic model via `schema_dict_to_pydantic_model()`, call `ainvoke(messages, output_format=DynamicModel)`. Fall back to free-text on failure.
- **`browser_use/tools/extraction/__init__.py`** — New subpackage
- **`browser_use/tools/extraction/schema_utils.py`** — New: `schema_dict_to_pydantic_model(schema: dict) -> type[BaseModel]`. Converts JSON Schema dict → runtime Pydantic model. Handles object, array, primitives, nested objects. Raises `ValueError` on unsupported features.
- **`browser_use/tools/extraction/views.py`** — New: `ExtractionResult(data, schema_used, is_partial, source_url, content_stats)`

### Design Decisions

- `output_schema` is `dict` (JSON Schema), not `type[BaseModel]` — the agent LLM emits JSON, can't reference Python classes. Programmatic users call `MyModel.model_json_schema()`.
- Leverages existing `BaseChatModel.ainvoke(output_format=type[T])` (base.py:39-40) which already handles provider differences.
- `output_schema=None` preserves all existing behavior (backward compatible).
- On schema conversion or validation failure, falls back to free-text with warning.

### Testing (`tests/ci/test_structured_extraction.py`)

1. `schema_dict_to_pydantic_model` round-trips for flat, nested, array, primitive types
2. Extract with `output_schema=None` → free-text (backward compat)
3. Extract with valid schema → validated JSON via mock LLM
4. Unsupported schema → graceful fallback to free-text
5. `pytest-httpserver` page with known data, verify extracted JSON

---

## PR 2: JS-Codegen Extraction Action

**Goal**: New `extract_with_script` action. A blocking LLM sub-agent generates a JavaScript extraction script from the page's HTML structure, executes it via CDP `Runtime.evaluate`, returns structured JSON. Does not pollute the main agent's context.

### Architecture

```
Main agent calls extract_with_script(query, output_schema?, css_selector?)
  │
  ├─ 1. Get page HTML
  │     ├─ If css_selector provided: CDP Runtime.evaluate → querySelector(css).outerHTML
  │     └─ If no selector: HTMLSerializer.serialize(enhanced_dom_tree) (already cleans scripts/styles/base64)
  │
  ├─ 2. Truncate HTML to ~100K chars for LLM context (structure sampling, not content extraction)
  │     Key insight: HTML is for the LLM to understand DOM structure and write selectors.
  │     The JS executes on the FULL live DOM, so truncation of the prompt HTML is safe.
  │
  ├─ 3. Single blocking LLM call (page_extraction_llm):
  │     System: "Write a JS IIFE that extracts data matching [schema] from a page with this structure"
  │     User: "<html_structure>...</html_structure>\n<query>...</query>\n<schema>...</schema>"
  │     → LLM returns JS code
  │
  ├─ 4. Execute JS via CDP Runtime.evaluate (returnByValue=True, awaitPromise=True)
  │     Reuse evaluate() pattern from code_use/namespace.py:175-253
  │
  ├─ 5. Validate result against output_schema (if provided)
  │     If validation fails: retry once with error feedback in prompt
  │
  └─ 6. Return ActionResult with structured JSON
        extracted_content = JSON string
        metadata = {js_script, css_selector, extraction_id} (for caching in PR 4)
```

### What the LLM Sees (separate context, not in main agent history)

```
System prompt:
  You are an expert at writing JavaScript data extraction scripts.
  Write a single JavaScript IIFE that extracts the requested data from the current page's DOM.

  Rules:
  - Use document.querySelectorAll / querySelector with robust CSS selectors
  - Return a JSON-serializable value (object or array)
  - Handle null/missing elements with fallback values
  - Use .textContent.trim() for text, .getAttribute() for attributes
  - Do NOT use external libraries — vanilla JS only
  - The script runs on the full live DOM, not just the HTML shown below
  - Wrap everything in (function(){ ... })()

User message:
  <query>Extract all products with name, price, and URL</query>
  <output_schema>{"type":"object","properties":{"products":{"type":"array","items":...}}}</output_schema>
  <html_structure>
  [truncated clean HTML from HTMLSerializer — enough to see DOM patterns]
  </html_structure>
```

### Files Created/Modified

- **`browser_use/tools/extraction/js_codegen.py`** — New file: core logic

```python
class JSExtractionService:
    """Generates and executes JS extraction scripts via a blocking LLM call."""

    async def extract(
        self,
        query: str,
        browser_session: BrowserSession,
        llm: BaseChatModel,
        output_schema: dict | None = None,
        css_selector: str | None = None,
    ) -> ExtractionResult:
        # 1. Get HTML structure
        html = await self._get_html_for_llm(browser_session, css_selector)
        # 2. Generate JS script via LLM
        js_script = await self._generate_script(llm, html, query, output_schema)
        # 3. Execute via CDP
        raw_result = await self._execute_script(browser_session, js_script)
        # 4. Validate against schema
        validated = self._validate_result(raw_result, output_schema)
        return validated
```

- **`browser_use/tools/views.py`** — New action model:

```python
class ExtractWithScriptAction(BaseModel):
    query: str
    output_schema: dict | None = Field(default=None)
    css_selector: str | None = Field(
        default=None,
        description='CSS selector to narrow extraction to a specific page region'
    )
    extraction_id: str | None = Field(
        default=None,
        description='Reuse a previously generated script on a similar page'
    )
```

- **`browser_use/tools/service.py`** — Register new action:

```python
@self.registry.action(
    """Generate and execute a JS script to extract structured data from the page.
    More reliable than extract for tables, lists, and structured content.
    Produces a reusable extraction script. Use extraction_id to reuse on similar pages.""",
    param_model=ExtractWithScriptAction,
)
async def extract_with_script(
    params: ExtractWithScriptAction,
    browser_session: BrowserSession,
    page_extraction_llm: BaseChatModel,
    file_system: FileSystem,
):
    service = JSExtractionService()
    result = await service.extract(
        query=params.query,
        browser_session=browser_session,
        llm=page_extraction_llm,
        output_schema=params.output_schema,
        css_selector=params.css_selector,
    )
    # Return ActionResult (same flow as existing extract)
    ...
```

- **`browser_use/agent/system_prompts/system_prompt.md`** — Add guidance about when to use `extract_with_script` vs `extract`:

```
- Use extract_with_script for structured data (tables, product lists, search results)
  and when you need to extract the same type of data from multiple similar pages.
- Use extract for prose content, summaries, or when you need semantic understanding.
```

### Key Implementation Details

**Getting HTML for the LLM:**
- Reuse `HTMLSerializer` from `browser_use/dom/serializer/html_serializer.py` — already removes scripts, styles, base64 images
- When `css_selector` provided: use CDP `Runtime.evaluate` to get `document.querySelector(selector).outerHTML` (smaller, targeted)
- Truncate to 100K chars — the LLM only needs to see enough structure to write selectors. The JS runs on the full live DOM.

**Executing the JS script:**
- Extract `evaluate()` logic from `code_use/namespace.py:175-253` into a shared utility (or import it)
- Use `cdp_client.send.Runtime.evaluate(params={'expression': js, 'returnByValue': True, 'awaitPromise': True})`
- Handle `EvaluateError` — if JS fails, retry with error message in LLM prompt

**Context isolation:**
- The sub-agent's LLM call uses `page_extraction_llm.ainvoke(messages)` with its own messages list
- These messages never enter the main agent's `MessageManager` — only the `ActionResult` does
- The main agent sees: `extracted_content = "{ structured JSON }"` and `metadata = {extraction_id, js_script}`

### Testing (`tests/ci/test_js_extraction.py`)

1. `pytest-httpserver` serves a product table HTML. `JSExtractionService.extract()` with mock LLM that returns JS like `(function(){return Array.from(document.querySelectorAll('tr')).map(...)})()`. Verify JSON result matches expected.
2. With `css_selector`: serve page with `div#target` containing data. Verify only that section's HTML sent to LLM.
3. JS execution failure → retry with error feedback in prompt → success on second try.
4. Schema validation: result doesn't match schema → validation error in ExtractionResult.
5. Large page: HTML > 100K chars, verify truncation applied but JS still runs on full DOM.
6. Backward compat: existing `extract` action unaffected.

---

## PR 3: Structure-Aware Content Chunking

**Goal**: Improve the markdown extraction path. Replace naive char-based truncation (service.py:726-741) with structural chunking that never splits tables/code blocks/list items.

### Files Modified

- **`browser_use/dom/markdown_extractor.py`** — Add `chunk_markdown_by_structure(content, max_chunk_size, overlap_lines) -> list[MarkdownChunk]`
- **`browser_use/dom/views.py`** — Add `MarkdownChunk` dataclass
- **`browser_use/tools/service.py`** — Replace truncation block (lines 726-744) with chunking call
- **`browser_use/dom/serializer/html_serializer.py`** — Table normalization (synthesize missing `<thead>`, pad short rows)

### Chunking Algorithm

Split priority: headers > paragraphs > table row boundaries > list items > sentences. Never split inside: table rows, code blocks, list continuations. `overlap_lines` carries context (e.g. column headers) across chunk boundaries.

### Testing (`tests/ci/test_content_chunking.py`)

1. Table not split mid-row
2. Code blocks not split
3. Header boundaries respected
4. End-to-end: 200-row HTML table → chunk → verify complete rows

---

## PR 4: Extraction Strategy Cache

**Goal**: Cache JS scripts and extraction strategies for reuse across similar pages. When the agent visits page 2 of products, skip the LLM call — rerun the cached JS script from page 1.

### Files Created/Modified

- **`browser_use/tools/extraction/cache.py`** — New:

```python
class ExtractionStrategy(BaseModel):
    id: str = Field(default_factory=uuid7str)
    url_pattern: str          # glob, e.g. "https://example.com/products/*"
    js_script: str | None     # cached JS from extract_with_script
    css_selector: str | None
    output_schema: dict | None
    query_template: str
    success_count: int = 0
    failure_count: int = 0

class ExtractionCache:
    def register(strategy) -> str: ...
    def get(extraction_id) -> ExtractionStrategy | None: ...
    def find_matching(url) -> ExtractionStrategy | None: ...
```

- **`browser_use/tools/extraction/js_codegen.py`** — When `extraction_id` provided, look up cached strategy, skip LLM call, execute cached JS directly. If cached JS fails (DOM changed), regenerate once.
- **`browser_use/tools/service.py`** — After successful `extract_with_script`, auto-register strategy in cache. Return `extraction_id` in `ActionResult.metadata`.
- **`browser_use/agent/service.py`** — Add `ExtractionCache` instance to Agent
- **`browser_use/tools/registry/service.py`** (line 62-71) — Add `extraction_cache: ExtractionCache` to special param types

### Testing (`tests/ci/test_extraction_cache.py`)

1. Register/get round-trip
2. URL pattern matching
3. Cached JS reuse: second call with `extraction_id` skips LLM
4. Cache invalidation: cached JS fails → regeneration
5. Success/failure counting

---

## PR 5: Error Recovery + Multi-Page Aggregation

**Goal**: Retry logic for both extraction paths. Aggregation layer that merges results across multiple `extract_with_script` calls (e.g. paginated product listings).

### Files Created/Modified

- **`browser_use/tools/extraction/js_codegen.py`** — Retry: JS execution error → re-prompt LLM with error. Validation error → re-prompt with schema hint. Timeout → retry once.
- **`browser_use/tools/extraction/aggregator.py`** — New: `ExtractionAggregator` — maintains running result collection keyed by `extraction_id`. Methods: `add(result)`, `aggregate() -> ExtractionResult`, `summary -> str`. Deduplication via exact field match.
- **`browser_use/tools/extraction/views.py`** — `ExtractionError` (error_type, retries_exhausted, fallback_used), `ExtractionRetryConfig`
- **`browser_use/tools/service.py`** — Wire aggregator into `extract_with_script` handler

### Aggregation Flow

1. Agent: `extract_with_script(query="Get products")` on page 1 → 20 products, returns `extraction_id="abc"`
2. Agent navigates to page 2: `extract_with_script(extraction_id="abc")` → runs cached JS, adds to aggregator
3. `ActionResult.long_term_memory`: "40 unique products from 2 pages. extraction_id=abc"
4. Agent calls `done` with aggregate

### Testing (`tests/ci/test_extraction_recovery.py`)

1. JS error → retry with error feedback → success
2. Schema validation failure → retry → success
3. Aggregation: 3 pages with same extraction_id → deduplicated merge
4. Aggregate summary in `long_term_memory`

---

## New File Structure

```
browser_use/tools/extraction/
    __init__.py           # PR 1
    schema_utils.py       # PR 1: JSON Schema ↔ Pydantic model conversion
    views.py              # PR 1+: ExtractionResult, ExtractionConfig, errors
    js_codegen.py         # PR 2: JSExtractionService (generate + execute JS)
    cache.py              # PR 4: ExtractionCache, ExtractionStrategy
    aggregator.py         # PR 5: ExtractionAggregator
```

## Critical Files

| File | PRs | What Changes |
|------|-----|-------------|
| `browser_use/tools/views.py` | 1, 2 | Add `output_schema` to ExtractAction, new ExtractWithScriptAction |
| `browser_use/tools/service.py` | 1, 2, 3, 4, 5 | Schema branching in extract, new extract_with_script registration |
| `browser_use/dom/markdown_extractor.py` | 3 | Add chunk_markdown_by_structure |
| `browser_use/agent/system_prompts/system_prompt.md` | 2 | Guidance for extract vs extract_with_script |
| `browser_use/tools/registry/service.py` | 4 | Add extraction_cache to special params |
| `browser_use/agent/service.py` | 4 | Add ExtractionCache to Agent |
| `browser_use/agent/views.py` | 1 | Optional ExtractionConfig in AgentSettings |

## Verification

```bash
uv run pytest -vxs tests/ci/test_structured_extraction.py
uv run pytest -vxs tests/ci/test_js_extraction.py
uv run pytest -vxs tests/ci/test_content_chunking.py
uv run pytest -vxs tests/ci/test_extraction_cache.py
uv run pytest -vxs tests/ci/test_extraction_recovery.py
uv run pytest -vxs tests/ci/  # full suite — no regressions
uv run pyright
uv run ruff check --fix && uv run ruff format
```
