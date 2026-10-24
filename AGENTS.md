# Development rules

Browser Use uses Pi as its only planning engine.
Python provides the public client, CLI, and provider adapters.

- Use `uv` for Python dependencies and commands.
- Use `npm ci` for the pinned JavaScript dependencies.
- Keep exact model IDs and never substitute another model.
- Accept new model IDs through existing provider transports.
- Keep unknown pricing as `null`.
- Keep Cloud as the default browser.
- Preserve explicit Chrome, Chromium, and CDP connections.
- Preserve borrowed browsers and unrelated tabs during cleanup.
- Keep OpenAI and Anthropic adapters on the shared Pi browser helper.
- Do not restore the old Python planner or Rust beta.
- Keep generated engine assets outside Git.
- Serialize builds because each build replaces `dist/`.
- Run `npm run check` and the relevant existing tests.
- Run `uv run pre-commit run --all-files` before each PR.
- Build Python assets with `npm run build:python` before wheel checks.
- Keep telemetry free of tasks, scripts, outputs, credentials, and raw endpoints.
- Treat host code and bash as trusted application capabilities.
- Enforce security restrictions in the browser or a trusted gateway.

Read `docs/migration.md`, `docs/enterprise.md`, and `docs/telemetry.md` for scope and limits.
This branch contains an unpublished major-version draft.
Do not publish packages or create release tags from this branch.
