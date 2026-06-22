---
name: kafcade
description: >
  Multi-project DevFlow agent cascade. Auto-detects project type, CI stack,
  and deploy path from local config (BLUEPRINT.md, package.json, netlify.toml,
  vercel.json, pyproject.toml, fly.toml). Spawns focused subagents per step.
  Triggers on "kafcade", "kc B", "kc P", "kc D", "kc CI", "kc Im", "kc E",
  "kc C", "kc Bl", "kc I", "KafCade", or "kc full". KafCa mode always ON.
  Evolved by EvoMetaClaw v2.0 from mooc-designer session signals 2026-06-15.
---

# KafCade — Cascaded DevFlow Agents
## Version 2.0 · Multi-Project · KafCa ON · RRSS

Wraps DevFlow commands in project-aware subagents. Auto-detects project type,
CI stack, and deploy path from local config files. KafCa mode always active.

---

## PROJECT AUTO-DETECTION (run at start of every session)

```
Step 1 — Read in order (first found wins for each field):
  CLAUDE.md → BLUEPRINT.md → package.json → pyproject.toml → vercel.json → netlify.toml → fly.toml

Step 2 — Derive PROJECT_SNAPSHOT:
  name:      BLUEPRINT.md h1 title | package.json "name" | directory name
  type:      static | python-api | node-api | nextjs | docker
  language:  python | javascript | typescript | none
  repo:      git remote get-url origin
  live_url:  BLUEPRINT.md "Live site:" | vercel.json → vercel URL | netlify.toml → netlify URL
  blueprint: BLUEPRINT.md path (for roadmap 🔲 items)

Step 3 — Derive CI_STACK:
  if pyproject.toml   → ["uv run ruff format", "uv run ruff check", "uv run ty check", "uv run pytest"]
  if package.json     → ["npm run lint", "npm run typecheck", "npm test"]  (or pnpm/yarn/vitest)
  if netlify.toml (static) → []  (no build CI — validate HTML manually if htmlhint available)
  if none             → warn user, skip CI gate

Step 4 — Derive DEPLOY_CMD:
  if netlify.toml     → "netlify deploy --prod --dir <publish>"  (read publish= from toml)
  if vercel.json      → "vercel --prod"
  if fly.toml         → "fly deploy"
  if railway.*        → "railway up"
  else                → "git push origin main"  (CD-on-push / GitHub Pages)

Step 5 — Derive VERIFY_CMD:
  if static (netlify) → "curl -s -o /dev/null -w '%{http_code}' <live_url>"  (expect 200)
  if API (vercel/fly) → "curl <live_url>/health"
  else                → "echo deploy triggered"
```

Embed PROJECT_SNAPSHOT at the top of every subagent prompt.

---

## KNOWN PROJECT REGISTRY

| Project | Type | CI | Deploy | Live URL |
|---------|------|----|--------|----------|
| `mooc-designer` | static | none | `netlify deploy --prod --dir site` | `stately-bublanina-0aa129.netlify.app` |
| `free-claude-code` | python-api | uv/ruff/ty/pytest | `vercel --prod` | `free-claude-code-main-ebon.vercel.app` |
| `Nuclear_Energy_MOOC` | node (Vite) | `npm run build` | kimi.page (manual) | `vstcro6r5df54.kimi.page` |

---

## COMMANDS

### `kc B` — Build
Spawn: `general-purpose` agent

```
[PROJECT_SNAPSHOT]

Task: Implement the next 🔲 roadmap item from BLUEPRINT.md.

Steps:
1. Read BLUEPRINT.md — find first 🔲 item.
2. Read relevant source files (never guess contents).
3. Plan: files to create/modify, dependencies, security.
4. Implement: minimal KafCa-style. No extra abstractions.
5. Run CI_STACK (if any). Fix failures before stopping.
6. Report: [Files Changed] [Logic Added] [Verification] [Risks]

Gates (block if any fail):
- No hardcoded secrets or API keys
- Async operations error-handled at boundaries
- No type: ignore suppressions
- New functions covered by tests (if test suite exists)
```

---

### `kc I` — Integrate
Spawn: `general-purpose` agent

```
[PROJECT_SNAPSHOT]

Task: Sync code ↔ docs ↔ state.

Steps:
1. git diff HEAD — summarise changes since last commit.
2. Check new functions/modules have doc comments.
3. Mark completed items ✅ in BLUEPRINT.md.
4. Flag technical debt or deferred items.
5. Update CLAUDE.md if architectural facts changed.
6. Output: what changed · in sync · needs attention.

Do not add features. Do not run CI.
```

