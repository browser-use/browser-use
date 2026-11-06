# BrowserBuddy

A small macOS desktop MVP for browser-use built with Gradio + PyInstaller.

## What it does

- Opens a local Gradio UI in the browser.
- Saves the DeepSeek API key in macOS Keychain.
- Runs browser-use tasks with a dedicated browser profile.
- Writes logs to `~/Library/Logs/BrowserBuddy/app.log`.
- Renders link preview cards by fetching page metadata (`og:image`, description, favicon).
- Shows attachments and image previews; PDF attachments get a first-page PNG preview.
- Bundles Playwright Chromium so friends do not have to install Python or Playwright.

## User guide

The app includes a **功能与示例** tab with:

- Supported browser actions and task types.
- Ready-to-use example tasks in **Chinese and English**.
- Tips for writing clear prompts.
- Current limitations (CAPTCHA, 2FA, anti-bot pages, file attachments).

The task screen also has an **示例任务** dropdown. Select one and click **填入示例** to load it into the task box. Both `中文｜...` and `English | ...` options are available.

Example tasks cover search and summarization, CSV extraction, price comparison, login testing, multi-tab reading, page validation, downloadable files, and multi-source research.

## Development

From this directory:

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ../.. gradio keyring

python app.py
```

Set the DeepSeek key in the UI. It is stored in macOS Keychain, not in the repository.

## Build a macOS app

```bash
./build_mac.sh
```

By default the build looks for Google Chrome at:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

If Chrome exists, it skips the Chromium download and the resulting app uses the friend's installed Chrome. If you want to distribute to people who may not have Chrome, force bundling:

```bash
BUNDLE_CHROMIUM=1 ./build_mac.sh
```

Outputs:

```text
dist/BrowserBuddy.app
dist/BrowserBuddy.dmg
```

For a debug build with a terminal window:

```bash
CONSOLE=1 ./build_mac.sh
```

## Signing and notarization

Without an Apple Developer signature, macOS Gatekeeper will block the app. For an MVP, friends can:

1. Right-click `BrowserBuddy.app`.
2. Choose **Open**.
3. Choose **Open** again.

For a polished release, set a Developer ID identity:

```bash
APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./build_mac.sh
```

Notarization is a separate step with `notarytool` and `stapler`.

## Customize

- App name: `APP_NAME` in `app.py` and `build_mac.sh`.
- Model: `DEFAULT_MODEL` in `app.py`.
- API base URL: `DEFAULT_BASE_URL` in `app.py`.
- Browser profile: `PROFILE_DIR` in `app.py`.
- Logs: `LOG_DIR` in `app.py`.

## Notes

- The app binds Gradio to `127.0.0.1`; do not enable `share=True` for a local-only app.
- The bundled Chromium increases the app size significantly.
- Keep API keys out of source code and `.env` files that might be shared.
