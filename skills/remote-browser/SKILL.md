---
name: remote-browser
description: Controls an isolated Browser Use Cloud browser from a sandboxed machine with the current Browser Use CLI.
allowed-tools: Bash(browser-use:*)
---

# Remote Browser

Use this skill when an agent runs on a machine without a usable local Chrome and needs an isolated browser. The current Browser Use CLI runs Python from stdin. Do not use the removed `open`, `state`, `click`, `input`, `tab`, `cloud connect`, or `--connect` commands.

## Check the CLI

```bash
browser-use --doctor
browser-use skill show
```

If setup fails, follow the current [Browser Use skill](../browser-use/SKILL.md).

## Start an isolated browser

Authenticate once:

```bash
browser-use auth login
```

Pick a short unique name. `r7k2` below is only an example.

```bash
browser-use <<'PY'
start_remote_daemon("r7k2")
PY
```

Use the same name for every command in this browser:

```bash
BU_NAME=r7k2 browser-use <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

Each remote daemon is a separate Browser Use Cloud browser. Use a different name for each parallel task. Remote browsers can bill until they stop or time out.

## Inspect and interact

Helpers are pre-imported. Keep multi-step work in one heredoc when practical.

```bash
BU_NAME=r7k2 browser-use <<'PY'
print(page_info())
print(js("document.title"))

fill_input('input[name="q"]', "browser automation")
press_key("Enter")
wait_for_load()

print(page_info())
PY
```

Useful helpers:

- Navigate: `new_tab(url)`, `goto_url(url)`, `wait_for_load()`
- Inspect: `page_info()`, `js(code)`, `cdp(method, ...)`
- Interact: `click_at_xy(x, y)`, `type_text(text)`, `fill_input(selector, text)`, `press_key(key)`, `scroll(x, y)`
- Tabs: `list_tabs()`, `switch_tab(target)`, `close_tab(target)`
- Files and proof: `capture_screenshot()`, `wait_for_element(selector)`

Prefer the accessibility tree for element discovery:

```python
nodes = cdp("Accessibility.getFullAXTree")["nodes"]
```

Use a targeted `js(...)` query when the accessibility tree lacks the element. Verify each action with `page_info()`, a focused DOM check, or a screenshot.

## Stop the browser

When the work is done, stop the exact named browser:

```bash
browser-use <<'PY'
stop_remote_daemon("r7k2")
PY
```

Do not leave an unused remote browser running.
