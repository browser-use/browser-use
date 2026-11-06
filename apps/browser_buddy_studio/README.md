# BrowserBuddy Studio

A product-style macOS desktop UI for browser-use.

## Stack

- **React + Vite** frontend
- **FastAPI** local backend
- **PyWebView** native macOS window
- **browser-use** agent runtime
- **PyInstaller** `.app` + DMG packaging

No Node.js is required at runtime. React is built into static files and served by FastAPI inside the app.

## Development

```bash
./dev.sh
```

This starts:

- FastAPI on `http://127.0.0.1:8765`
- Vite on `http://127.0.0.1:5173`

Open the Vite URL. The frontend proxies `/api` and `/artifacts` to FastAPI.

## Build a macOS app

```bash
./build_mac.sh
```

Outputs:

```text
dist/BrowserBuddy.app
dist/BrowserBuddy.dmg
```

Useful variants:

```bash
CONSOLE=1 ./build_mac.sh          # keep a terminal for debugging
BUNDLE_CHROMIUM=1 ./build_mac.sh  # bundle Chromium for friends without Chrome
```

## Features

- Sidebar with persistent task history (stored under Application Support)
- Command-style task composer
- Live execution timeline over SSE
- Markdown result rendering
- Link preview cards with `og:image`
- Attachment and PDF/image previews
- Multi-provider model settings:
  - DeepSeek
  - Browser Use
  - OpenAI
  - Anthropic
  - Google Gemini
- Per-provider API keys stored in macOS Keychain
- Light/dark themes
- Keyboard shortcuts:
  - `⌘N` new task
  - `⌘Enter` run
  - `Esc` stop

## Architecture

```text
PyWebView window
  └── React static UI
        └── FastAPI on 127.0.0.1:<random port>
              ├── /api/run
              ├── /api/stop
              ├── /api/events (SSE)
              ├── /api/state
              └── /artifacts
                    └── browser-use Agent
```

## Notes

- The app is macOS-only because it uses `sips` for PDF previews and macOS Keychain.
- The backend binds to loopback only.
- API keys are never written to the frontend bundle.
- Task history and UI preferences persist across app restarts in `~/Library/Application Support/BrowserBuddy/`.
- Unsigned builds require right-click → Open on first launch.
