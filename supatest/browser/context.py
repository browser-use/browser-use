import logging
from typing import Optional, cast
import asyncio

from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext
from browser_use.browser.context import BrowserContextConfig, BrowserContextState, BrowserSession
from browser_use.browser.views import BrowserState, BrowserError
from supatest.dom.service import SupatestDomService
from supatest.dom.views import SupatestDOMElementNode
from supatest.browser.views import SupatestBrowserState

logger = logging.getLogger(__name__)


class SupatestBrowserContext(BrowserContext):
    """Extended version of BrowserContext that uses SupatestDOMElementNode"""

    def __init__(
        self,
        browser: 'Browser',
        config: BrowserContextConfig = BrowserContextConfig(),
        state: Optional[BrowserContextState] = None,
        active_page_id: Optional[str] = None
    ):
        super().__init__(browser, config, state)
        self.active_page_id = active_page_id

    async def _initialize_session(self):
        """Initialize the browser session with Supatest extensions"""
        logger.debug('Initializing browser context')

        playwright_browser = await self.browser.get_playwright_browser()
        context = await self._create_context(playwright_browser)
        self._page_event_handler = None

        # Get or create a page to use
        pages = context.pages
        logger.info(f'active_page_id received: {self.active_page_id}')
        logger.info(f'available pages: {pages}')
        
        # making the tabId 0 as default 
        tabId = 0
        page_info = {}
        if self.browser.config.cdp_url:
            cdp_session = await pages[0].context.new_cdp_session(pages[0])
            result = await cdp_session.send('Target.getTargets')
            await cdp_session.detach()
            targets = result.get('targetInfos', [])

            # If active_page_id is provided, only process that specific page
            if self.active_page_id is not None:
                for target in targets:
                    if target['targetId'] == self.active_page_id:
                        for page_id, page in enumerate(pages):
                            if page.url == target['url']:
                                try:
                                    title = await page.title()
                                    active_page_details = {
                                        "Page ID": page_id,
                                        "Target ID": target["targetId"],
                                        "URL": page.url,
                                        "Title": title
                                    }
                                    print(f'Active Page Details: {active_page_details}')
                                    tabId = page_id
                                except Exception as e:
                                    print(f'Error retrieving active page info: {e}')
                                break
                        break

        self.session = BrowserSession(
            context=context,
            cached_state=None,
        )

        active_page = None
        if self.browser.config.cdp_url:
            # If we have a saved target ID, try to find and activate it
            if self.state.target_id:
                targets = await self._get_cdp_targets()
                for target in targets:
                    if target['targetId'] == self.state.target_id:
                        # Find matching page by URL
                        for page in pages:
                            if page.url == target['url']:
                                active_page = page
                                break
                        break


        if not active_page:
            if pages:
                active_page = pages[tabId]
                logger.debug('Using existing page')
            else:
                active_page = await context.new_page()
                logger.debug('Created new page')

            # Get target ID for the active page
            if self.browser.config.cdp_url:
                targets = await self._get_cdp_targets()
                for target in targets:
                    if target['url'] == active_page.url:
                        self.state.target_id = target['targetId']
                        break

        # Bring page to front
        await active_page.bring_to_front()
        await active_page.wait_for_load_state('load')

        return self.session

    async def _update_state(self, focus_element: int = -1) -> SupatestBrowserState:
        """Update and return state with Supatest extensions."""
        session = await self.get_session()

        # Check if current page is still valid, if not switch to another available page
        try:
            page = await self.get_current_page()
            # Test if page is still accessible
            await page.evaluate('1')
        except Exception as e:
            logger.debug(f'Current page is no longer accessible: {str(e)}')
            # Get all available pages
            pages = session.context.pages
            if pages:
                self.state.target_id = None
                page = await self._get_current_page(session)
                logger.debug(f'Switched to page: {await page.title()}')
            else:
                raise BrowserError('Browser closed: no valid pages available')

        try:
            await self.remove_highlights()
            dom_service = SupatestDomService(page)
            content = await dom_service.get_clickable_elements(
                focus_element=focus_element,
                viewport_expansion=self.config.viewport_expansion,
                highlight_elements=self.config.highlight_elements,
            )

            screenshot_b64 = await self.take_screenshot()
            pixels_above, pixels_below = await self.get_scroll_info(page)

            self.current_state = SupatestBrowserState(
                element_tree=content.element_tree,
                selector_map=content.selector_map,
                url=page.url,
                title=await page.title(),
                tabs=await self.get_tabs_info(),
                screenshot=screenshot_b64,
                pixels_above=pixels_above,
                pixels_below=pixels_below,
            )

            return self.current_state
        except Exception as e:
            logger.error(f'Failed to update state: {str(e)}')
            # Return last known good state if available
            if hasattr(self, 'current_state'):
                return self.current_state
            raise

    async def get_dom_element_by_index(self, index: int) -> SupatestDOMElementNode:
        """Override to return SupatestDOMElementNode instead of DOMElementNode"""
        logger.debug(f"[Supatest] Getting element by index {index}")
        state = await self.get_state()
        if index not in state.selector_map:
            logger.error(f"[Supatest] No element found with index {index}")
            raise ValueError(f'No element found with index {index}')
        element = state.selector_map[index]
        if not isinstance(element, SupatestDOMElementNode):
            logger.error(f"[Supatest] Element at index {index} is not a SupatestDOMElementNode: {type(element)}")
            raise ValueError(f'Element at index {index} is not a SupatestDOMElementNode')
        return element

    async def get_state(self) -> SupatestBrowserState:
        """Get the current state of the browser with Supatest extensions"""
        await self._wait_for_page_and_frames_load()
        session = await self.get_session()
        session.cached_state = await self._update_state()

        # Save cookies if a file is specified
        if self.config.cookies_file:
            asyncio.create_task(self.save_cookies())

        return session.cached_state 