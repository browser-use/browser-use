MONTHS = {
	'January': 1,
	'February': 2,
	'March': 3,
	'April': 4,
	'May': 5,
	'June': 6,
	'July': 7,
	'August': 8,
	'September': 9,
	'October': 10,
	'November': 11,
	'December': 12,
}


def calculate_times_to_click(mode: str, current: dict, target: dict) -> int:
	"""
	Calculate how many times to click a navigation element to go from current to target value,
	based on the mode of navigation (e.g., daily, monthly, yearly).

	:param mode: One of "date", "month", "year", "month-year"
	:param current: Dict with only the relevant fields
	:param target: Dict with only the relevant fields
	:return: Integer number of clicks
	"""

	if mode == 'date':
		# Expect fields: date (int)
		return abs(target['date'] - current['date'])

	elif mode == 'month':
		# Expect fields: month (str)
		return abs(MONTHS[target['month']] - MONTHS[current['month']])

	elif mode == 'year':
		# Expect fields: year (int)
		return abs(target['year'] - current['year'])

	elif mode == 'month-year':
		# Expect fields: month (str), year (int)
		curr_total = current['year'] * 12 + MONTHS[current['month']]
		targ_total = target['year'] * 12 + MONTHS[target['month']]
		return abs(targ_total - curr_total)

	else:
		raise ValueError(f'Unsupported mode: {mode}')
