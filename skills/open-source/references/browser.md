# Browser Configuration

## Table of Contents
- [Basic Usage](#basic-usage)
- [All Parameters](#all-parameters)
- [Authentication Strategies](#authentication-strategies)
- [Real Browser Connection](#real-browser-connection)
- [Remote / Cloud Browser](#remote--cloud-browser)

---

## Basic Usage

```python
from browser_use import Agent, Browser, ChatBrowserUse

browser = Browser(
    headless=False,
    window_size={'width': 1000, 'height': 700},
)

agent = Agent(task='Search for Browser Use', browser=browser, llm=ChatBrowserUse())
await agent.run()
```

`Browser` is an alias for `BrowserSession` — same class.

## All Parameters

### Core
- `cdp_url`: CDP URL for existing browser (e.g., `"http://localhost:9222"`)

### Display & Appearance
- `headless` (default: `None`): Auto-detects display. `True`/`False`/`None`
- `window_size`: `{'width': 1920, 'height': 1080}` or `ViewportSize`
- `window_position` (default: `{'width': 0, 'height': 0}`)
- `viewport`: Content area size
- `no_viewport` (default: `None`): Disable viewport emulation
- `device_scale_factor`: DPI (`2.0` for retina)

### Browser Behavior
- `keep_alive` (default: `None`): Keep browser running after agent completes
- `allowed_domains`: Restrict navigation with patterns:
  - `'example.com'` → `https://example.com/*`
  - `'*.example.com'` → domain + subdomains
  - `'http*://example.com'` → both protocols
  - `'chrome-extension://*'` → extensions
  - TLD wildcards (`example.*`) NOT allowed
  - Auto-optimized to sets for 100+ domains (O(1) lookup)
- `prohibited_domains`: Block domains (same patterns). `allowed_domains` takes precedence
- `enable_default_extensions` (default: `True`): uBlock Origin, cookie handlers, ClearURLs
- `cross_origin_iframes` (default: `False`)
- `is_local` (default: `True`): `False` for remote browsers

### User Data & Profiles
- `user_data_dir` (default: auto temp): Profile data dir. `None` for incognito
- `profile_directory` (default: `'Default'`): Chrome profile name
- `storage_state`: Cookies/localStorage as file path or dict

### Network & Security
- `proxy`: `ProxySettings(server='http://host:8080', bypass='localhost', username='user', password='pass')`
- `permissions` (default: `['clipboardReadWrite', 'notifications']`)
- `headers`: HTTP headers for remote browsers

### Browser Launch
- `executable_path`: Custom browser path
- `channel`: `'chromium'`, `'chrome'`, `'chrome-beta'`, `'msedge'`
- `args`: Additional CLI args list
- `env`: Environment vars dict
- `chromium_sandbox` (default: `True` except Docker)
- `devtools` (default: `False`): Requires `headless=False`
- `ignore_default_args`: List or `True` for all

### Timing & Performance
- `minimum_wait_page_load_time` (default: `0.25`)
- `wait_for_network_idle_page_load_time` (default: `0.5`)
- `wait_between_actions` (default: `0.5`)

### AI Integration
- `highlight_elements` (default: `True`)
- `paint_order_filtering` (default: `True`): Remove hidden elements (experimental)

### Downloads & Files
- `accept_downloads` (default: `True`)
- `downloads_path`: Download directory
- `auto_download_pdfs` (default: `True`)

### Device Emulation
- `user_agent`: Custom user agent string
- `screen`: Screen size info

### Recording & Debugging
- `record_video_dir`: Save as `.mp4`
- `record_video_size` (default: ViewportSize)
- `record_video_framerate` (default: `30`)
- `record_har_path`: Network traces as `.har`
- `traces_dir`: Complete trace files
- `record_har_content` (default: `'embed'`): `'omit'`/`'embed'`/`'attach'`
- `record_har_mode` (default: `'full'`): `'full'`/`'minimal'`

### Advanced
- `disable_security` (default: `False`): **NOT RECOMMENDED**
- `deterministic_rendering` (default: `False`): **NOT RECOMMENDED**

### Class Methods

```python
# Auto-detect Chrome and first available profile
browser = Browser.from_system_chrome()
browser = Browser.from_system_chrome(profile_directory='Profile 5')

# List available profiles
profiles = Browser.list_chrome_profiles()
# [{'directory': 'Default', 'name': 'Person 1'}, {'directory': 'Profile 1', 'name': 'Work'}]
```

---

## Authentication Strategies

| Approach | Best For | Setup |
|----------|----------|-------|
| Real Browser | Personal automation, existing logins | Low |
| Storage State | Production, CI/CD, headless | Medium |
| TOTP 2FA | Authenticator apps | Low |
| Email/SMS 2FA | Email/SMS verification | Medium |

### Storage State Persistence

```python
# Export cookies/localStorage
await browser.export_storage_state('auth.json')

# Load on next run
browser = Browser(storage_state='auth.json')
```

Auto-saves periodically and on shutdown. Auto-loads and merges on startup.

### TOTP 2FA

Pass secret in `sensitive_data` with key ending in `bu_2fa_code`:

```python
agent = Agent(
    task="Login to my account",
    llm=llm,
    sensitive_data={
        'google_bu_2fa_code': 'JBSWY3DPEHPK3PXP'  # TOTP secret
    },
)
```

Agent generates fresh 6-digit codes on demand. Find secrets in:
- 1Password: Edit item → One-Time Password → Show secret
- Google Authenticator: "Can't scan it?" during setup
- Authy: Desktop app settings → Export

### Email/SMS 2FA

- **AgentMail**: Disposable inboxes for email verification
- **1Password SDK**: Retrieve codes from password manager
- **Gmail API**: Read 2FA codes (requires OAuth 2.0 setup)

### Security Best Practices

- Restrict domains: `Browser(allowed_domains=['*.example.com'])`
- Disable vision for sensitive pages: `Agent(use_vision=False)`
- Use storage state instead of passwords when possible

---

## Real Browser Connection

Use your existing Chrome with saved logins:

```python
# Auto-detect (recommended)
browser = Browser.from_system_chrome()

# Manual paths
browser = Browser(
    executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    user_data_dir='~/Library/Application Support/Google/Chrome',
    profile_directory='Default',
)
```

Close Chrome completely before running.

### Platform Paths

| Platform | executable_path | user_data_dir |
|----------|----------------|---------------|
| macOS | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` | `~/Library/Application Support/Google/Chrome` |
| Windows | `C:\Program Files\Google\Chrome\Application\chrome.exe` | `%LocalAppData%\Google\Chrome\User Data` |
| Linux | `/usr/bin/google-chrome` | `~/.config/google-chrome` |

---

## Remote / Cloud Browser

### Browser-Use Cloud (Recommended)

```python
# Simple
browser = Browser(use_cloud=True)

# Advanced — bypasses captchas, geo-restrictions
browser = Browser(
    cloud_profile_id='your-profile-id',
    cloud_proxy_country_code='us',  # us, uk, fr, it, jp, au, de, fi, ca, in
    cloud_timeout=30,               # minutes (free: 15, paid: 240)
)
```

**Prereqs:** `BROWSER_USE_API_KEY` env var from https://cloud.browser-use.com/new-api-key

### CDP URL (Any Provider)

```python
browser = Browser(cdp_url="http://remote-server:9222")
```

### With Proxy

```python
from browser_use.browser import ProxySettings

browser = Browser(
    proxy=ProxySettings(
        server="http://proxy-server:8080",
        username="proxy-user",
        password="proxy-pass"
    ),
    cdp_url="http://remote-server:9222"
)
```
