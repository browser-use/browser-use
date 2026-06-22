# RRSS Toolkit

**Robust · Reliable · Solid · Systematic.**
Distribution layer for ARM, RRSS, KafCa, KafCade.

Lineage: extracted from `browser_use/research/circuit.py` (ARM) + `~/.claude/skills/{kafca,kafcade,evo-metaclaw}/` skill set. Evolved by EvoMetaClaw v2.0 → KafCade v2.4.

## What ships

| Channel | Install | What you get |
|---------|---------|--------------|
| **PyPI** | `pip install rrss-arm` | ARM async circuit breaker + KafCa decorators |
| **Claude Code skills** | `curl -fsSL <raw>/install.sh \| bash` | kafca, kafcade, evo-metaclaw, rrss → `~/.claude/skills/` |
| **One-liner (sh)** | `curl -fsSL <raw>/install.sh \| bash` | Both of the above, sha256-verified |
| **One-liner (ps1)** | `iwr <raw>/install.ps1 -useb \| iex` | Same, Windows-native |

## Stage 1 scope (this release)

- `sdk/python/` — `rrss-arm` package: `HostCircuitBreaker`, `CircuitOpenError`, `kafca_timeout`, `kafca_retry`
- `skills/` — 4 Claude Code skills as standalone markdown files
- `install.sh` / `install.ps1` — sha256-verified installers
- `.github/workflows/release-rrss.yml` — tag-triggered PyPI publish + GitHub release

## Stage 2 (planned — see BLUEPRINT.md)

- npm `@rrss/arm` (JS port)
- Browser extension (Chrome/Firefox) — KafCa overlay for claude.ai / chatgpt
- Homebrew tap, Scoop bucket, Docker image

## Out of scope

- APK / mobile — these are skills + a circuit breaker, not an app. If you want mobile, build a separate product on top.

## Layout

```
rrss-toolkit/
├── sdk/python/                 PyPI package
│   ├── pyproject.toml
│   ├── README.md
│   ├── LICENSE
│   └── src/rrss_arm/
│       ├── __init__.py
│       ├── circuit.py          ARM HostCircuitBreaker
│       └── kafca.py            kafca_timeout, kafca_retry decorators
├── skills/                     Claude Code skill bundle
│   ├── kafca.md
│   ├── kafcade.md
│   ├── evo-metaclaw.md
│   └── rrss.md                 NEW: consolidated RRSS principles skill
├── install.sh                  POSIX installer (Linux/macOS/Git-Bash)
├── install.ps1                 PowerShell installer (Windows native)
├── BLUEPRINT.md                Roadmap + lineage
└── .github/workflows/
    └── release-rrss.yml        Tag-triggered release
```

## Versioning

Independent semver per channel.

| Component | Version |
|-----------|---------|
| `rrss-arm` (PyPI) | 0.1.0 |
| Skills bundle | 0.1.0 |
| KafCade skill | 2.4 (bumped from 2.3) |
| KafCa skill | 1.0 |
| EvoMetaClaw skill | 2.0 |
