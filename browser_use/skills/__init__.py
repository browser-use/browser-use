"""Skills package — all exports are lazy so `python -m browser_use.skills.fitness`
runs cleanly (no runpy warning) and standalone consumers pay only for what they import.
"""

from typing import TYPE_CHECKING

__all__ = [
	'SkillService',
	'MissingCookieException',
	'MassFunction',
	'SelectionMode',
	'SkillFitnessTracker',
	'dempster_combine',
]

if TYPE_CHECKING:
	from browser_use.skills.fitness import (
		MassFunction as MassFunction,
	)
	from browser_use.skills.fitness import (
		SelectionMode as SelectionMode,
	)
	from browser_use.skills.fitness import (
		SkillFitnessTracker as SkillFitnessTracker,
	)
	from browser_use.skills.fitness import (
		dempster_combine as dempster_combine,
	)
	from browser_use.skills.service import SkillService as SkillService
	from browser_use.skills.views import MissingCookieException as MissingCookieException


def __getattr__(name: str):
	if name in {'MassFunction', 'SelectionMode', 'SkillFitnessTracker', 'dempster_combine'}:
		from browser_use.skills import fitness

		return getattr(fitness, name)
	if name == 'SkillService':
		from browser_use.skills.service import SkillService

		return SkillService
	if name == 'MissingCookieException':
		from browser_use.skills.views import MissingCookieException

		return MissingCookieException
	raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
