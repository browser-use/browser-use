# DevFlow — AI Development Workflow Skill
## Version 1.0 · Portable · LLM-Agnostic

> A structured, command-driven development workflow for AI coding assistants.
> Works with: Claude (Code), GPT-4/o, Gemini, Mistral, local LLMs (Ollama, LMStudio, PicoClaw, OpenClaw).
> Use as a skill file, system prompt prefix, or context injection.

---

## COMMAND REFERENCE

| Command | Full Name        | One-Line Description |
|---------|-----------------|----------------------|
| `B`     | Build           | Implement the next roadmap item or specified feature |
| `I`     | Integrate       | Reflect on recent changes · sync docs + state |
| `Im`    | Improve         | Refactor, optimise, harden — no new features |
| `E`     | Evaluate        | Audit: quality · security · performance · consistency |
| `C`     | Consolidate     | Deduplicate · remove dead code · reorganise |
| `Bl`    | Blueprint       | Update the project documentation/blueprint file |
| `P`     | Push            | Git commit (smart message) + push to all remotes |
| `D`     | Deploy          | Deploy to live server; confirm live URL |
| `CI`    | Continuous Improve | Full pipeline: I → Im → E → C → Bl → P → D |

**Combination syntax:** `B+Bl+P+D` runs commands left-to-right.
**Pipeline alias:** `full` = `B+I+Im+E+C+Bl+P+D`

---

## COMMAND SPECIFICATIONS

### B — Build
**Purpose:** Implement the next item on the project roadmap, or a feature the user specifies.

**Steps:**
1. Read `CLAUDE.md` (or equivalent project context file) and the blueprint/roadmap.
2. Identify the next `🔲` roadmap item, or accept a feature spec from the user.
3. Plan: list files to create/modify, dependencies, security implications.
4. Implement: write code that is **secure, efficient, robust, stable, scalable**.
5. Verify: check for syntax errors, broken references, exposed secrets.
6. Report: what was built, what files changed, what is next.

**Quality gates (must pass before completing B):**
- No API keys or secrets hardcoded in source
- All user-controlled strings HTML-escaped before innerHTML injection
- Graceful fallback / error handling on every async operation
- No `eval()`, no `document.write()`, no inline `javascript:` hrefs

---

### I — Integrate
**Purpose:** Reflect on what was built; synchronise code ↔ docs ↔ state.

**Steps:**
1. `git diff HEAD` — summarise what changed since last commit.
2. Check that every new function/module is documented.
3. Check that roadmap items newly completed are marked `✅` in blueprint.
4. Note any technical debt, deferred items, or follow-up needed.
5. Update `CLAUDE.md` if architectural facts changed.
6. Output: integration summary (what changed, what is in sync, what needs attention).

---

### Im — Improve
**Purpose:** Improve existing code quality without changing external behaviour.

**Steps:**
1. Run `E` (Evaluate) first to get a prioritised finding list.
2. Apply improvements in priority order:
   - **P0 — Security:** XSS vectors, exposed secrets, unsafe patterns → fix immediately
   - **P1 — Correctness:** off-by-one, null-dereference, race conditions
   - **P2 — Performance:** unthrottled events, redundant re-renders, large payloads
   - **P3 — Quality:** dead code, magic numbers, duplicated logic, inconsistent naming
   - **P4 — Style:** formatting, comment accuracy, unused imports
3. Do not introduce new features during Im.
4. Report: list of improvements made, items deferred, measurable gains (if any).

---

### E — Evaluate
**Purpose:** Produce a structured audit report across four axes.

**Output format:**
```
## Evaluation Report — [project] [date]

### Security  (P0)
[finding: file:line — description — severity — recommended fix]

### Correctness  (P1)
[...]

### Performance  (P2)
[...]

### Quality / Consistency  (P3–P4)
[...]

### Score
Security: X/10 · Correctness: X/10 · Performance: X/10 · Quality: X/10
```

**Checks to run:**
- Grep for: `innerHTML =`, `eval(`, `document.write(`, `localStorage.setItem.*secret`, hardcoded tokens
- Count async functions without try/catch
- Check all external API calls have timeout/abort handling
- Verify CSP headers present (if web project)
- Check service worker cache strategy is correct
- Verify no `console.log` of sensitive data

---

### C — Consolidate
**Purpose:** Clean up; eliminate redundancy; improve organisation.

**Steps:**
1. `git status` — list untracked files that should be .gitignored.
2. Find duplicate functions/logic → extract to shared helpers.
3. Remove dead code (functions never called, CSS never used).
4. Verify file organisation matches blueprint file manifest.
5. Check `.gitignore` covers: `node_modules/`, `.env`, `*.log`, `dist/`, secrets.
6. Report: what was removed/merged, line-count delta, files reorganised.

---

### Bl — Blueprint
**Purpose:** Update the project's living blueprint/documentation file to reflect current reality.

**Steps:**
1. Read the blueprint file (e.g., `*_Blueprint*.md`).
2. Diff blueprint claims vs. actual code state:
   - Version number matches `package.json`
   - All shipped roadmap items marked `[x]`
   - Module/function count is accurate
   - File manifest reflects actual files
   - API table reflects actual integrations
3. Add changelog entry for the current version.
4. Update executive summary if scope changed.
5. Update footer: version · date · deploy URL.
6. **Preserve all historical changelogs** — never delete past entries.

---

### P — Push
**Purpose:** Commit all staged changes with a smart message and push to all remotes.

