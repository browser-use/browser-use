from typing import TYPE_CHECKING

from browser_use.skills.browser_use import skill_text as browser_use_skill_text

__all__ = ['browser_use_skill_text']


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
