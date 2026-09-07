# Explicit screenshot delivery

BrowserCode attaches successful `Page.captureScreenshot` responses to the model. The earlier bu-pi worker attached only its global `screenshot()` helper. A model could therefore save `page.screenshot()` to a file without receiving the image as vision.

The first reliability cohort exposed this on Luna task 040: one global screenshot call, one saved mobile JPEG and no image-read calls. The judge saw severe mobile text reflow absent from the agent's audit. This is a documented delivery gap; supplying the image is not proof that the model will interpret it correctly.

## Change

A passive CDP result tap now captures explicitly requested screenshots on the worker connection. Page helpers, other tabs and raw CDP share the same path. File bytes and command results remain available. The global helper attaches once. No extra browser action or screenshot request is introduced.

The tap captures its callback at command dispatch. Each cell closes its own capture scope; late responses cannot enter the next cell. Reconnect reinstalls the current scope on the new connection. Attachments remain bounded to four images per cell and 8 MB per image; omitted images receive an explicit warning. The separate recording/eval observer is unchanged.

## Proof

The full Node 22.23.2 suite passes **68/68** tests. New cases exercise JPEG/PNG/WebP, direct page and other-tab captures, raw root/session CDP, exact saved-byte equality, one attachment per capture, overflow, failed-cell application evidence, reconnect and dispatch-scoped passive response taps. A scripted model receives the image after the exact saved-screenshot pattern that failed in the trace. These tests use real local Chrome and no paid inference.

The earlier 64-test pass covered the reliability runtime plus provider-budget failure cases. The 68-test result includes this screenshot change. Six Python integration tests, strict TypeScript checks and the docs build also pass. The npm tarball installs into a separate application and passes a Node 22.23.2 ESM import and strict TypeScript consumer check. A focused follow-up assertion verifies the other tab’s captured PNG is exactly 390 × 844; the SDK runtime is unchanged. Full benchmark results belong to the separately frozen runtime SHA.

## Compatibility and measurement

Inside the worker, explicit captures now produce additional image attachments. This intentionally changes model input and may change context usage, cost and behavior. Standalone Page calls still return bytes. Existing profiles, files, transcripts and customer deployments are not migrated. Pin the preceding commit to roll back.

The first reliability cohorts evaluated `a7fe3d46625ec0d3b5ac1d2022d08a5a9b03163d`. Their outcomes cannot be attributed to this later fix. The new frozen SHA was evaluated on both complete task sets; [results](./vision-results.md) retain every outcome without substituting individual retries. No benchmark-specific selectors, expected answers or task IDs enter the runtime prompt.

## TypeScript consumer configuration

The final package passes an ESM import and strict `NodeNext` consumer check with `skipLibCheck: true`, matching this repository's compiler configuration. An invalid `compaction: 'yes'` option is still rejected. Full dependency declaration checking with `skipLibCheck: false` fails: Pi 0.85.1's generated declarations omit JSON import attributes, and Google's declarations reference an unavailable optional MCP type. This is an upstream typing compatibility limitation, not a successful full declaration check. It does not change the evaluated runtime bytes. The failed diagnostic and the supported-configuration checks are retained with the local package verification.
