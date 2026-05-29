"""Task models and loaders for WebVoyager + GAIA-web, with reference answers.

Two datasets ship in the WebVoyager repo (both included here):
  - webvoyager_data.jsonl : 643 tasks across 15 live sites. Reference answers live
    separately in reference_answer.json, keyed by site -> answers[id].
  - gaia_web.jsonl        : 90 web tasks from GAIA. Each row carries its own
    ground-truth "Final answer" inline.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pydantic import BaseModel

from simulator.config import GAIA_JSONL, REFERENCE_JSON, WEBVOYAGER_JSONL


class WebVoyagerTask(BaseModel):
	id: str
	site: str
	question: str
	start_url: str
	source: str = 'webvoyager'  # 'webvoyager' | 'gaia'
	reference_answer: str | None = None
	reference_type: str | None = None  # 'golden' | 'possible' | 'exact' | 'gaia' | ...
	reference_notice: str | None = None

	@property
	def folder_name(self) -> str:
		"""Filesystem-safe folder name for this task."""
		return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in f'{self.source}__{self.id}')


def _reference_index(path: Path = REFERENCE_JSON) -> dict[str, dict[int, tuple]]:
	"""site -> {answer_id: (ans, type, notice)} from reference_answer.json."""
	if not path.exists():
		return {}
	idx: dict[str, dict[int, tuple]] = {}
	for site, blk in json.loads(path.read_text()).items():
		notice = blk.get('notice')
		idx[site] = {a['id']: (a.get('ans'), a.get('type'), notice) for a in blk.get('answers', [])}
	return idx


def load_webvoyager_tasks(path: Path = WEBVOYAGER_JSONL) -> list[WebVoyagerTask]:
	ref = _reference_index()
	out = []
	for line in path.read_text().splitlines():
		if not line.strip():
			continue
		r = json.loads(line)
		site = r['web_name']
		try:
			aid = int(str(r['id']).split('--')[-1])
		except ValueError:
			aid = -1
		ans, typ, notice = ref.get(site, {}).get(aid, (None, None, None))
		out.append(
			WebVoyagerTask(
				id=r['id'],
				site=site,
				question=r['ques'],
				start_url=r['web'],
				source='webvoyager',
				reference_answer=ans,
				reference_type=typ,
				reference_notice=notice,
			)
		)
	return out


def load_gaia_tasks(path: Path = GAIA_JSONL) -> list[WebVoyagerTask]:
	out = []
	for line in path.read_text().splitlines():
		if not line.strip():
			continue
		r = json.loads(line)
		final = r.get('Final answer')
		out.append(
			WebVoyagerTask(
				id=r['id'],
				site=f'GAIA-L{r.get("Level", "?")}',
				question=r['ques'],
				start_url=r['web'],
				source='gaia',
				reference_answer=str(final) if final is not None else None,
				reference_type='gaia',
			)
		)
	return out


def load_tasks(n: int, shuffle: bool = False, seed: int = 0, source: str = 'both') -> list[WebVoyagerTask]:
	"""Load up to ``n`` tasks from the chosen source(s) (optionally shuffled first)."""
	tasks: list[WebVoyagerTask] = []
	if source in ('webvoyager', 'both'):
		tasks += load_webvoyager_tasks()
	if source in ('gaia', 'both'):
		tasks += load_gaia_tasks()
	if not tasks:
		raise SystemExit(f'no tasks loaded for source={source!r}')
	if shuffle:
		random.Random(seed).shuffle(tasks)
	return tasks[:n]
