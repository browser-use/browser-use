from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import unquote

from .config import BROWSER_STATE_FILE, PLATFORM_LOGINS_FILE

# A platform is considered signed in when at least one of these cookies exists
# for the matching domain. These cookies are only issued after a real login.
PLATFORMS: dict[str, dict[str, Any]] = {
	'taobao': {
		'label': '淘宝',
		'domains': ('taobao.com', 'tmall.com'),
		'auth_cookies': ('unb', 'tracknick'),
		'account_cookies': ('tracknick', '_nk_'),
	},
	'jd': {
		'label': '京东',
		'domains': ('jd.com',),
		'auth_cookies': ('thor', 'pt_key'),
		'account_cookies': ('pin', 'pt_pin'),
	},
	'xiaohongshu': {
		'label': '小红书',
		'domains': ('xiaohongshu.com',),
		'auth_cookies': ('web_session',),
		'account_cookies': (),
	},
	'douyin': {
		'label': '抖音',
		'domains': ('douyin.com',),
		'auth_cookies': ('sessionid', 'sid_tt'),
		'account_cookies': ('nickname', 'unique_id'),
	},
}


def _domain_matches(domain: str, domains: tuple[str, ...]) -> bool:
	normalized = (domain or '').lstrip('.').lower()
	return any(normalized == item or normalized.endswith(f'.{item}') for item in domains)


def _cookie_is_live(cookie: dict[str, Any], now: float) -> bool:
	expires = cookie.get('expires', -1)
	if expires in (None, -1, 0):
		return True
	try:
		return float(expires) > now
	except (TypeError, ValueError):
		return True


def _matching_cookies(cookies: list[dict[str, Any]], site: str) -> list[dict[str, Any]]:
	info = PLATFORMS.get(site)
	if not info:
		return []
	names = set(info['auth_cookies'])
	return [
		cookie
		for cookie in cookies
		if cookie.get('name') in names and _domain_matches(str(cookie.get('domain', '')), info['domains'])
	]


def has_auth_cookie(cookies: list[dict[str, Any]], site: str, now: float | None = None) -> bool:
	"""Return True when a live login cookie for this platform is present."""
	now = time.time() if now is None else now
	return any(_cookie_is_live(cookie, now) for cookie in _matching_cookies(cookies, site))


def account_from_cookies(cookies: list[dict[str, Any]], site: str) -> str:
	info = PLATFORMS.get(site)
	if not info:
		return ''
	names = set(info.get('account_cookies') or ())
	for cookie in cookies:
		if cookie.get('name') not in names:
			continue
		if not _domain_matches(str(cookie.get('domain', '')), info['domains']):
			continue
		value = str(cookie.get('value') or '').strip()
		if value:
			return unquote(value)
	return ''


def read_cookies() -> list[dict[str, Any]]:
	try:
		payload = json.loads(BROWSER_STATE_FILE.read_text(encoding='utf-8'))
	except Exception:
		return []
	cookies = payload.get('cookies') if isinstance(payload, dict) else None
	return [cookie for cookie in cookies if isinstance(cookie, dict)] if isinstance(cookies, list) else []


def read_records() -> dict[str, dict[str, Any]]:
	try:
		payload = json.loads(PLATFORM_LOGINS_FILE.read_text(encoding='utf-8'))
	except Exception:
		return {}
	return payload if isinstance(payload, dict) else {}


def record_login(site: str, success: bool) -> None:
	"""Persist the last successful login time (cookies remain the source of truth)."""
	if site not in PLATFORMS:
		return
	records = read_records()
	entry = records.get(site) if isinstance(records.get(site), dict) else {}
	entry['logged_in'] = bool(success)
	entry['updated_at'] = time.time()
	if success:
		entry['last_login_at'] = entry['updated_at']
	records[site] = entry
	try:
		PLATFORM_LOGINS_FILE.parent.mkdir(parents=True, exist_ok=True)
		temp = PLATFORM_LOGINS_FILE.with_suffix('.tmp')
		temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
		temp.replace(PLATFORM_LOGINS_FILE)
	except Exception:
		pass


def platform_status() -> list[dict[str, Any]]:
	"""Current login state for every supported platform, for the UI."""
	cookies = read_cookies()
	records = read_records()
	now = time.time()
	result: list[dict[str, Any]] = []
	for site, info in PLATFORMS.items():
		entry = records.get(site) if isinstance(records.get(site), dict) else {}
		alive = has_auth_cookie(cookies, site, now)
		result.append(
			{
				'site': site,
				'label': info['label'],
				'logged_in': alive,
				'account': account_from_cookies(cookies, site) or str(entry.get('account') or ''),
				'last_login_at': entry.get('last_login_at'),
			}
		)
	return result
