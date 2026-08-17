from datetime import datetime, timezone

from browser_use.config import DBStyleEntry


def test_db_style_entry_created_at_is_timezone_aware():
	entry = DBStyleEntry()
	created_at = datetime.fromisoformat(entry.created_at)

	assert created_at.tzinfo is not None
	assert created_at.utcoffset() == timezone.utc.utcoffset(created_at)
