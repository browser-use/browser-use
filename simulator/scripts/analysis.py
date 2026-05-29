"""WebArena vs WebVoyager context-length experiment.

python -m simulator.scripts.analysis structure   # task/site structure of both datasets
python -m simulator.scripts.analysis measure      # measure start-page context length (uses a browser)
python -m simulator.scripts.analysis compare       # combine measurements + verdict
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from simulator.config import RUNS_DIR, WEBARENA_JSON, WEBVOYAGER_JSONL

OUT_DIR = RUNS_DIR / 'analysis'
BLOCKED_AX = 50  # a real homepage has hundreds of AX nodes; fewer => likely a bot wall

# Public instances of the same software WebArena self-hosts (weights = start_url counts).
WEBARENA_PROXY_PAGES = [
	{'site': 'shopping (Magento/Luma proxy)', 'url': 'https://magento.softwaretestingboard.com/', 'weight': 192},
	{'site': 'gitlab (public project proxy)', 'url': 'https://gitlab.com/gitlab-org/gitlab-foss', 'weight': 196},
	{'site': 'map (OpenStreetMap)', 'url': 'https://www.openstreetmap.org/', 'weight': 128},
	{'site': 'reddit (Postmill demo proxy)', 'url': 'https://postmill.xyz/', 'weight': 114},
	{'site': 'wikipedia (scoped wiki proxy)', 'url': 'https://en.wikipedia.org/wiki/Main_Page', 'weight': 23},
]


# --- structure ------------------------------------------------------------ #
def structure() -> None:
	wv = [json.loads(line) for line in WEBVOYAGER_JSONL.read_text().splitlines() if line.strip()]
	wa = json.loads(WEBARENA_JSON.read_text())
	print(f'WebVoyager: {len(wv)} tasks   |   WebArena: {len(wa)} tasks\n')

	print('--- WebVoyager: tasks per site (all start at the homepage) ---')
	for site, n in Counter(t['web_name'] for t in wv).most_common():
		print(f'  {site:22s} {n:4d}')

	print('\n--- WebArena: tasks per site ---')
	wa_sites: Counter = Counter()
	for t in wa:
		for s in t['sites']:
			wa_sites[s] += 1
	for site, n in wa_sites.most_common():
		print(f'  {site:22s} {n:4d}')


# --- measure (uses a browser) --------------------------------------------- #
def _webvoyager_pages() -> list[dict]:
	rows = [json.loads(line) for line in WEBVOYAGER_JSONL.read_text().splitlines() if line.strip()]
	c = Counter((r['web_name'], r['web']) for r in rows)
	return [{'site': name, 'url': url, 'weight': n} for (name, url), n in c.most_common()]


async def _measure(pages: list[dict], out_path: Path) -> None:
	import tiktoken

	from browser_use import Browser

	enc = tiktoken.get_encoding('o200k_base')
	out_path.parent.mkdir(parents=True, exist_ok=True)

	async def ev(b, expr):
		cdp = await b.get_or_create_cdp_session()
		r = await cdp.cdp_client.send.Runtime.evaluate(
			params={'expression': expr, 'returnByValue': True, 'awaitPromise': True}, session_id=cdp.session_id
		)
		return None if r.get('exceptionDetails') else r.get('result', {}).get('value')

	b = Browser(headless=True)
	await b.start()
	results = []
	try:
		for i, p in enumerate(pages, 1):
			print(f'[{i}/{len(pages)}] {p["site"]:30s} {p["url"]}', flush=True)
			try:
				cdp = await b.get_or_create_cdp_session()
				await cdp.cdp_client.send.Page.navigate(params={'url': p['url']}, session_id=cdp.session_id)
				await asyncio.sleep(5.0)
				text = await ev(b, '(document.body && document.body.innerText) || ""') or ''
				try:
					ax = len((await cdp.cdp_client.send.Accessibility.getFullAXTree(session_id=cdp.session_id)).get('nodes', []))
				except Exception:  # noqa: BLE001
					ax = None
				rec = {**p, 'text_tokens': len(enc.encode(text, disallowed_special=())), 'ax_nodes': ax}
			except Exception as e:  # noqa: BLE001
				rec = {**p, 'error': str(e)[:200]}
			results.append(rec)
	finally:
		await b.stop()
	out_path.write_text(json.dumps(results, indent=2))
	print(f'wrote {out_path}')


async def measure() -> None:
	await _measure(_webvoyager_pages(), OUT_DIR / 'webvoyager_results.json')
	await _measure(WEBARENA_PROXY_PAGES, OUT_DIR / 'webarena_proxy_results.json')


# --- compare -------------------------------------------------------------- #
def _wavg(rows: list[dict], key: str) -> float:
	rows = [r for r in rows if r.get(key) is not None and (r.get('ax_nodes') or 0) >= BLOCKED_AX]
	w = sum(r['weight'] for r in rows)
	return (sum(r[key] * r['weight'] for r in rows) / w) if w else 0.0


def compare() -> None:
	wv = json.loads((OUT_DIR / 'webvoyager_results.json').read_text()) if (OUT_DIR / 'webvoyager_results.json').exists() else []
	wa = (
		json.loads((OUT_DIR / 'webarena_proxy_results.json').read_text())
		if (OUT_DIR / 'webarena_proxy_results.json').exists()
		else []
	)
	if not (wv and wa):
		print('missing measurements — run `python -m simulator.scripts.analysis measure` first')
		return
	for metric in ('text_tokens', 'ax_nodes'):
		v, a = _wavg(wv, metric), _wavg(wa, metric)
		longer = 'WebVoyager' if v > a else 'WebArena'
		ratio = (max(v, a) / min(v, a)) if min(v, a) else float('inf')
		print(f'  {metric:11s}: WebVoyager={v:8.0f}  WebArena(proxy)={a:8.0f}  -> {longer} longer ({ratio:.1f}x)')


def main() -> None:
	ap = argparse.ArgumentParser(prog='python -m simulator.scripts.analysis')
	ap.add_argument('cmd', choices=['structure', 'measure', 'compare'])
	a = ap.parse_args()
	if a.cmd == 'structure':
		structure()
	elif a.cmd == 'measure':
		asyncio.run(measure())
	else:
		compare()


if __name__ == '__main__':
	main()