---

### `kc Im` — Improve
Spawn: `general-purpose` agent

```
[PROJECT_SNAPSHOT]

Task: Improve existing code quality — no new behaviour.

Priority:
  P0 Security   : XSS (innerHTML + user input), exposed secrets, eval() → fix immediately
  P1 Correctness: null-deref, race conditions, off-by-one
  P2 Performance: scroll/resize listeners missing {passive:true}; redundant re-renders
  P3 Quality    : dead code, magic numbers, duplicated logic, naming inconsistency
                  check global function name shadows (scrollTo, open, print, fetch, etc.)
  P4 Style      : unused imports, stale comments, trailing whitespace

Steps:
1. grep: innerHTML =, eval(, document.write(, hardcoded tokens, localStorage.*secret
2. Check scroll/resize/wheel listeners missing {passive:true}
3. Check function names shadow browser globals
4. Apply in priority order. No new features.
5. Run CI_STACK. Report: improvements · deferred · measurable delta.
```

---

### `kc E` — Evaluate
Spawn: `Explore` agent (read-only)

```
[PROJECT_SNAPSHOT]

Task: Structured audit report.

Checks:
- grep: innerHTML =, eval(, document.write(, localStorage.*secret, hardcoded tokens
- Scroll/resize listeners missing {passive:true}
- Global function name shadows (scrollTo, open, print, fetch, etc.)
- Async functions without try/catch at boundary
- External API calls without timeout/abort handling
- type: ignore (Python) / @ts-ignore (TS) suppressions
- DRY: duplicated logic across files
- Dead code: defined but never called
- BLUEPRINT.md version vs codebase reality
- OG/Twitter meta present (web projects)
- No console.log of sensitive data

Output (exact):
## Evaluation Report — [project] — [date]

### Security (P0)
[finding: file:line — description — severity — fix]

### Correctness (P1)
[...]

### Performance (P2)
[...]

### Quality/Consistency (P3–P4)
[...]

### Score
Security: X/10 · Correctness: X/10 · Performance: X/10 · Quality: X/10
```

---

### `kc C` — Consolidate
Spawn: `general-purpose` agent

```
[PROJECT_SNAPSHOT]

Task: Remove redundancy, dead code, organisational debt.

Steps:
1. git status — list untracked; add to .gitignore if appropriate.
2. Find duplicate functions/logic — extract to shared helpers.
3. Remove functions never called (verify with grep first).
4. .gitignore must cover: .venv/ .env *.log __pycache__/ dist/ .ruff_cache/
   Static sites also: *.backup.html *.bak mooc-designer-img*.png (if not in site/)
5. Verify file layout matches BLUEPRINT.md manifest.
6. Run CI_STACK if changes made.
7. Report: removed/merged · line delta · files reorganised.
```

---

### `kc Bl` — Blueprint
Spawn: `general-purpose` agent

```
[PROJECT_SNAPSHOT]

Task: Update BLUEPRINT.md to reflect current reality.

Steps:
1. Read BLUEPRINT.md and source files.
2. Diff blueprint vs code:
   - Version matches package.json / pyproject.toml (if any)
   - All shipped items marked ✅ in Roadmap table
   - File manifest reflects actual files
   - Live URL is current
3. Add changelog entry for current version.
4. Update version + date in header.
5. Preserve all historical changelogs — never delete.

Do not change source code.
```

---

### `kc P` — Push (inline)

```bash
git status
git diff --stat HEAD
# Stage specific files — never git add -A or git add .
# Commit via HEREDOC:
git commit -m "$(cat <<'EOF'
type(scope): subject ≤72 chars

- bullet: what + why
- bullet: what + why

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
git push origin <branch>
git log --oneline -3
```

---

### `kc D` — Deploy (inline)

```bash
# Auto-detected DEPLOY_CMD — examples:
# Static/Netlify:  netlify deploy --prod --dir site
# Node/Vercel:     vercel --prod
# Python/Fly.io:   fly deploy && fly status
# CD-on-push:      (push already triggers deploy)

DEPLOY_CMD

# Verify (VERIFY_CMD):
# curl -s -o /dev/null -w '%{http_code}' LIVE_URL  → expect 200
# curl LIVE_URL/health                              → expect {"status":"ok"}
```

---

### `kc CI` — Full improvement pipeline
Sequential: `kc I` → `kc Im` → `kc E` → `kc C` → `kc Bl` → `kc P` → `kc D`

