# Codexification Baseline Status

Phase 0 status for `CODEXIFY_IMPLEMENTATION_PLAN.md`.

This is a working baseline note, not a full test report. The goal is to capture enough current behavior and existing coverage to start the runtime refactor safely.

## Current Coverage Map

- DOM serializer and selector map:
  - `tests/ci/browser/test_dom_serializer.py`
  - Covers cleaned DOM representation, `selector_map`, shadow DOM, same-origin iframe content, iframe tags, and click execution through indexed elements.
- Multi-action guards:
  - `tests/ci/test_multi_act_guards.py`
  - Covers `terminates_sequence` metadata, static sequence termination, URL-change guard, focus-change guard, and safe chained inputs.
- Coordinate clicking:
  - `tests/ci/test_coordinate_clicking.py`
  - Covers click schema switching, coordinate-capable model detection, and externally passed `Tools`.
- Tabs:
  - `tests/ci/browser/test_tabs.py`
  - Covers creating, switching, closing, background tabs, and completion after tab operations.
- Screenshots:
  - `tests/ci/browser/test_screenshot.py`
  - `tests/ci/test_screenshot_exclusion.py`
- Downloads, uploads, and security:
  - `tests/ci/security/test_download_filename_sanitization.py`
  - `tests/ci/security/test_upload_file_containment.py`
  - Related upload behavior appears in CLI and tool tests.
- Browser interactions:
  - `tests/ci/interactions/test_autocomplete_interaction.py`
  - `tests/ci/interactions/test_dropdown_aria_menus.py`
  - `tests/ci/interactions/test_dropdown_native.py`
  - `tests/ci/interactions/test_radio_buttons.py`
- Extraction and markdown:
  - `tests/ci/test_structured_extraction.py`
  - `tests/ci/test_markdown_extractor.py`
  - `tests/ci/test_markdown_chunking.py`
  - `tests/ci/test_extract_images.py`
- Tool registry and action parameter injection:
  - `tests/ci/infrastructure/test_registry_core.py`
  - `tests/ci/infrastructure/test_registry_validation.py`
  - `tests/ci/infrastructure/test_registry_action_parameter_injection.py`
- Task evals:
  - `tests/ci/evaluate_tasks.py`
  - `tests/agent_tasks/*.yaml`
  - Requires `BROWSER_USE_API_KEY` and `GOOGLE_API_KEY` for meaningful non-skipped results.

## Baseline Commands Run

```bash
uv run pytest tests/ci/test_coordinate_clicking.py tests/ci/test_multi_act_guards.py::TestTerminatesSequenceMetadata -q
```

Result: `42 passed in 0.08s`.

```bash
uv run pytest tests/ci/test_multi_act_guards.py::TestRuntimeGuard::test_click_link_aborts_remaining -q
```

Result: `1 passed in 12.36s`.

Notes:

- Verified real-browser `multi_act` runtime guard.
- Click on link navigated from `/page_a` to `/page_b`.
- Remaining queued actions were skipped after page change.
- Fixture produced expected favicon 500s and a page readiness timeout warning.

```bash
uv run pytest tests/ci/browser/test_dom_serializer.py::TestDOMSerializer::test_dom_serializer_with_shadow_dom_and_iframes -q
```

Result: `1 passed in 12.25s`.

Notes:

- Selector map contained 10 interactive elements.
- Serialized DOM indices all mapped back into `selector_map`.
- Regular DOM, shadow DOM, same-origin iframe content, and iframe tags were represented.
- Clicks succeeded on regular DOM button, shadow DOM button, and same-origin iframe button.
- Page click counter reached `3`.

## Next Baseline Work

- Run broader browser baseline:

```bash
uv run pytest tests/ci/test_multi_act_guards.py tests/ci/browser/test_tabs.py tests/ci/browser/test_screenshot.py -q
```

- Run interaction baseline:

```bash
uv run pytest tests/ci/interactions -q
```

- Run security/file baseline:

```bash
uv run pytest tests/ci/security/test_download_filename_sanitization.py tests/ci/security/test_upload_file_containment.py -q
```

- Run task eval baseline when API keys are available:

```bash
uv run python tests/ci/evaluate_tasks.py
```

## Phase 0 Assessment

- Current targeted baseline is healthy.
- Existing tests already cover many critical behaviors we need to preserve.
- Full baseline is not complete yet: broader browser tests, interaction tests, security/file tests, and real task evals still need to be run or recorded.
