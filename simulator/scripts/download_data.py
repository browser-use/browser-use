"""Download the task datasets the simulator needs into simulator/data/.

The raw datasets are third-party and gitignored (the repo ignores *.json/*.jsonl),
so fetch them once after cloning:

    python -m simulator.scripts.download_data          # skip files already present
    python -m simulator.scripts.download_data --force  # re-download everything
"""

from __future__ import annotations

import argparse

import httpx

from simulator.config import DATA_DIR

SOURCES = {
	'webvoyager_data.jsonl': 'https://raw.githubusercontent.com/MinorJerry/WebVoyager/main/data/WebVoyager_data.jsonl',
	'gaia_web.jsonl': 'https://raw.githubusercontent.com/MinorJerry/WebVoyager/main/data/GAIA_web.jsonl',
	'reference_answer.json': 'https://raw.githubusercontent.com/MinorJerry/WebVoyager/main/data/reference_answer.json',
	'webarena_test.raw.json': 'https://raw.githubusercontent.com/web-arena-x/webarena/main/config_files/test.raw.json',
}


def main() -> None:
	ap = argparse.ArgumentParser(prog='python -m simulator.scripts.download_data')
	ap.add_argument('--force', action='store_true', help='Re-download even if the file already exists.')
	args = ap.parse_args()

	DATA_DIR.mkdir(parents=True, exist_ok=True)
	for name, url in SOURCES.items():
		dest = DATA_DIR / name
		if dest.exists() and not args.force:
			print(f'  skip (exists): {name}')
			continue
		print(f'  downloading {name} ...', flush=True)
		resp = httpx.get(url, follow_redirects=True, timeout=60)
		resp.raise_for_status()
		dest.write_bytes(resp.content)
		print(f'  wrote {name} ({len(resp.content):,} bytes)')
	print(f'datasets in {DATA_DIR}')


if __name__ == '__main__':
	main()