Spawn each as its own agent. After each: did anything break? Fix before continuing.
Final report: structured summary · E scores before/after.

---

### `kc full` — Complete feature lifecycle
Sequential: `kc B` → `kc CI`

---

## DISPATCH RULES

1. Parse `kc <command>` or `kafcade <command>` or bare `B+CI+E+P+D+Bl` etc.
2. Run auto-detection (PROJECT_SNAPSHOT + CI_STACK + DEPLOY_CMD) first.
3. **Spawn** commands: `Agent(subagent_type=..., prompt=[PROJECT_SNAPSHOT] + template)`.
4. **Inline** commands: execute Bash steps directly (P and D are always inline).
5. Combinations (`kc B+P+D`): spawn B, await result, run P + D inline.
6. KafCa output: metrics first · no openers · no closers · WHY comments only.

---

## KafCa RRSS Principles

| Principle | Application |
|-----------|-------------|
| **Robust**     | Circuit-breaker: CI fails → fix before continuing, never skip gates |
| **Reliable**   | Config auto-detected, not hardcoded → works across project types |
| **Solid**      | B step only closes when CI passes and verify returns 200 |
| **Systematic** | Every session: auto-detect → execute → report → checkpoint |

---

## EvoMetaClaw Lineage

```
kafcade-v1.0 (2026-06-07)
  hardwired: free-claude-code · Python/uv · Vercel
  fitness: 6/10 (breaks on non-Python projects)

kafcade-v2.0 (2026-06-15)
  GRPO_STEP signal: mooc-designer static/Netlify session
  mutations:
    + PROJECT_SNAPSHOT auto-detection (replaces hardcoded snapshot)
    + CI_STACK detection (static/node/python)
    + DEPLOY_CMD detection (netlify/vercel/fly/railway)
    + Im: passive-listener check + global-shadow check
    + E: OG-meta check added
    + C: static-site gitignore patterns
  fitness: 9/10 (4 project types · portable · RRSS-compliant)

kafcade-v2.1 (2026-06-15)
  GRPO_STEP signal: free-claude-code B+Ci+E+P+D Bl session
    - B encountered an empty roadmap (BLUEPRINT.md "🔲 none"); spent cycles checking GH
      issues (gh CLI absent on Windows) before falling back to E.
    - E (read-only Explore) and Ci (uv run gates) ran cleanly in parallel.
    - Ci surfaced a real regression: 3 ty errors in tests/api/test_admin.py from
      `mod = importlib.reload(mod)` rebinding clashing with the narrowed import type.
      Fix: drop the reassignment (importlib.reload mutates in place); no # type: ignore
      (CLAUDE.md hard rule).
    - E flagged drift in BLUEPRINT.md Module Map (17→18 providers, 1429→1443 tests).
  mutations:
    + B: short-circuit on empty roadmap — emit "roadmap clear, propose via E or kc Im"
      instead of fabricating a target. Skip GH-issue lookup when `gh` not on PATH.
    + Parallelism rule: E (read-only) MAY run concurrently with Ci gates — they share
      no write surface. Sequential `kc CI` pipeline remains the default for Im/C/Bl/P/D.
    + Ci gate as own command: rename `kc CI` (pipeline) → `kc CIp`; introduce
      `kc Cg` for the gate-only run (ruff format + ruff check + ty + pytest). Keeps
      "Ci" / "CI" as user shorthand routable to either.
    + Co-Authored-By: bump default to "Claude Opus 4.7 (1M context)" — keeps lineage
      truthful to the model that actually ran the session.
    + EvoMetaClaw hook: every audit (kc E) that uncovers blueprint drift writes a
      one-line lineage signal here, even on otherwise no-op sessions.
  fitness: 9.5/10 (parallel-safe · empty-roadmap-aware · regression-catching)

kafcade-v2.2 (2026-06-15)
  GRPO_STEP signal: autoclaw B+Ci+E+P+D Bl session — distribution-first build
    - User asked for "SDK, binaries, APK or whatever other relevant ways to use the
      application". B target was not a roadmap item but a NEW DIMENSION: shipping
      surface (how users reach the product), not feature surface (what the product does).
    - PROJECT_SNAPSHOT auto-detect missed it: the repo had Cargo.toml + agent.go +
      agent.py + ui/ (vite) all at once. CI_STACK matrix didn't model "polyglot core
      + multi-runtime distribution". Got past it by treating distribution channels as
      first-class deliverables (sdk/python, sdk/js, sdk/go, mobile/, packaging/).
    - User followed with "landing page linking to clow + desiredsolutions presence".
      Cross-project context was needed — pulled JSON-LD identity graph from clow's
      index.html (clow-tau.vercel.app, desiredsolutions.space, dnzengou GitHub,
      LinkedIn) so autoclaw's schema.org sameAs links the family, not isolated.
    - install.sh and install.ps1 both ship sha256 verification by default — RRSS
      Resistant/Secure principle applied at the SUPPLY-CHAIN layer, not just the code.
    - Tauri 2 mobile gives APK + IPA + macOS .app + Windows .exe + Linux AppImage
      from one source tree — the "or whatever other relevant ways" expanded from
      "binaries" to "all five desktop bundles + two mobile bundles" essentially free.
  mutations:
    + PROJECT_SNAPSHOT extension: detect POLYGLOT projects (Cargo.toml AND go.mod
      AND pyproject.toml AND ui/package.json). When polyglot, emit a "distribution
      matrix" hint at session start so B knows it has multiple shipping vectors.
    + B: when user goal is "ways to use X" / "distribute X" / "ship X" / "SDK/binary/
      APK/package" — treat as MULTI-CHANNEL build. Auto-scaffold sdk/{python,js,go}/,
      .github/workflows/{release,docker,android}.yml, install.{sh,ps1}, packaging/
      {homebrew,scoop,debian}/ in one pass. Don't ask "which channel?" — ship all.
    + Bl: blueprint MUST include a "Distribution Channels" table when project ships
      to end users. Use status column (✅ CI ready / 🔲 planned) per channel.
    + LANDING-PAGE channel: marketing surface is part of distribution. When user
      asks for "landing page" / "marketing site" / "product page":
        - Match the parent brand's stack (read sibling project's index.html if any).
        - Pull JSON-LD identity graph from sibling (Organization, sameAs, founder)
          and link the new product into it via schema.org subOrganization / sameAs.
        - Same analytics (Plausible domain swap), same form provider (Web3Forms),
          same security headers (CSP allow plausible.io + web3forms.com only).
        - Ship as site/ subdir with vercel.json + 404.html + robots.txt + sitemap.xml.
    + RRSS ARM extension: ARM = Adoption · Retention · Monetization. Apply at
      shipping layer:
        - Adoption: 14-channel install grid (lowest-friction first: pip > brew > sh).
        - Retention: managed Pro tier in pricing block with waitlist CTA.
        - Monetization: 3-tier pricing (OSS €0 / Pro €9.99 / Enterprise contact),
          matching Clow's €9.99/mo proven price point.
    + Cross-project memory pull: when a sibling project is named in the prompt
      ("clow", "desiredsolutions", etc.) check /c/Users/nzengou/.claude/projects/<sibling>/memory/MEMORY.md
      for canonical URLs, brand voice, pricing, analytics IDs. Do not invent.
    + Co-Authored-By: keep "Claude Opus 4.7 (1M context)" — confirmed model id.
  fitness: 9.8/10 (polyglot-aware · distribution-as-first-class · cross-project-linked)

kafcade-v2.3 (2026-06-18)
  GRPO_STEP signal: autoclaw post-push reality session
    - Three CI workflows (CI, Docker, Android) went green-to-red on first push and
      stayed red across three remediation commits. Root causes were all "shipped
      configs the user trusts" but never test-fired locally:
        * ci.yml referenced `dtolnay/rust-action@stable` (non-existent action,
          correct name is `dtolnay/rust-toolchain@stable`)
        * Dockerfile expected `Cargo.lock` after we gitignored it
        * android.yml expected `ui/package-lock.json` for npm cache key
        * ui/package.json `"build": "tsc && vite build"` failed strict tsc because
          App.tsx imported React but never referenced React.* (jsx: react-jsx)
        * mobile/tauri.conf.json referenced icons/ that didn't exist
        * docker.yml multi-arch (amd64+arm64) timed out even with a Go-based image
    - First-shipped-distribution channels (Homebrew/Scoop) had REPLACE_WITH_*
      placeholders that would 100% block first install — no automation existed to
      fill them post-release.
    - PR #1 (Docker pivot) was opened but never merged; main kept regressing while
      the fix sat in a branch. Open PRs are not delivered work.
  mutations:
    + CI-truth rule: NEVER ship `continue-on-error: true` as a quality strategy.
      Use it only as a temporary diagnostic. Each `continue-on-error` should have
      a TODO with a target date for removal. Background: pretending tests pass
      hides regressions and breaks the very RRSS Reliable principle the skill claims.
    + Lock-file rule: when a workflow caches deps via lockfile path, generate the
      lockfile (npm install --package-lock-only, cargo generate-lockfile) and
      commit it. Don't reference a path that won't exist on a fresh checkout.
    + Action-name verification: before referencing a third-party GitHub Action,
      curl `https://github.com/<owner>/<repo>` and confirm 200. `@stable` /
      `@v3` look identical when wrong; the run only fails at step setup time.
    + Asset-existence rule: when a build references a directory (icons/, assets/,
      public/), ensure at LEAST a placeholder is committed. Empty .gitkeep + a
      generator script (cargo tauri icon icons/icon.svg) is better than failing
      at minute 12 of a CI run.
    + Multi-arch Docker rule: ship amd64 first, arm64 SECOND only after amd64 is
      green for two consecutive runs. QEMU-emulated arm64 builds take 3-5×
      longer and have an independent failure surface (musl quirks, glibc deltas).
    + Post-release automation as a first-class channel: SDK / binary release
      isn't complete without a workflow that auto-updates Homebrew formula +
      Scoop manifest + .deb control SHA256s. release-publish.yml as standard
      companion to release.yml. Without it, install channels are aspirational.
    + Security defaults: ship .github/dependabot.yml + .github/workflows/codeql.yml
      + .github/SECURITY.md in the same commit as the first distribution channels.
      Don't bolt on after the first CVE.
    + SDK smoke-test minimum: every SDK ships with a 5-test smoke suite that
      pings a mocked server and verifies type round-trip. Type signatures alone
      are not a contract test.
    + PR-merge follow-through: opening a PR is half the work. After 24h with no
      review, fold the fix forward into a follow-up commit on main and close
      the PR with a reference. Don't let "open PR for visibility" accumulate.
    + README badges + table-of-docs are not decoration — they're the discovery
      surface for every new visitor. Ship in the same commit as distribution.
  fitness: 9.9/10 (CI-honest · supply-chain-complete · security-defaulted)

