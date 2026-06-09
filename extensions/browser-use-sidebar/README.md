# Browser Use Sidebar Assistant

Chrome/Edge side-panel extension for sending the current page context to a local Browser Use assistant.

## Start the Local Bridge

From the repository root:

```powershell
$env:PYTHONPATH='.'
C:\Users\zhy\anaconda3\envs\browser-use311\python.exe -m browser_use.skill_cli.main sidepanel-server --model gpt-5.4 --cdp-url http://localhost:9222
```

The extension expects the bridge at:

```text
http://127.0.0.1:8765
```

If `--cdp-url` is omitted, the bridge tries to auto-discover a running Chrome CDP endpoint. Use `--no-auto-cdp` to force the assistant to launch its own headless browser instead.

## Load the Extension

1. Open `chrome://extensions`.
2. Enable `Developer mode`.
3. Click `Load unpacked`.
4. Select this folder:

```text
C:\Users\zhy\Desktop\课程材料\browser-use\extensions\browser-use-sidebar
```

5. Click the Browser Use toolbar icon to open the side panel.

## Autofill Profiles

The bridge keeps local autofill profiles in JSON. By default it creates:

```text
%USERPROFILE%\.browser-use\sidepanel_profiles.json
```

You can override the path:

```powershell
$env:PYTHONPATH='.'
C:\Users\zhy\anaconda3\envs\browser-use311\python.exe -m browser_use.skill_cli.main sidepanel-server --model gpt-5.4 --cdp-url http://localhost:9222 --credential-store C:\Users\zhy\Desktop\profiles.json
```

Use `autofill_profiles.example.json` as the schema reference. Each profile can match by `domains` and/or `urls`, then provide fields with optional CSS `selectors` and semantic `aliases`.

The extension only previews non-secret metadata automatically. It requests actual values only after you click `Autofill current page`, and only for the current page URL.

## Usage

Open any page, refresh the side panel context, enter a task, and click `Run`. With `Auto observe` enabled, the side panel follows tab changes and periodically refreshes the current page title, URL, visible text, and visible links.

Chinese tasks are sent with `locale=zh-CN` automatically when Chinese text is detected. API keys and autofill profile values stay in the local bridge; the extension does not store model credentials.
