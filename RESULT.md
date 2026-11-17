# Live gallery redesign

The gallery now uses a near-black canvas, the platform system font, a quiet Live/tab-count header, and borderless 16:10 previews with 12px corners and soft depth. Each preview has a compact caption with a local letter avatar, ellipsized title, and muted host. No favicon requests or external assets are used.

The enlarged view uses a source-anchored FLIP transform driven by a critically damped spring. Retargeting preserves position and velocity; Escape, the close button, and the backdrop dismiss it, and focus returns to the tile. Clicking the preview during dismissal reverses the transition. Reduced motion skips transforms and disables shimmer/pulse animations. Loading, empty, disconnected, increased contrast, reduced transparency, and safe-area layouts are covered. The grid uses one column on phones, two or three on laptops, and four on wide screens.

Only the inline HTML/CSS/JS changed in production. Python CDP handling, bearer-token authentication, CSP, data-only images, and read-only behavior are unchanged. The HTML and Python source remain ASCII-only.

## Critique and polish findings fixed

Read Apple Design in full and Impeccable's skill, critique, polish, and craft-floor references. Applied the supplied brief as the visual direction. The manual visual and interaction review found and fixed:

- Excessive interface weight: removed the branded eyebrow, toolbar instructions, numerical badges, heavy tile chrome, and full URL noise. Previews now lead the composition.
- Poor live-dot legibility over pale pages: added a small dark backing and kept the green indicator quiet.
- Slow return motion under a heavily loaded headless browser: replaced timestep-limited integration with an elapsed-time analytical spring, preserving interruption velocity.
- Invalid initial phone capture during dismissal: recaptured only after the native dialog closed; verified a 390px viewport has a 390px document width.
- Repeated screen-reader status announcements: update the tab-count live region only when the count changes.
- Keyboard continuity and motion preferences: added a real-Chrome regression covering Enter, Escape during opening, focus restoration, reduced motion, long titles, loading frames, aspect ratio, and phone overflow.

The first implementation was inspected at desktop, enlarged, phone, and empty states; the second polish iteration was inspected again. Invalid phone evidence was replaced. Final captures were opened and visually checked. No generated or synthetic page imagery was substituted.

Impeccable's factory instructions prohibit its launcher, scripts, detector, and hooks, so those were not run. There is no existing PRODUCT.md or DESIGN.md. Its critique reference requests explicit permission for two independent agents; permission was requested asynchronously and has not yet been received. The findings above are the manual polish pass, not a completed dual-agent critique.

## Screenshots

WebP files are in `/home/exedev/work/shots-ui/`:

| State | Baseline | Redesigned |
| --- | --- | --- |
| 1440 x 900 grid | before-desktop.webp | after-desktop.webp |
| 1440 x 900 enlarged | before-enlarged.webp | after-enlarged.webp |
| 390 x 844 phone | before-phone.webp | after-phone.webp |
| 1440 x 900 empty | before-empty.webp | after-empty.webp |

Baseline HTML was imported directly from `/home/exedev/work/wt-gallery/browser_use/gallery.py` on `oss/gallery`, without modifying that worktree. Each capture used a local source Chrome with the six requested real public pages and a separate headless viewer Chrome. Empty-state captures used a source browser with no page targets. The same public-page URLs and 1280 x 800 source viewport were used throughout; target discovery order can differ. Temporary capture browsers and servers were stopped.

## Validation

- `uv run pytest tests/ci/test_gallery.py -q`: 10 passed, including real Chrome interaction and the existing security/streaming tests.
- `PATH=$HOME/.local/bin:$PATH uv run pytest tests -m "not chrome" -q`, with SIGHUP reset to its default disposition: 942 passed, 3 skipped, 144 deselected. One existing Pydantic AI streamed-compaction warning.
- New regression run against the unchanged baseline HTML: failed as expected; current HTML passes.
- Production Python AST comparison: identical outside the HTML constant.
- `git diff --check`: passed.
- `PATH=$HOME/.local/bin:$PATH uv run pre-commit run --all-files`: passed.

The initial broad test attempt collided with a temporary file from the concurrent yesqa pre-commit hook and failed during collection. The successful full run above was performed sequentially. The initial formatter pass reformatted the new test; subsequent formatting passed.
