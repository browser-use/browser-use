# Bound screenshot previews

The first fresh confirmation exposed a concrete transport failure in the frozen Luna reference `b430a91`: task `bub2-002` returned a full-page JPEG measuring 1425 × 21,637 pixels. It was only 387,728 bytes, below the worker's 8 MB attachment guard. Its 32-pixel patch count is `ceil(1425/32) × ceil(21637/32) = 30,465`. The provider rejected the next inference request because one image exceeded its 30,000-patch limit.

The trace, downloaded original image, and provider error agree on this mechanism. No compaction occurred. The outcome remains an assigned runner zero without an actual judgment in evaluation `228eee8b-4e78-4978-b3e5-0f718b4c4930`, [execution 34185578184](https://github.com/browser-use/new-eval-platform/actions/runs/34185578184). No outcome is replaced.

## Change

Check screenshot dimensions before native attachment. Normal viewport captures retain their exact bytes and skip image decoding. Oversized previews use the existing upstream Pi image-resize helper, loaded only when needed, with its 2000 × 2000 and 4.5 MiB base64 limits. Original CDP results and saved artifacts are untouched. This adds no package dependency, browser recapture, or action replay.

Every resized preview carries its original and displayed dimensions plus a warning to request readable viewport/crop detail. Unknown dimensions, over-50-megapixel images, and failed processing are omitted with an explicit warning, while valid later captures survive. The existing whole-cell deadline and cancellation boundary contain processing hangs. No credential, profile, history, browser-ownership, result-schema, or legacy Python Browser Use behavior changes.

## Limits

The real failing JPEG can be resized locally to 132 × 2000 in roughly 1.25 seconds, but that preview is too narrow to read ordinary text. Resizing prevents this transport rejection; it does not prove a visual judgment or complete the original task. Original files and explicit crops remain necessary. Different providers may enforce additional limits.

Local Chrome also returned an empty payload for a 22,000-pixel-tall WebP capture. The new path omitted that payload with a warning. A valid 6000-pixel WebP exercises resizing separately.

The Python bundle initially omitted the image because the upstream WASM asset was absent. Its build now copies that pinned asset beside the bundled JavaScript and includes it in the wheel. The bundle defines its own directory explicitly so the image backend can locate the asset. Python integration tests exercise real Chrome capture, original file preservation, and the resized native image in the next local fixture-provider request.

Final local checks passed: 87 Node tests, typecheck, documentation build, and all seven Python integration tests against both the source bundle and the unpacked built wheel. The wheel's WASM bytes match the pinned dependency asset. These checks use real local Chrome and scripted/local SSE provider responses; they do not measure benchmark quality. [Numeric diagnosis and validation](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/image-limits.json).

The frozen `f41c5b7` confirmation arms do not contain this change. The image fix is a separate next candidate, SDK `a4a0ba2c69a3c4ee5d2a0243734157fef7068fd2`.

## Remote package smoke

A 32-turn, 600-second diagnostic on `bub2-002` completed successfully at this exact SDK: [execution 34187516720](https://github.com/browser-use/new-eval-platform/actions/runs/34187516720), evaluation `26892b16-1c1c-4a3e-bcb5-138485904012`. It produced a real **20/100** Findings judgment, with 31 steps, 351.064 seconds of recorded agent execution, and $0.04605014 recorded agent inference cost. Its final response explicitly says the capture set is incomplete and makes no verified-deliverable claim. No task deliverable files were produced.

The downloaded artifact contains 27 validated PNG evidence images. The separate eval observer recorded three screenshot errors; the SDK recorded no cleanup errors, compactions, or inference retries. An independent Cloud API read confirmed that this smoke's browser stopped.

This attempt produced no native model-image attachments or resize notices. Consequently it verifies package/inference/browser/evidence integration, **not remote execution of the resize mechanism**. The real-Chrome local tests remain the mechanism proof. No outcome replaces the failed reference task or enters either full confirmation cohort. There is no benchmark improvement claim for this image experiment yet. [Exact inputs and numeric smoke evidence](https://github.com/browser-use/bu-pi/blob/codex/raw-cdp-k7m2/evidence/image-limits-smoke.json).
