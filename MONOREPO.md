# Monorepo

One repo for Browser Use in both languages. Python stays at the root, exactly where PyPI, Docker, `pip install git+...`
and every open PR expect it. Browser Use JS (formerly `browser-use/browser-use-pi`) lives in `js/` with its full history.

## Layout

```
browser-use/
├── browser_use/ tests/ examples/ docker/ scripts/   Python (unchanged)
├── pyproject.toml uv.lock Dockerfile server.json    Python packaging (unchanged)
├── skills/ static/ AGENTS.md                        shared
├── js/                                              Browser Use JS (npm @browser_use/core)
│   ├── src/ test/ examples/ docs/ eval/
│   ├── package.json package-lock.json tsconfig*.json
│   └── .history/browser-use-pi-commit-map.tsv       old Pi SHA -> new SHA
└── .github/workflows/
    ├── test.yaml package.yaml lint.yml docker.yml publish.yml install-script.yml   Python
    └── js.yml publish-js.yml                                                       JS
```

Python tooling ignores `js/`: pre-commit `exclude: ^js/`, ruff `extend-exclude`, `.dockerignore`. The wheel and sdist
contain the same files as before. The root `.gitignore` ignores `*.json` and `*.txt`; `js/.gitignore` negates both, then
re-ignores the root's secret files (`credentials.json`, `cookies.json`, `token.json`, ...).

## CI

- `lint.yml` runs on every PR (its checks are required by branch protection; a path filter would block JS-only PRs).
- `test.yaml`, `package.yaml`, `docker.yml` ignore `js/**` changes.
- `js.yml` runs only when `js/**` or itself changes: Node 22.19 and 24 run `npm ci`, build, check, `format:check` and
  the tests that need no browser. A separate `chrome` job runs the full suite; it is not a required check yet.

## Releases and tags

| | Python | JS |
|---|---|---|
| tag | `X.Y.Z`, `X.Y.ZrcN` (starts with a digit) | `js-vX.Y.Z`, `js-vX.Y.Z-rc.N` |
| workflow | `publish.yml` (skips `js-*`) | `publish-js.yml` (skips everything else) |
| gate | `release` environment approval | same `release` environment |
| registry | PyPI trusted publishing | npm trusted publishing + provenance; `-rc.N` goes to dist-tag `next` |
| Docker | yes (`docker.yml`) | no (`docker.yml` skips `js-*`) |

Push-tag filters in the Python workflows are `'[0-9]*'`, so a `js-v*` tag runs no Python CI.

JS release:

1. Bump `version` in `js/package.json`, merge.
2. `gh release create js-v0.2.0 --target main --latest=false` (`--latest=false` keeps Python as the repo's Latest release).
3. Approve the `release` environment. `publish-js.yml` checks the tag equals `js-v<version>` and is the checked-out
   commit, then builds, checks and runs `npm publish --provenance --access public`.

Versions are independent. JS reaches 1.0.0 only when matched evals show parity with Python 1.0.x.

## Pulling later Pi commits

`js/` currently holds Pi `parity/py-1.0.6` (a8fdf9c): Pi `main` 4cbc951 plus the parity stack browser-use/browser-use-pi#37
-> #39 -> #40 -> #41 (42 commits). The import is deterministic (same input gives the same SHAs), so later Pi commits come in by
re-running the filter and merging (use the Pi branch name in place of `main`):

```bash
rm -rf /tmp/pi-js && git clone -q https://github.com/browser-use/browser-use-pi /tmp/pi-js
printf '%s\n' 'regex:(^|[^/\w])#(\d+)==>\1browser-use/browser-use-pi#\2' > /tmp/pi-msg.txt
(cd /tmp/pi-js && uvx --from git-filter-repo git-filter-repo --force --to-subdirectory-filter js --replace-message /tmp/pi-msg.txt)
git fetch /tmp/pi-js main:import/pi-js
git merge --no-ff import/pi-js -m "Pull browser-use-pi <sha> into js/"
M=js/.history/browser-use-pi-commit-map.tsv
tail -n +2 /tmp/pi-js/.git/filter-repo/commit-map | grep -vFxf <(tail -n +2 "$M") >> "$M"   # append new rows only
```

Already-imported commits keep their SHAs, so only the new ones merge. Once Pi is archived, JS work happens here.

## Prompt sync (phase 2)

The system prompts (`browser_use/agent/prompt.py`, `js/src/prompt.ts`) share only 2 of 24 paragraphs today, so they stay
separate until the parity work settles the wording. Then:

- `prompts/system.md` with shared paragraphs and per-language blocks;
- `scripts/sync_prompts.py --check` regenerates both committed prompt files and runs in CI (same pattern as
  `scripts/sync_browser_harness_skill.py --check`);
- every prompt change gets a matched eval in both languages.

## Rollback

- Before merge: close the PR.
- After merge: `git revert -m 1 <import merge>` plus a revert of the wiring commit, then unarchive `browser-use-pi`.
- Nothing is published until someone creates a `js-v*` release; PyPI and Docker are unaffected either way.

## Decisions for Gregor

- **npm name.** `@browser_use/core` (Gregor, 2026-11-17). It is a new package, and npm only lets trusted publishing be
  set on a package that exists, so the first version is published by hand once (see "First npm publish" below); every
  later `js-v*` release publishes from `publish-js.yml`. After it is live, deprecate `@browser_use/pi`:
  `npm deprecate @browser_use/pi "Moved to @browser_use/core"`.
- **npm trusted publisher.** One-time account step: in the npm package settings add a trusted publisher for
  `browser-use/browser-use`, workflow `publish-js.yml`, environment `release`. Until then JS keeps publishing by hand.
- **Archive `browser-use-pi`** after merge, with a README pointer here; move its open issues with `gh issue transfer`.

## First npm publish (one time, by an owner of the @browser_use npm scope)

npm cannot attach a trusted publisher to a package that has never been published, so `@browser_use/core` 0.2.0 goes up
by hand once, from main after this PR merges (npm >= 11.15, account 2FA on):

```bash
git clone --depth 1 https://github.com/browser-use/browser-use /tmp/bu && cd /tmp/bu/js
npm ci && npm publish --access public
npm trust github @browser_use/core --repo browser-use/browser-use --file publish-js.yml --env release --allow-publish
```

Then `gh release create js-v0.2.0 --latest=false` tags it: `publish-js.yml` sees 0.2.0 already on npm and skips. From
0.2.1 on, a `js-vX.Y.Z` release publishes through OIDC with provenance after the `release` environment approval.
