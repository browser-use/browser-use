"""Shared utilities for CLI command handlers."""

from datetime import datetime, timezone


def format_duration(started_at: datetime | None, finished_at: datetime | None) -> str:
	"""Format duration between two timestamps, or elapsed time if still running."""
	if not started_at:
		return ''

	try:
		if finished_at:
			end = finished_at
		else:
			end = datetime.now(timezone.utc)

		delta = end - started_at
		total_seconds = int(delta.total_seconds())

		if total_seconds < 60:
			return f'{total_seconds}s'
		elif total_seconds < 3600:
			minutes = total_seconds // 60
			seconds = total_seconds % 60
			return f'{minutes}m {seconds}s'
		else:
			hours = total_seconds // 3600
			minutes = (total_seconds % 3600) // 60
			return f'{hours}h {minutes}m'
	except Exception:
		return ''
