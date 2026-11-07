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

- ChatGPT-style conversation threads with persistent history
- Intent detection: greetings and pure chat replies do not start a browser; only browser-related requests do
- Follow-up prompts stay in the same conversation, not a separate task screen
- Follow-up tasks that reuse the previous result, sources, and links
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
- Configurable search engine with automatic regional fallback (Bing 中国 → 搜狗 → 百度 → 360 → Bing 国际 → Google → DuckDuckGo)
- Persistent login for Taobao, JD, Xiaohongshu, and Douyin
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

## Platform login

Use the sidebar **登录平台** button to open Taobao, JD, Xiaohongshu, or Douyin in a visible browser. The user completes QR or password login directly in the browser; the app never stores the password. Cookies are persisted in the dedicated browser profile and exported to `~/Library/Application Support/BrowserBuddy/storage_state.json`, so platform logins survive task restarts.

If a task hits login, QR code, CAPTCHA, SMS verification, or payment confirmation, the agent calls `request_human_help`. The UI pauses the task, shows the reason, and waits for **继续任务** or **取消任务**. This requires the browser to be visible (turn off headless mode).

## Follow-up tasks

Follow-up prompts are sent in the same conversation input. Each new message automatically includes prior user tasks, assistant results, source links, and file names as context. This supports flows like:

1. Find product links.
2. Continue to read reviews for those products.
3. Continue to add a product to the cart.

Payment confirmation still requires the human-intervention flow and is never automated.

## Chat vs browser tasks

Before each message, the backend classifies intent:

- Greetings, small talk, explanations, writing, translation, math → chat reply only, no browser.
- Open/search/click/login/download/extract/shop/compare → browser agent.

This avoids starting Chromium for messages like “hi” or “你好”.

## Notes

- The app is macOS-only because it uses `sips` for PDF previews and macOS Keychain.
- The backend binds to loopback only.
- API keys are never written to the frontend bundle.
- Task history and UI preferences persist across app restarts in `~/Library/Application Support/BrowserBuddy/`.
- Browser downloads are saved to the macOS default Downloads folder: `~/Downloads`. Open it from the sidebar → 下载文件夹, the result toolbar, or Settings → 打开下载文件夹.
- For mainland China, choose a search engine in Settings. The default **自动** mode prioritizes Bing 中国, then falls back to 搜狗, 百度, 360, Bing 国际, Google, and DuckDuckGo. Engines that redirect to CAPTCHA pages are skipped.
- Xiaohongshu and Douyin are not search-engine options. Log in once with **登录平台**, then ask the agent to search directly on the site (for example, "打开小红书搜索露营装备"). The agent uses the saved login state and searches inside the platform.
- Xiaohongshu and Douyin source cards open in the app's logged-in browser instead of the system browser, so notes and videos play without a mobile QR scan. Xiaohongshu note URLs must keep their `xsec_token`; the app reuses the token from the URLs visited during the task when the model returns a bare `/explore/<id>` link.
- The source browser is a normal Chrome window: close it with the window's close button when finished. Clicking another Xiaohongshu or Douyin source opens a fresh window, or reuses the current one if it is still open.
- Unsigned builds require right-click → Open on first launch.

## API keys

API keys are stored per provider in macOS Keychain. The backend caches keys in memory so a key is read from Keychain once per app session, not on every task.

On the first read, macOS may ask for Keychain access. Choose **Always Allow** to avoid future prompts for the same signed build. Ad-hoc signed development builds may prompt again after rebuilding because their code signature changes.
