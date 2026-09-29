# Anthropic integration launch checklist

Keep this branch private until every unchecked item is complete.

## Browser Use side

- [x] Implement the 31 members exported by the current Anthropic browser toolset.
- [x] Keep `BrowserUse` and `Bash` as peer tools in the runner.
- [x] Disable `file_upload` by default.
- [x] Resize screenshots to the API image limit.
- [x] Bound Bash runtime and output and remove ambient credentials.
- [x] Document owned, borrowed, remote CDP, and Browser Use Cloud sessions.
- [x] Run focused tests, Ruff, formatting, compilation, and a borrowed-CDP smoke.
- [ ] Replace the existing `anthropic==0.76.0` dependency with Anthropic's
      confirmed public browser-toolset SDK version.
- [ ] Run `quickstart.py` through the public SDK and launch model.

## Release coordination

- [ ] Confirm the public Python package version and supported Python versions.
- [ ] Confirm the public model name used in the quickstart.
- [ ] Confirm release time, embargo, Anthropic docs URL, and quickstarts URL.
- [ ] Replace placeholders in the launch copy with the Browser Use announcement URL.
- [ ] Push or open a PR only after explicit publication approval.

## Supported file behavior

Local Bash and a local browser share a filesystem. With a remote browser, an
upload succeeds only when the file already exists on the browser host or the
application supplies a `document_resolver` that stages approved documents
there. Cross-host upload/download transport is a follow-up and is not claimed
by this launch branch.
