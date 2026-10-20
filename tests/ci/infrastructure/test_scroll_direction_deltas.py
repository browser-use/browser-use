"""ScrollEvent directions must map to the right axes."""

import pytest

from browser_use.browser.watchdogs.default_action_watchdog import _direction_to_deltas


@pytest.mark.parametrize(
	('direction', 'amount', 'expected'),
	[
		('down', 500, (0, 500)),
		('up', 500, (0, -500)),
		('right', 500, (500, 0)),
		('left', 500, (-500, 0)),
	],
)
def test_direction_maps_to_correct_axis(direction, amount, expected):
	"""left/right must be horizontal deltas — previously every non-down
	direction collapsed to a vertical -amount scroll-up."""
	assert _direction_to_deltas(direction, amount) == expected
