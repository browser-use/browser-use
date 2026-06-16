"""Success-preferring merge of one captured run into another.

Both runs must be HF-style dirs: ``<dir>/data/<source>__<id>/`` task folders plus a
``<dir>/metadata.jsonl`` index. For each task present in both, keep the target's
trajectory if it already **succeeded**; otherwise take the incoming run's (so a
success replaces a failure, and a new failure replaces an old failure — i.e. the
merged set is the union of successes, with incoming winning ties only when the
target failed). Tasks on only one side are kept as-is. The target's ``data/``,
``metadata.jsonl`` and ``run_summary.json`` are updated in place; the incoming run
is left untouched (folders are copied, not moved).

	python -m simulator.scripts.merge_runs <target_dir> <incoming_dir>
	python -m simulator.scripts.merge_runs <target_dir> <incoming_dir> --upload <repo_id>

``--upload`` also reconciles the HuggingFace dataset repo: it deletes files that no
longer exist locally (stale steps from replaced trajectories — ``upload_large_folder``
only adds/updates, never deletes) and then re-uploads (resumable). Requires
``huggingface_hub`` and a logged-in token.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _load_meta(run_dir: Path) -> tuple[dict[str, dict], list[str]]:
	mp = run_dir / 'metadata.jsonl'
	if not mp.exists():
		raise SystemExit(f'{mp} not found — merge needs an HF-style run with a metadata.jsonl index')
	rows, order = {}, []
	for line in mp.read_text().splitlines():
		line = line.strip()
		if not line:
			continue
		r = json.loads(line)
		key = r['trajectory_dir'].split('/')[-1]
		rows[key] = r
		order.append(key)
	return rows, order


def _succeeded(row: dict) -> bool:
	return row.get('success') is True


def _replace_folder(target_data: Path, incoming_data: Path, key: str) -> None:
	src, dst = incoming_data / key, target_data / key
	if not src.is_dir():
		raise SystemExit(f'incoming folder missing: {src}')
	if dst.exists():
		shutil.rmtree(dst)
	shutil.copytree(src, dst)


def merge(target: Path, incoming: Path) -> dict:
	old, old_order = _load_meta(target)
	new, _ = _load_meta(incoming)
	target_data, incoming_data = target / 'data', incoming / 'data'

	both = [k for k in old_order if k in new]
	only_target = [k for k in old_order if k not in new]
	only_incoming = [k for k in new if k not in old]

	took_new, kept_old = [], []
	for k in both:
		if _succeeded(old[k]):
			kept_old.append(k)  # target already succeeded -> keep it
		else:
			_replace_folder(target_data, incoming_data, k)
			took_new.append(k)
	for k in only_incoming:  # brand-new tasks: bring them in
		_replace_folder(target_data, incoming_data, k)

	# rebuild metadata: winning row per task, target order then incoming-only appended
	merged_rows = {}
	for k in old_order:
		merged_rows[k] = old[k] if (_succeeded(old[k]) or k not in new) else new[k]
	for k in only_incoming:
		merged_rows[k] = new[k]
	order = old_order + only_incoming
	(target / 'metadata.jsonl').write_text('\n'.join(json.dumps(merged_rows[k], ensure_ascii=False) for k in order) + '\n')

	def succ(keys):
		return sum(_succeeded(merged_rows[k]) for k in keys)

	stats = {
		'target': target.name,
		'incoming': incoming.name,
		'tasks': len(order),
		'kept_old': len(kept_old),
		'took_new': len(took_new),
		'added_from_incoming': len(only_incoming),
		'only_target': len(only_target),
		'target_success': sum(_succeeded(old[k]) for k in old_order),
		'incoming_success': sum(_succeeded(new[k]) for k in new),
		'merged_success': succ(order),
		'by_source': {},
	}
	for src in sorted({merged_rows[k]['source'] for k in order}):
		ks = [k for k in order if merged_rows[k]['source'] == src]
		stats['by_source'][src] = [succ(ks), len(ks)]

	summary = {
		'dataset': target.name,
		'task_count': stats['tasks'],
		'merge': {
			'rule': 'per task: keep target if it succeeded; else take incoming (success-preferring)',
			'incoming': incoming.name,
			**{k: stats[k] for k in ('kept_old', 'took_new', 'added_from_incoming', 'only_target')},
			**{k: stats[k] for k in ('target_success', 'incoming_success', 'merged_success')},
		},
		'success': {'overall': [stats['merged_success'], stats['tasks']], **stats['by_source']},
	}
	(target / 'run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
	return stats


def upload(target: Path, repo_id: str) -> None:
	from huggingface_hub import CommitOperationDelete, HfApi

	api = HfApi()
	remote = set(api.list_repo_files(repo_id, repo_type='dataset'))
	local = set()
	for p in target.rglob('*'):
		if p.is_file():
			rel = p.relative_to(target).as_posix()
			if rel.startswith('.git/') or rel.startswith('.cache/'):
				continue
			local.add(rel)
	orphans = sorted(remote - local)
	if orphans:
		print(f'deleting {len(orphans)} stale remote files (replaced trajectories)...', flush=True)
		ops = [CommitOperationDelete(path_in_repo=o) for o in orphans]
		batch = 2000
		for i in range(0, len(ops), batch):
			api.create_commit(
				repo_id=repo_id,
				repo_type='dataset',
				operations=ops[i : i + batch],
				commit_message='merge_runs: remove stale steps from replaced trajectories',
			)
	print('uploading (resumable upload_large_folder)...', flush=True)
	api.upload_large_folder(
		repo_id=repo_id,
		repo_type='dataset',
		folder_path=str(target),
		ignore_patterns=['.git/*', '.git/**', '**/.git/*'],
	)
	print('upload done')


def main() -> None:
	ap = argparse.ArgumentParser(prog='python -m simulator.scripts.merge_runs')
	ap.add_argument('target', type=Path, help='HF-style run dir to merge INTO (updated in place).')
	ap.add_argument('incoming', type=Path, help='HF-style run dir to merge FROM (left untouched).')
	ap.add_argument('--upload', metavar='REPO_ID', default=None, help='Also reconcile + upload to this HF dataset repo.')
	a = ap.parse_args()
	s = merge(a.target, a.incoming)
	n = s['tasks']
	print(f'merged {n} tasks | kept_old {s["kept_old"]} | took_new {s["took_new"]} | added {s["added_from_incoming"]}')
	print(
		f'success: target {s["target_success"]} | incoming {s["incoming_success"]} | MERGED {s["merged_success"]} ({s["merged_success"] / n * 100:.1f}%)'
	)
	for src, (ns, nt) in s['by_source'].items():
		print(f'  {src}: {ns}/{nt} ({ns / nt * 100:.1f}%)')
	if a.upload:
		upload(a.target, a.upload)


if __name__ == '__main__':
	main()
