# Third comparison: trace findings

The four full cohorts are still running. This page records selected mechanisms, not an aggregate score or a new acceptance rule. All original outcomes remain in their assigned cohorts.

## First differing Hard pair: a repair replaced good fields

Task `3qsqcq` requests product titles, prices and sellers from an Amazon search page. Reference `769ea14` passes; candidate `29e2b5e` fails. The reference delivers 15 rows. The candidate delivers 56, with four colour/pattern navigation labels in the title column.

The candidate initially extracts titles from headings, but cannot find product links through its assumed heading/link structure. While fixing links, it also changes the title extractor to prefer the first product-link text longer than 20 characters. That can select “+4 other colours/patterns” instead of the product name. The earlier source observation already contained the real title for one corresponding priced card.

The agent inspects the first five and last five records, then the first ten unique records. The bad final titles occur at rows 12, 16, 18 and 24, outside those samples. Its final verification checks counts, page identity and merchant IDs. It never compares changed title fields with its earlier heading observations.

`finish_from_js` then delivers the constructed table unchanged. Both artifacts' final text equals the SDK result text. Neither run has a tool error. This is a model-written extraction error, not a demonstrated transport regression. The candidate openly maps a shared merchant ID to the seller name observed in one buy box; that is different from individually checking 56 offers, but this audit does not establish that the mapping itself is false.

The general problem is **repairing one field while silently degrading another**. A potential mitigation is to preserve verified fields by stable record identity and compare replacements against earlier observations. Nonempty fields and head/tail samples are insufficient validation. The current prompt already asks for field-meaning checks; this trace shows the model did not perform the relevant check.

No site-specific selector, blacklist, row cap or extra model review enters the frozen candidate. One selected loss cannot establish which SDK change caused the model's choice. The reference also chose a smaller output scope, and the live result sets differ. Reassess after the full paired comparison.

[Exact event indices, artifact hashes, manifests and original judgments](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/confirmation3-first-pair.json).
