# Browser Configuration (browser-use 1.0)

## Table of Contents
- [Pick a browser](#pick-a-browser)
- [All parameters](#all-parameters)
- [Logins](#logins)
- [Your own Chrome](#your-own-chrome)
- [Cloud browser](#cloud-browser)

---

## Pick a browser

```python
from browser_use import Agent, Browser

Browser()                                   # Browser Use Cloud browser (default; needs BROWSER_USE_API_KEY)
Browser('chromium')                         # fresh local Chrome/Chromium/Edge, own temp profile, deleted afterwards
Browser('chromium', headless=True)          # headless (default: headless only when there is no display)
Browser('chromium', user_data_dir='~/bu')   # a dedicated profile dir kept between runs (log in once)
Browser('chrome')                           # the Chrome you have open, with your logins
Browser('chrome', profile='Work')           # a new Chrome on a temporary copy of your Chrome profile 'Work'

agent = Agent(task='Search for Browser Use', browser=Browser('chromium'))
await agent.run()
```

`Browser(local=True)` and the 0.x `Browser(use_cloud=False)` are `Browser('chromium')`.

| | Logins | Parallel agents | Servers / Docker / CI |
|---|---|---|---|
| `Browser()` | `cloud_profile_id` | yes | yes |
| `Browser('chromium')` | none, or its `user_data_dir` | yes (own browser + daemon each) | yes (headless) |
| `Browser('chrome')` | yours | no (one shared daemon, one tab) | no |
| `Browser('chrome', profile=...)` | yours (a copy) | yes | if Chrome and the profile are there |

## All parameters

- `kind` (first argument): `'cloud'` (default), `'chromium'`, `'chrome'`
- `headless`: `'chromium'` and `'chrome'` + `profile`. `None` (default) = headless only without a display
- `executable_path`: browser binary for launched browsers. Default: `BH_CHROME_PATH` / `CHROME_PATH`, then the
  installed Chrome, Chromium or Edge (Google Chrome only for `profile=`)
- `user_data_dir`: `'chromium'` only. Chrome's own default profile dir raises (Chrome 136+ refuses remote debugging on it)
- `profile`: `'chrome'` only. Display name (`'Work'`) or directory (`'Profile 1'`)
- `keep_alive`: `Agent.run()` leaves the browser running; stop it with `await browser.stop()`
- `cloud_profile_id`, `cloud_proxy_country_code` (default `'us'`, `None` = off), `cloud_timeout` (minutes),
  `live_view`: cloud only

Options that do not fit the browser raise `ValueError` before anything starts. 0.x options that are gone
(`window_size`, `allowed_domains`, `storage_state`, `proxy`, ...) raise `TypeError` naming the 1.0 answer; see
MIGRATING.md. Window size, user agent, headers and permissions: say it in the task, the agent sends the CDP command.

## Logins

| Approach | How |
|---|---|
| Your Chrome | `Browser('chrome')` (attach) or `Browser('chrome', profile='Work')` (copy) |
| A local profile of the agent's own | `Browser('chromium', user_data_dir='~/bu-profile')`, log in once |
| Cloud profile | `Browser(cloud_profile_id='work')` |
| Passwords | `Agent(task, sensitive_data={'password': '...'})`; the model types it with `type_secret('password')` |
| TOTP 2FA | a `sensitive_data` key ending in `bu_2fa_code` holds the TOTP secret; the current 6-digit code is typed |

`Browser('chrome')` and `profile=` hand the agent your real cookies. Use `Browser('chromium')` or the cloud browser
for untrusted tasks.

## Your own Chrome

`Browser('chrome')` attaches through browser-harness (the same Chrome the `browser-use` CLI drives):

1. Turn on chrome://inspect/#remote-debugging once ("Allow remote debugging for this browser instance").
2. Click Allow on Chrome's "Allow remote debugging?" prompt when the agent connects (macOS: or run
   `browser-harness mac-approve`). The start fails after 120 s without it.
3. Several browsers with remote debugging on: Google Chrome wins; with none of them Chrome it raises instead of guessing.

`Browser('chrome', profile='Work')` needs none of that: it copies `Local State` and the profile (minus caches) into a
temp dir and launches Google Chrome on it. Your Chrome can stay open. Logins made during the run are not written back.

## Cloud browser

```python
browser = Browser(
    cloud_profile_id='your-profile-id-or-name',
    cloud_proxy_country_code='us',  # None turns the proxy off
    cloud_timeout=60,               # minutes, 1-240
)
```

Key: `browser-use auth login` or `BROWSER_USE_API_KEY` from https://cloud.browser-use.com/settings?tab=api-keys