**Steps:**
1. `git status` — list what will be committed (never use `git add -A` blindly; stage specific files).
2. `git diff --stat` — confirm the diff is as expected.
3. Compose commit message:
   - Type prefix: `feat:` / `fix:` / `docs:` / `refactor:` / `perf:` / `security:`
   - Subject line: ≤72 chars, imperative mood, no period
   - Body: what + why (not how), bullet list if multiple changes
   - Footer: `Co-Authored-By:` if AI-assisted
4. `git commit -m "..."` via HEREDOC to preserve formatting.
5. `git push origin main`
6. If project has dual-branch deploy (e.g., `root` = GitHub Pages default): `git push origin main:root`
7. Confirm: show `git log --oneline -3`.

---

### D — Deploy
**Purpose:** Push the live version to the deployment target and confirm.

**Detection order (first match wins):**
1. `netlify.toml` present → deploy via Netlify
2. `vercel.json` present → deploy via Vercel
3. `.github/workflows/*.yml` present → GitHub Actions (auto on push)
4. No config → GitHub Pages (push to `gh-pages` or configured branch)

**Netlify path:**
```bash
# If netlify CLI available:
netlify deploy --prod --dir .
# If not: push to connected branch triggers CD automatically
# One-time setup: netlify.com/import → GitHub → select repo → branch: root/main
```

**Vercel path:**
```bash
# If vercel CLI available:
vercel --prod
# If not: push to connected branch triggers CD automatically
# One-time setup: vercel.com/import → GitHub → select repo
```

**GitHub Pages path:**
```bash
# Served from root of `root` or `main` branch
# Settings → Pages → Source → branch: root / folder: / (root)
```

**After deploy — verify:**
- Live URL loads (HTTP 200)
- Service Worker registered (DevTools → Application → Service Workers)
- PWA manifest valid
- No mixed-content warnings

---

### CI — Continuous Improve
**Purpose:** Run the full improvement pipeline without building new features.

**Pipeline:** `I → Im → E → C → Bl → P → D`

**Execution:**
1. Run each command in sequence.
2. After each command, check: did anything break? If yes, fix before continuing.
3. At end, report a structured summary of all changes made.
4. Flag any items that require human decision (breaking changes, cost implications, etc.).

---

## COMBINATION RULES

| Input | Resolves to | Typical use case |
|-------|------------|-----------------|
| `B P D` | Build → Push → Deploy | Ship a new feature |
| `I Bl P` | Integrate → Blueprint → Push | Sync docs after a build session |
| `Im P D` | Improve → Push → Deploy | Harden + ship |
| `E Im` | Evaluate → Improve | Quality pass without deploy |
| `C Bl P` | Consolidate → Blueprint → Push | Cleanup commit |
| `CI` | I→Im→E→C→Bl→P→D | Full maintenance cycle |
| `full` | B→I→Im→E→C→Bl→P→D | Complete feature lifecycle |

**Parsing rules:**
- Commands separated by space, `+`, `,`, or `→` are all equivalent.
- Commands are case-insensitive: `b+p+d` = `B+P+D`.
- If user types only a command letter with no other context, infer project from current working directory / open files.

---

## CONTEXT DETECTION

When invoked, the skill auto-detects project context by reading (in order):
1. `CLAUDE.md` — project facts, conventions, commands
2. `*_Blueprint*.md` — roadmap, architecture, version
3. `package.json` — name, version, scripts
4. `git log --oneline -5` — recent activity
5. `git status` — current state

If none found, ask user: "What is this project? Drop a README or describe it."

---

## QUALITY PRINCIPLES (R²S²)

Every output from this skill must be:

| Principle | Meaning |
|-----------|---------|
| **Robust** | Handles errors gracefully; never crashes silently |
| **Reliable** | Produces consistent, predictable results |
| **Solid** | No half-measures; complete implementations only |
| **Stable** | Does not break existing functionality |
| **Resistant** | Fault-tolerant; degrades gracefully under failure |
| **Scalable** | Code patterns support growth without rewrite |
| **Secure** | No exposed secrets · XSS-safe · CSP-compliant |
| **Systematic** | Follows established project conventions |

---

## PORTABILITY NOTES

### Using with Claude Code (this file as a skill)
Register: place in `~/.claude/skills/devflow.md` or invoke via `/devflow`.
Trigger phrases: any of the command letters alone or combined, or "devflow".

### Using with other cloud LLMs (GPT-4, Gemini, Mistral, etc.)
Paste this document as the **system prompt** prefix, then type your command.
Example system prompt: `[paste DEVFLOW_SKILL.md content] --- Project context: [paste README or blueprint]`

### Using with local LLMs (Ollama / LMStudio / PicoClaw / OpenClaw)
1. Create a Modelfile or system prompt template with this document.
2. Recommended models: `codestral`, `deepseek-coder-v2`, `qwen2.5-coder`.
3. For PicoClaw/OpenClaw: place in the system prompt field of the model config.
4. Temperature: 0.1–0.2 for deterministic code output.

### Ollama Modelfile example
```
FROM deepseek-coder-v2
SYSTEM """
[paste full DEVFLOW_SKILL.md content here]
"""
PARAMETER temperature 0.15
PARAMETER top_p 0.9
```

---

## VERSIONING

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | May 2026 | Initial release · 9 commands · R²S² principles · full portability guide |

---

*DevFlow Skill v1.0 · Designed for WanderSync · Generalises to any software project*
*Portable: Claude · GPT-4 · Gemini · Mistral · Ollama · PicoClaw · OpenClaw*
