"""CDP-Use High-Level Library

A Playwright-like library built on top of CDP (Chrome DevTools Protocol).
"""

from .element import Element
from .mouse import Mouse
from .page import Page

__all__ = ['Page', 'Element', 'Mouse']