kafcade-v2.4 (2026-06-22) ← CURRENT
  GRPO_STEP signal: rrss-toolkit B+P session — multi-skill bundle distribution
    - User asked: "Build a sdk / apk / plugin / extensions or whatever ways to
      distribute these evolve version, ARM RRSS KafCa KafCade". Different shape
      from v2.2/v2.3's "ship ONE app across channels". Here the artifacts are
      heterogeneous: ARM is Python code (~140 LoC inside browser-use), RRSS is
      design principles (no code), KafCa+KafCade+EvoMetaClaw are SKILL.md
      markdown files living in ~/.claude/skills/.
    - v2.2's "ship all channels" doctrine would have wasted effort on APK/IPA
      for things that are SKILLS, not applications. The KafCa pillar "no
      hedging — decide or defer" forced an honest cut: APK doesn't fit.
    - The unifying shipping unit was `rrss-toolkit/` — a bundle, not a single
      product. Combines: PyPI (rrss-arm) + Claude Code skills (4 markdown
      files via manifest.json) + cross-platform installer (install.sh +
      install.ps1) + GH Actions release that publishes BOTH the wheel AND
      the skill bundle with sha256 checksums (tag-prefix `rrss-v*`).
    - "Evolve" in the user's prompt was both a verb AND an artifact name
      (evo-metaclaw skill). Resolved by treating it as a verb on this very
      skill — this lineage entry IS the evolutionary signal.
    - The new `rrss` skill was authored fresh (not extracted) — it consolidates
      RRSS principles that were previously scattered across kafca+kafcade. This
      is META_SKILL_GENERATE in the EvoMetaClaw vocabulary: a higher-order
      skill emerging when a pattern repeats across the population.
  mutations:
    + MULTI-SKILL-BUNDLE shape detection: when user asks to distribute "these"
      with mixed artifact types (code + skills + docs), emit a single bundle
      directory with per-channel subdirs (sdk/python, sdk/js, skills, packaging)
      and a top-level manifest.json that maps source -> dest for each artifact.
      Don't force all artifacts into the same channel.
    + APK/mobile heuristic: if the underlying artifacts are SKILLS or LIBRARIES
      (not an end-user app with a UI), SKIP mobile channels. Saves a week of
      Tauri-stub bikeshedding. Mobile makes sense only when there's a UI.
    + skills/ as a first-class channel: bundle markdown SKILL.md files with a
      manifest.json (name/version/source/dest), back up existing files before
      overwrite (.backup.YYYYMMDD-HHMMSS), make sha256 checksums mandatory
      (extends v2.3 supply-chain rule from binaries to text artifacts).
    + Lift-out pattern: when a self-contained module exists inside a host project
      (e.g. browser_use/research/circuit.py), extract it verbatim into the new
      package keeping the same module name (rrss_arm/circuit.py). Host stays
      source of truth; the lift-out is a snapshot tagged by version.
    + Tag-prefix isolation for sub-releases: when a sub-project lives inside a
      larger repo, use a tag prefix (rrss-v*) so its release pipeline doesn't
      collide with the host's main release stream. release-rrss.yml triggers
      only on `rrss-v*` tags.
    + "Evolve" as recursion guard: when user says "evolve" alongside concrete
      build targets, do BOTH — append a lineage entry AND ship the artifact.
      Don't enter a meta-loop. Circuit-breaker: max recursion depth 1 per turn
      (EvoMetaClaw CIRCUIT_BREAKER_CHECK / max_recursion_depth=2 still applies).
    + Bundle README must list shipped + planned channels with effort/leverage
      table — gives user a clear stage-2 menu without committing to all of it.
  fitness: 9.85/10 (multi-artifact-aware · honest-cuts · meta-recursion-safe)
  next evolution trigger: "kafcade evolve" | first session shipping a CLI binary
    via this same bundle pattern (will surface the cargo/go-build cross-compile
    matrix the lift-out pattern doesn't cover)
```

---

## VERSIONING

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-06-07 | Initial — hardwired to free-claude-code, Python/uv/Vercel |
| 2.0 | 2026-06-15 | Multi-project auto-detect (static/node/python/docker). Im adds passive-listener + global-shadow checks. E adds OG-meta check. C adds static-site .gitignore patterns. EvoMetaClaw lineage block. RRSS table. Known project registry. |
| 2.1 | 2026-06-15 | B short-circuits on empty roadmap (no fabricated targets, no gh dependency on Windows). E may run in parallel with Ci gates. Split `kc CI` (pipeline) → `kc CIp` and introduce `kc Cg` for the gate-only run. Co-Authored-By bumped to Opus 4.7. Audits that catch blueprint drift write a lineage signal even on no-op sessions. |
| 2.2 | 2026-06-15 | Polyglot projects detected as first-class. B treats "ways to use / distribute / ship / SDK / binary / APK" as multi-channel build — ships all channels at once (Python/JS/Go SDKs + Rust+Go binaries × 5 OS/arch + APK/IPA + Homebrew/Scoop/.deb + Docker multi-arch + install.sh/ps1). Bl requires Distribution Channels table when product ships to end users. New LANDING-PAGE channel: match sibling project stack, link via JSON-LD identity graph (sameAs/subOrganization), reuse analytics/form/CSP. RRSS extended with ARM (Adoption/Retention/Monetization) at shipping layer. Cross-project memory pull when sibling brand named in prompt. |
| 2.3 | 2026-06-18 | CI-honesty mandate — `continue-on-error: true` is diagnostic only, never a quality strategy. Asset-existence rule: placeholder + generator script for any referenced directory (icons/, assets/). Multi-arch Docker ships amd64 first, arm64 after two green runs. Lock-file rule: generate + commit any lockfile referenced by cache keys. Action-name verification: curl-check action URLs before using. Post-release automation: `release-publish.yml` auto-updates Homebrew + Scoop + .deb SHA256s after each tag. Security defaults: Dependabot + CodeQL + SECURITY.md ship in same commit as distribution. SDK smoke-test minimum: 5 tests/mocked-server/type-round-trip. PR-merge follow-through: don't accumulate open PRs as "visibility". README badges + table-of-docs ship same commit as distribution. |
| 2.4 | 2026-06-22 | Multi-skill-bundle shape detected when user asks to distribute heterogeneous artifacts (code + skills + docs). Single bundle directory with per-channel subdirs + manifest.json mapping source→dest. APK/mobile auto-skipped when artifacts are skills/libraries with no UI (saves a week of bikeshedding). skills/ promoted to first-class channel: markdown SKILL.md + manifest.json + sha256 checksums + backup-on-overwrite. Lift-out pattern: vendor self-contained modules into new PyPI packages keeping the same module name (host stays source of truth). Tag-prefix isolation for sub-releases (rrss-v*) so sub-project release pipelines don't collide with host. Meta-recursion guard: "evolve" + concrete targets → do both (lineage entry + ship), max depth 1. Bundle README must list shipped + planned channels with effort/leverage table. |
