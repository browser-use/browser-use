"""Inspect a Rust browser-agent session in a local state.db.

Usage:
    uv run python examples/rust/inspect_rust_trace.py ~/.browser-use-terminal/state.db <session_id>
    uv run python examples/rust/inspect_rust_trace.py ~/.browser-use-terminal/state.db --latest

The script is intentionally dependency-free. It reads the Rust terminal SQLite
store and prints enough trace shape to debug reliability/cost regressions
without opening Laminar: model turns, browser_script/observe counts,
screenshots, token/cost totals, large tool outputs, artifacts, and a compact
timeline.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _expand(path: str) -> Path:
	return Path(path).expanduser()


def _json_loads(raw: str) -> dict[str, Any]:
	try:
		value = json.loads(raw)
	except json.JSONDecodeError:
		return {'_decode_error': raw[:500]}
	return value if isinstance(value, dict) else {'value': value}


def _short(value: Any, limit: int = 140) -> str:
	text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
	text = ' '.join(text.split())
	if len(text) <= limit:
		return text
	return text[: limit - 1] + '…'


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
	return event.get('payload') if isinstance(event.get('payload'), dict) else {}


def _tool_name(payload: dict[str, Any]) -> str:
	return str(payload.get('name') or payload.get('tool') or payload.get('tool_name') or '?')


def _tool_arguments(payload: dict[str, Any]) -> dict[str, Any]:
	args = payload.get('arguments')
	if isinstance(args, str):
		try:
			parsed = json.loads(args)
			return parsed if isinstance(parsed, dict) else {}
		except json.JSONDecodeError:
			return {}
	if isinstance(args, dict):
		return args
	return {}


def _payload_text_chars(payload: dict[str, Any]) -> int:
	total = 0
	for key in ('text', 'summary', 'data', 'outputs', 'extracted_content'):
		value = payload.get(key)
		if value is None:
			continue
		if isinstance(value, str):
			total += len(value)
		else:
			total += len(json.dumps(value, ensure_ascii=False))
	return total


def _input_context_tokens(payload: dict[str, Any]) -> int | None:
	for key in (
		'estimated_context_tokens',
		'context_tokens',
		'input_tokens_estimate',
		'estimated_input_tokens',
	):
		value = payload.get(key)
		if isinstance(value, int):
			return value
	return None


def _input_image_count(payload: dict[str, Any]) -> int | None:
	for key in ('input_image_count', 'image_count', 'images'):
		value = payload.get(key)
		if isinstance(value, int):
			return value
		if isinstance(value, list):
			return len(value)
	return None


def connect(path: Path) -> sqlite3.Connection:
	if not path.exists():
		raise FileNotFoundError(path)
	conn = sqlite3.connect(path)
	conn.row_factory = sqlite3.Row
	return conn


def latest_session_id(conn: sqlite3.Connection) -> str:
	row = conn.execute(
		'SELECT id FROM sessions ORDER BY updated_ms DESC, created_ms DESC LIMIT 1'
	).fetchone()
	if row is None:
		raise RuntimeError('no sessions found')
	return str(row['id'])


def load_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
	row = conn.execute(
		'SELECT id, parent_id, cwd, artifact_root, status, created_ms, updated_ms, '
		'agent_path, agent_nickname, agent_role FROM sessions WHERE id = ?',
		(session_id,),
	).fetchone()
	if row is None:
		raise RuntimeError(f'session not found: {session_id}')
	return dict(row)


def load_events(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
	rows = conn.execute(
		'SELECT seq, id, session_id, ts_ms, type, payload_json '
		'FROM events WHERE session_id = ? ORDER BY seq ASC',
		(session_id,),
	).fetchall()
	events: list[dict[str, Any]] = []
	for row in rows:
		event = dict(row)
		event['payload'] = _json_loads(str(event.pop('payload_json')))
		events.append(event)
	return events


def load_artifacts(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
	try:
		rows = conn.execute(
			'SELECT id, event_seq, kind, path, mime, bytes, created_ms, metadata_json '
			'FROM artifacts WHERE session_id = ? ORDER BY created_ms ASC',
			(session_id,),
		).fetchall()
	except sqlite3.OperationalError:
		return []
	artifacts: list[dict[str, Any]] = []
	for row in rows:
		artifact = dict(row)
		artifact['metadata'] = _json_loads(str(artifact.pop('metadata_json') or '{}'))
		artifacts.append(artifact)
	return artifacts


def summarize(events: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
	type_counts = Counter(str(event['type']) for event in events)
	tool_calls: Counter[str] = Counter()
	tool_outputs: Counter[str] = Counter()
	tool_text_chars: defaultdict[str, int] = defaultdict(int)
	largest_outputs: list[tuple[int, int, str, str]] = []
	usage = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'cost_usd': 0.0}
	max_context_tokens = 0
	max_input_images = 0
	screenshots = 0
	observe_calls = 0

	for event in events:
		payload = _event_payload(event)
		event_type = str(event['type'])
		if event_type == 'model.tool_call':
			name = _tool_name(payload)
			tool_calls[name] += 1
			if name == 'browser_script':
				args = _tool_arguments(payload)
				if args.get('action') == 'observe':
					observe_calls += 1
		elif event_type == 'tool.output':
			name = _tool_name(payload)
			tool_outputs[name] += 1
			chars = _payload_text_chars(payload)
			tool_text_chars[name] += chars
			if chars:
				largest_outputs.append((chars, int(event['seq']), name, _short(payload, 240)))
		elif event_type == 'tool.image':
			screenshots += 1
		elif event_type == 'model.usage':
			input_tokens = int(payload.get('input_tokens') or payload.get('prompt_tokens') or 0)
			output_tokens = int(payload.get('output_tokens') or payload.get('completion_tokens') or 0)
			total_tokens = int(payload.get('total_tokens') or input_tokens + output_tokens)
			usage['input_tokens'] += input_tokens
			usage['output_tokens'] += output_tokens
			usage['total_tokens'] += total_tokens
			usage['cost_usd'] += float(payload.get('cost_usd') or payload.get('cost') or 0.0)
		elif event_type == 'model.turn.request':
			if context_tokens := _input_context_tokens(payload):
				max_context_tokens = max(max_context_tokens, context_tokens)
			if image_count := _input_image_count(payload):
				max_input_images = max(max_input_images, image_count)

	largest_outputs.sort(reverse=True)
	return {
		'event_counts': dict(type_counts.most_common()),
		'tool_calls': dict(tool_calls.most_common()),
		'tool_outputs': dict(tool_outputs.most_common()),
		'tool_output_chars': dict(sorted(tool_text_chars.items())),
		'largest_outputs': largest_outputs[:10],
		'usage': usage,
		'model_turns': type_counts.get('model.turn.request', 0),
		'model_calls': type_counts.get('model.turn.response', 0),
		'observe_calls': observe_calls,
		'screenshots': screenshots,
		'max_context_tokens': max_context_tokens,
		'max_input_images': max_input_images,
		'artifact_count': len(artifacts),
		'artifact_kinds': dict(Counter(str(a.get('kind') or '?') for a in artifacts).most_common()),
	}


def timeline_line(event: dict[str, Any], started_ms: int | None) -> str:
	payload = _event_payload(event)
	elapsed = ''
	if started_ms is not None:
		elapsed = f'{(int(event["ts_ms"]) - started_ms) / 1000:7.1f}s '
	event_type = str(event['type'])
	detail = ''
	if event_type in {'model.tool_call', 'tool.started', 'tool.finished', 'tool.output'}:
		detail = _tool_name(payload)
		if event_type == 'model.tool_call':
			args = _tool_arguments(payload)
			if args.get('action'):
				detail += f' action={args["action"]}'
			elif detail == 'browser_script' and args.get('code'):
				detail += f' code={len(str(args["code"]))} chars'
	elif event_type == 'tool.image':
		image = payload.get('image') if isinstance(payload.get('image'), dict) else {}
		detail = str(image.get('label') or image.get('path') or '')
	elif event_type == 'model.usage':
		detail = (
			f'in={payload.get("input_tokens") or payload.get("prompt_tokens") or 0} '
			f'out={payload.get("output_tokens") or payload.get("completion_tokens") or 0} '
			f'cost={payload.get("cost_usd") or payload.get("cost") or 0}'
		)
	elif event_type in {'session.result', 'session.done'}:
		detail = _short(payload.get('result') or payload.get('text') or payload)
	elif event_type in {'session.failure', 'session.failed'}:
		detail = _short(payload.get('error') or payload.get('message') or payload)
	return f'{event["seq"]:>6} {elapsed}{event_type:<28} {detail}'


def print_report(
	db_path: Path,
	session: dict[str, Any],
	events: list[dict[str, Any]],
	artifacts: list[dict[str, Any]],
	limit_events: int,
) -> None:
	summary = summarize(events, artifacts)
	print('== session ==')
	print(f'  db          : {db_path}')
	print(f'  id          : {session["id"]}')
	print(f'  status      : {session["status"]}')
	print(f'  cwd         : {session["cwd"]}')
	print(f'  artifacts   : {session["artifact_root"]}')
	if session.get('parent_id'):
		print(f'  parent      : {session["parent_id"]}')
	print()

	print('== totals ==')
	print(f'  events      : {len(events)}')
	print(f'  model turns : {summary["model_turns"]}')
	print(f'  model calls : {summary["model_calls"]}')
	print(f'  screenshots : {summary["screenshots"]}')
	print(f'  observe     : {summary["observe_calls"]}')
	print(f'  max context : {summary["max_context_tokens"] or "unknown"} tokens')
	print(f'  max images  : {summary["max_input_images"] or "unknown"}')
	usage = summary['usage']
	print(
		'  usage       : '
		f'{usage["input_tokens"]} in / {usage["output_tokens"]} out / '
		f'{usage["total_tokens"]} total / ${usage["cost_usd"]:.4f}'
	)
	print()

	print('== tools ==')
	for name, count in summary['tool_calls'].items():
		chars = summary['tool_output_chars'].get(name, 0)
		print(f'  {name:<18} calls={count:<3} output_chars={chars}')
	print()

	if summary['largest_outputs']:
		print('== largest tool outputs ==')
		for chars, seq, name, preview in summary['largest_outputs']:
			print(f'  seq={seq:<5} {name:<16} chars={chars:<7} {preview}')
		print()

	if artifacts:
		print('== artifacts ==')
		for artifact in artifacts[-20:]:
			size = artifact.get('bytes')
			size_text = f'{size} bytes' if size is not None else 'unknown size'
			print(f'  seq={artifact.get("event_seq")} {artifact.get("kind")} {size_text} {artifact.get("path")}')
		print()

	print('== timeline ==')
	started_ms = int(events[0]['ts_ms']) if events else None
	shown = events if limit_events <= 0 else events[-limit_events:]
	for event in shown:
		print(timeline_line(event, started_ms))
	if limit_events > 0 and len(events) > limit_events:
		print(f'  ... omitted {len(events) - limit_events} earlier events; use --limit-events 0 for all')


def parse_args(argv: list[str]) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('state_db', help='Path to state.db')
	parser.add_argument('session_id', nargs='?', help='Session id to inspect')
	parser.add_argument('--latest', action='store_true', help='Inspect the most recently updated session')
	parser.add_argument('--limit-events', type=int, default=80, help='Timeline events to show; 0 means all')
	parser.add_argument('--json', action='store_true', help='Print machine-readable summary instead of text report')
	return parser.parse_args(argv)


def main(argv: list[str]) -> int:
	args = parse_args(argv)
	db_path = _expand(args.state_db)
	conn = connect(db_path)
	session_id = latest_session_id(conn) if args.latest else args.session_id
	if not session_id:
		raise SystemExit('session_id is required unless --latest is set')
	session = load_session(conn, session_id)
	events = load_events(conn, session_id)
	artifacts = load_artifacts(conn, session_id)
	if args.json:
		print(
			json.dumps(
				{
					'session': session,
					'summary': summarize(events, artifacts),
					'artifacts': artifacts,
				},
				indent=2,
				sort_keys=True,
			)
		)
	else:
		print_report(db_path, session, events, artifacts, args.limit_events)
	return 0


if __name__ == '__main__':
	raise SystemExit(main(sys.argv[1:]))
