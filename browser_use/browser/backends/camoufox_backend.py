"""Camoufox-based browser backend.

Implements the BrowserBackend abstraction on top of Camoufox (stealth-hardened
Firefox driven through Playwright's sync API). Camoufox's juggler fork includes
humanized mouse trajectories (additions/juggler/MouseTrajectories.hpp), so
page.mouse.click() / page.locator().click() automatically follow natural,
human-like pointer paths instead of teleporting the cursor.

The DOM snapshot walker tags visible elements with data-bu-id indices, matching
the browser-use element-indexing convention in a lightweight JS-only form.
"""

import asyncio
import logging
import uuid

from camoufox.sync_api import Camoufox

from browser_use.browser.backends.base import BrowserBackend
from browser_use.browser.profile import BrowserLaunchArgs, BrowserProfile

logger = logging.getLogger('browser_use.backends.camoufox')


# JS tree-walker that indexes all visible elements and stamps them with data-bu-id,
# returning a compact textual snapshot like: [0]<div text="Hello" />
WALKER_JS = """() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let idx=0; let out=[];
    while(walker.nextNode()){
      const el=walker.currentNode;
      const rect=el.getBoundingClientRect();
      if(rect.width>0 && rect.height>0){
        out.push(`[${idx}]<${el.tagName.toLowerCase()} text="${el.innerText?.slice(0,30)}" />`);
        el.setAttribute('data-bu-id', idx);
        idx++;
      }
    }
    return out.join('\\n');
}"""


class CamoufoxBackend(BrowserBackend):
    """Browser backend powered by Camoufox (anti-detect Firefox + Playwright sync API)."""

    def __init__(self, profile: BrowserProfile):
        self.profile = profile
        self.camoufox: Camoufox | None = None
        self.browser = None
        # page_id -> {'context': ..., 'page': ...}
        self.pages: dict[str, dict] = {}

    def _camoufox_options(self) -> dict:
        """Read camoufox launch options off the BrowserProfile."""
        profile = self.profile
        options = {
            'humanize': True,
            'os': 'random',
            'geoip': True,
            'headless': bool(profile.headless),
            'window': (1920, 1080),
        }
        # Extra profile args can override camoufox options, e.g. profile.args = ['--locale=fr-FR']
        options.update(BrowserLaunchArgs.args_as_dict(list(profile.args)))
        return options

    async def launch(self):
        """Start Camoufox via its context-manager protocol (__enter__ returns the browser)."""
        if self.browser is not None:
            return  # already launched

        profile = self.profile
        self.camoufox = Camoufox(
            humanize=True,
            os='random',
            geoip=True,
            headless=profile.headless,
            window=(1920, 1080),
        )
        # Camoufox's sync API is a context manager; enter it manually and keep it open
        # until close() calls __exit__. Run in a thread to avoid blocking the event loop.
        self.browser = await asyncio.to_thread(self.camoufox.__enter__)
        logger.debug('Camoufox browser launched')

    async def new_page(self, url: str):
        """Create a new browser context + page, navigate it to url, and return the page_id."""
        if self.browser is None:
            raise RuntimeError('Camoufox not launched - call launch() first')

        def _open():
            context = self.browser.new_context()
            page = context.new_page()
            page.goto(url)
            return context, page

        context, page = await asyncio.to_thread(_open)
        page_id = str(uuid.uuid4())
        self.pages[page_id] = {'context': context, 'page': page}
        return page_id

    async def navigate(self, page_id: str, url: str):
        """Navigate an existing page to a URL via page.goto()."""
        page = self._get_page(page_id)
        await asyncio.to_thread(page.goto, url)

    async def get_dom_snapshot(self, page_id: str):
        """Run the WALKER_JS tree-walker in the page; returns indexed element lines and stamps data-bu-id."""
        page = self._get_page(page_id)
        return await asyncio.to_thread(page.evaluate, WALKER_JS)

    async def get_ax_tree(self, page_id: str):
        """Return the accessibility tree via Playwright's page.accessibility.snapshot()."""
        page = self._get_page(page_id)
        return await asyncio.to_thread(lambda: page.accessibility.snapshot())

    async def screenshot(self, page_id: str):
        """Capture a PNG screenshot, returns raw bytes from page.screenshot()."""
        page = self._get_page(page_id)
        return await asyncio.to_thread(page.screenshot)

    async def click(self, page_id: str, selector: str = None, x: int = None, y: int = None):
        """Click by coordinates or CSS selector.

        Both paths go through Camoufox's juggler mouse implementation, which uses
        humanized pointer trajectories (additions/juggler/MouseTrajectories.hpp)
        rather than instant cursor jumps.
        """
        page = self._get_page(page_id)

        def _click():
            if x is not None and y is not None:
                page.mouse.click(x, y)
            elif selector:
                page.locator(selector).click()
            else:
                raise ValueError('click() requires either a selector or x and y coordinates')

        await asyncio.to_thread(_click)

    async def type_text(self, page_id: str, selector: str, text: str):
        """Fill an input/textarea matched by CSS selector with text."""
        page = self._get_page(page_id)
        await asyncio.to_thread(lambda: page.locator(selector).fill(text))

    # ------------------------------------------------------------------
    # Helpers / cleanup
    # ------------------------------------------------------------------
    def _get_page(self, page_id: str):
        if page_id not in self.pages:
            raise ValueError(f'Unknown page_id={page_id}. Did you call new_page()?')
        return self.pages[page_id]['page']

    async def close(self):
        """Close all contexts and shut Camoufox down via its context manager __exit__."""
        for entry in list(self.pages.values()):
            try:
                await asyncio.to_thread(entry['context'].close)
            except Exception:
                pass
        self.pages.clear()

        if self.camoufox is not None:
            try:
                await asyncio.to_thread(self.camoufox.__exit__, None, None, None)
            except Exception:
                pass
            self.camoufox = None
            self.browser = None
