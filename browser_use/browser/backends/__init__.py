from typing import TYPE_CHECKING

from .base import BrowserBackend
from .cdp_backend import CdpBackend

if TYPE_CHECKING:
	from .camoufox_backend import CamoufoxBackend

__all__ = ['BrowserBackend', 'CdpBackend', 'CamoufoxBackend']


def __getattr__(name: str):
	if name == 'CamoufoxBackend':
		from .camoufox_backend import CamoufoxBackend

		return CamoufoxBackend
	raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
