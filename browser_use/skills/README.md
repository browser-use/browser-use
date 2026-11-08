# browser_use.skills

The `browser-use` agent skill and its installer, behind the `browser-use skill` command:

- `browser-use/SKILL.md`: the skill. It is the `SKILL.md` of the pinned browser-harness release under the Browser Use
  name; `scripts/sync_browser_harness_skill.py` regenerates it and the repo copy in `skills/browser-use/` from the
  installed harness. Bump the pin, `uv sync`, rerun the script.
- `browser_use.py`: the renaming (name, description, OpenClaw install metadata).
- `install.py`: `browser-use skill show` prints the skill. `browser-use skill install` writes it to `~/.agents` and to
  each supported agent you have installed; `--target NAME` picks one, `--path DIR` a custom location.

The other skills (`cloud`, `open-source`, `qa`, `remote-browser`, `x402`) live in the repo's `skills/` directory.
