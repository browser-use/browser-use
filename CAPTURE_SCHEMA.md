# Trajectory capture — event schema v4

Element capture for trajectory recording lives in `browser_use/tools/registry/capture.py`
and is wired into `Registry.execute_action`. For every index-bearing action it writes an
`event_start` / `event_end` pair into a per-task JSONL log (`browser_use/logger/`).

Capture is **opt-in and best-effort**: nothing is written unless the runner registers a
logger (`register_logger(task_id, dir)` + `set_current_task(task_id)`), and no capture
failure ever breaks the action.

## Event shape

```jsonc
{"event": "event_start", "step": 3, "tool": "click",
 "action": {"index": 91, "element": { /* element record, below */ }},
 "timestamp": 1781241012.23}
{"event": "event_end", "step": 3, "tool": "click", "status": "success", "timestamp": ...}
```

## Element record

Legacy keys keep their 12_6 shape so existing consumers (web-knowledge `combine_logs`)
keep working. After **retargeting**, legacy keys describe the *interaction target* (the
element selectors should resolve to), not the raw CDP hit node.

| key | notes |
|---|---|
| `element_name`, `tag_name`, `role`, `attributes`, `xpath`, `text_content`, `container_node`, `children_node`, `is_clickable`, `is_scrollable`, `description` | legacy, 12_6-compatible |
| `node_name` | AX name, **backfilled** from anchor/first text line when the AX name is missing. An empty-string AX name is preserved as `''` (never collapsed to `null` — `load_jsonl` drops `null`) |
| `capture_version` | `4` |
| `text_full` / `text_first_line` | un-truncated-ish text (200 chars) and its first line; `text_content` stays 50-char for compatibility |
| `placeholder` | input placeholder, recorded separately instead of masquerading as text |
| `ax` | `{role, name, duplicates_in_view}` — duplicates = how many selector-map elements share (role, name); `1` means a role+name locator is unambiguous |
| `retarget` | `{applied, reason, levels}` — reason ∈ `interactive-tag, js-listener, role-attr, on-attr, tabindex, ax-role, ax-state, cursor-boundary` |
| `hit_node` | original CDP hit node summary, present only when retargeting moved the target |
| `anchor` | best text-bearing descendant (heading or title line) — the identity anchor |
| `selector_candidates` | see below |
| `scope_verification` | `{scope_css, scope_found, scope_contains_target}` for the container-derived scope |
| `ancestors` | compact `{tag, stable_attrs?, data_attrs?}` chain above the target (≤8 levels) |
| `container_node.heading_text` | first text line of the container — lets downstream emit text-disambiguated scopes |
| `container_node.scope_css` | suggested scope selector (landmark tag / stable attrs / stable role), `null` when none is safe |

## Selector candidates

Each candidate is generated at capture time and **verified against the live page** over
CDP with `this` bound to the exact node the agent used. Verification mirrors the tour
SDK's resolution algorithm (strict trimmed `textContent` equality, innermost tie-break).

```jsonc
{"kind": "scoped",
 "css": "button[type=\"button\"]",
 "text": "...",                                  // optional text filter
 "scope": {"css": "article", "text": "Notification"},  // optional, kind=scoped only
 "verify": {
   "count": 1,            // matches on the page (within scope for kind=scoped)
   "relation": "exact",   // what the SDK would pick: exact | descendant | ancestor | other | none
   "self_index": 0,       // where the recorded node sits in the match list (-1 = absent)
   "scope_count": 1,      // kind=scoped: containers matching {css, text}
   "scoped": {...}        // non-scoped kinds: same result re-run inside scope_css
 }}
```

Kinds, in generation order: `data-attrs`, `data-attrs-bare`, `compound`, `compound-tag`,
`structural`, `text`, `aria`, `href`, `scoped`, `structural-broad`, `tag`.
`text` candidates are encoded as `css: "*"` + `text` (the SDK `text:` form).

Ranking guidance for downstream: a candidate with `relation: "exact"` and `count: 1` is a
verified unique selector. `relation: "other"` is dead on arrival regardless of how
specific the CSS looks. `relation: "descendant"` (e.g. `text:` hitting the `<h2>` inside
a clickable card) needs closest-clickable resolution on the SDK side.

`scope: {css, text}` semantics (the phase-2 SDK contract): take all elements matching
`scope.css`, keep those whose first trimmed text line equals `scope.text`, use the first
as the query root for `css`/`text`.
