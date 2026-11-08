# BrowserBuddy Studio

A product-style macOS desktop UI for browser-use.

## Stack

- **React + Vite** frontend
- **FastAPI** local backend
- **PyWebView** native macOS window
- **browser-use** agent runtime
- **PyInstaller** `.app` + DMG packaging

No Node.js or Python is required on the user's Mac at runtime. React is built
into static files and CPython plus all dependencies are embedded by PyInstaller.
Chrome is used when present; set `BUNDLE_CHROMIUM=1` to ship Chromium inside the
app for Macs that don't have any Chromium-based browser.

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

What the build guarantees:

- **No Python on the user's Mac.** PyInstaller embeds CPython and every Python
  dependency inside `BrowserBuddy.app`; the build fails if `libpython` is missing.
- **Chrome is detected, not blindly bundled.** `BUNDLE_CHROMIUM=auto` (default)
  checks this Mac for Chrome/Chromium/Brave/Edge and skips the 185 MB Chromium
  download when one is found. Set `BUNDLE_CHROMIUM=1` to force Chromium into
  `Contents/Frameworks/ms-playwright` (a build that works on any Mac), or
  `BUNDLE_CHROMIUM=0` to never bundle it.
- **Drag-to-install.** The DMG contains the app plus an `Applications` symlink and
  a Finder layout, so installing is: open DMG → drag the icon into Applications.
- **No installer, no daemons, no root prompt.** The app runs as a normal user
  process and cleans up the browser it spawned when it quits.
- **Smoke test.** After packaging, the build launches the frozen binary with a
  clean data directory and waits for `/api/health`; a broken bundle fails the build
  instead of shipping.

Useful variants:

```bash
CONSOLE=1 ./build_mac.sh            # keep a terminal for debugging
BUNDLE_CHROMIUM=1 ./build_mac.sh    # always ship Chromium (works on any Mac)
BUNDLE_CHROMIUM=0 ./build_mac.sh    # never bundle; require the target Mac's Chrome
SKIP_SMOKE_TEST=1 ./build_mac.sh    # skip the frozen-app health check
APP_VERSION=1.2.0 ./build_mac.sh    # set CFBundleShortVersionString
```

Chromium is downloaded from `cdn.npmmirror.com` by default because the official
Playwright CDN redirects to Google storage, which is unreachable in mainland
China. Use the official host when you prefer it:

```bash
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.playwright.dev ./build_mac.sh
```

Signing and notarization:

```bash
APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
APPLE_ID="you@example.com" \
APPLE_TEAM_ID="TEAMID" \
APPLE_APP_PASSWORD="app-specific-password" \
./build_mac.sh
```

Without an identity the build is ad-hoc signed; on another Mac the first launch
needs right-click → Open → Open.

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
- Per-provider API keys stored in a private local file
- Configurable search engine with automatic regional fallback (Bing 中国 → 搜狗 → 百度 → 360 → Bing 国际 → Google → DuckDuckGo)
- Persistent login for Taobao, JD, Xiaohongshu, and Douyin
- ChatGPT-style light/dark themes (neutral gray + green accent, light by default)
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
              ├── /api/logins
              └── /artifacts
                    └── browser-use Agent
```

## Platform login

Use the sidebar **登录平台** button to open Taobao, JD, Xiaohongshu, or Douyin in a visible browser. The user completes QR or password login directly in the browser; the app never stores the password.

Login detection and status:

- The backend watches the browser's cookies every second. As soon as a real login cookie appears (`unb` for Taobao, `thor` for JD, `web_session` for Xiaohongshu, `sessionid` for Douyin), it exports the cookie jar, closes the login window automatically, and shows **“淘宝登录成功”**.
- If the scan fails, the user can simply close the browser window; the app treats it as cancelled and never blocks the UI.
- Platforms are considered signed in only while a live auth cookie exists, so expired sessions show **未登录** instead of a stale success.
- Login status is shown in the login dialog, as a badge on the sidebar button, and in **设置 → 平台登录**.
- Cookies are saved to `~/Library/Application Support/BrowserBuddy/storage_state.json`, and login timestamps to `platform_logins.json`. Cookies are also re-exported after every browser task and source-link view, so refreshed sessions are not lost and users do not have to scan again after restarting the app.

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

## Install and uninstall

Install:

1. Open `BrowserBuddy.dmg`.
2. Drag **BrowserBuddy** onto the **Applications** shortcut.

Uninstall:

1. Quit the app (⌘Q). The browser window it opened is closed automatically.
2. Drag `BrowserBuddy.app` from Applications to the Trash.
3. Optional: open 设置 → 数据与卸载 → **彻底删除本地数据**, or drag
   `~/Library/Application Support/BrowserBuddy` to the Trash.

Everything the app writes lives in that one folder (`logs`, chat history,
downloads, browser profile, saved API keys). There is no installer, no launch
agent, no kernel extension, and no system-wide state.

## Notes

- The app is macOS-only because it uses macOS-specific paths and `sips` for PDF previews.
- The backend binds to loopback only.
- API keys are never written to the frontend bundle.
- Task history, logs, UI preferences, downloads, and the browser profile all persist under a single root: `~/Library/Application Support/BrowserBuddy/`. Set `BROWSER_BUDDY_DATA_DIR=/some/path` to relocate it (useful for portable builds).
- Browser downloads are saved inside the app data folder: `~/Library/Application Support/BrowserBuddy/downloads`. Open it from the sidebar → 下载文件夹, the result toolbar, or Settings → 打开下载文件夹. The app does not touch the system `~/Downloads` folder, so macOS does not ask for Downloads permission.
- For mainland China, choose a search engine in Settings. The default **自动** mode prioritizes Bing 中国, then falls back to 搜狗, 百度, 360, Bing 国际, Google, and DuckDuckGo. Engines that redirect to CAPTCHA pages are skipped.
- Xiaohongshu and Douyin are not search-engine options. Log in once with **登录平台**, then ask the agent to search directly on the site (for example, "打开小红书搜索露营装备"). The agent uses the saved login state and searches inside the platform.
- Xiaohongshu and Douyin source cards open in the app's logged-in browser instead of the system browser, so notes and videos play without a mobile QR scan. Xiaohongshu note URLs must keep their `xsec_token`; the app reuses the token from the URLs visited during the task when the model returns a bare `/explore/<id>` link.
- The source browser is a normal Chrome window: close it with the window's close button when finished. Clicking another Xiaohongshu or Douyin source opens a fresh window, or reuses the current one if it is still open.
- Unsigned (ad-hoc signed) builds require right-click → Open on first launch. Signed and notarized builds open normally.

## API keys

API keys are stored per provider in `~/Library/Application Support/BrowserBuddy/secrets.json` with `0600` permissions. They are kept out of the frontend bundle and logs. The backend caches keys in memory so the file is read once per app session.

This local storage avoids macOS Keychain access prompts, which are unreliable for unsigned or ad-hoc signed development builds.
