import asyncio
import os
import logging
from typing import Optional
from playwright.async_api import Page, ElementHandle

from browser_use.dom.views import DOMElementNode
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


logger = logging.getLogger(__name__)

class ElementClickHandler:
    def __init__(self, get_current_page, enhanced_css_selector_for_element, update_state, get_locate_element, config):
        self.get_current_page = get_current_page
        self.enhanced_css_selector_for_element = enhanced_css_selector_for_element
        self.update_state = update_state
        self.get_locate_element = get_locate_element
        self.config = config
        self.timeouts = {
            'click': 3000,
            'download': 5000,
            'navigation': 5000,
            'popup': 2000
        }

    async def _get_unique_filename(self, directory: str, filename: str) -> str:
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filename = filename
        while os.path.exists(os.path.join(directory, new_filename)):
            new_filename = f'{base} ({counter}){ext}'
            counter += 1
        return new_filename

    async def _handle_popups(self, page: Page) -> None:
        """Handles common popup/overlay dismissal."""
        popup_selectors = [
            '[id*="cookie"] button',
            '[class*="popup"] button',
            '[id*="consent"] button',
            '[role="dialog"] button'
        ]
        
        for selector in popup_selectors:
            try:
                popup = await page.query_selector(selector)
                if popup and await popup.is_visible():
                    await popup.click(timeout=self.timeouts['popup'])
                    await page.wait_for_timeout(500)  # Wait for popup animation
            except Exception as e:
                logger.debug(f"Popup handling failed for selector {selector}: {str(e)}")
                continue

    async def _perform_click(self, page: Page, click_func, element_handle: ElementHandle) -> Optional[str]:
        if self.config.save_downloads_path:
            try:
                async with page.expect_download(timeout=self.timeouts['download']) as download_info:
                    await click_func()
                download = await download_info.value
                filename = await self._get_unique_filename(
                    self.config.save_downloads_path,
                    download.suggested_filename
                )
                path = os.path.join(self.config.save_downloads_path, filename)
                await download.save_as(path)
                return path
            except TimeoutError:
                logger.warning("⏳ Download timeout, proceeding with click...")
                await click_func()
        else:
            await click_func()  
        
        await page.wait_for_load_state()
        return None

    async def _relocate_element(self, element_node: DOMElementNode) -> Optional[ElementHandle]:
        """Helper method to relocate disappeared elements."""
        logger.debug(f"⚠️ Element disappeared before click. Re-locating...")
        new_handle = await self.get_locate_element(element_node)
        
        if new_handle is None:
            logger.debug(f"❌ Failed to re-locate element. Aborting click.")
            return None
            
        return new_handle

    async def _check_element_state(self, element_handle: ElementHandle, element_node: DOMElementNode) -> bool:
        """Checks if the element is attached, visible, and enabled."""
        try:
            is_attached = await element_handle.evaluate("el => !!el.parentElement")
        except Exception:
            is_attached = False
        is_visible = await element_handle.is_visible()
        is_enabled = await element_handle.is_enabled()

        logger.debug(f"📌 Element state - Attached: {is_attached}, Visible: {is_visible}, Enabled: {is_enabled}")

        if not is_attached:
            logger.warning(f"⚠️ Element {repr(element_node)} is no longer in the DOM.")
            return False
        
        if not is_visible:
            logger.warning(f"⚠️ Element {repr(element_node)} is not visible.")
            return False
        
        if not is_enabled:
            logger.warning(f"⚠️ Element {repr(element_node)} is disabled.")
            return False

        return True

    async def _manage_element_state(self, element_node: DOMElementNode, element_handle: ElementHandle) -> bool:
        """Manages element state and visibility."""
        if element_node.highlight_index is not None:
            await self.update_state(focus_element=element_node.highlight_index)

        await element_handle.scroll_into_view_if_needed()
        return await self._check_element_state(element_handle, element_node)

    async def _attempt_click(self, page: Page, element_handle: ElementHandle, element_node: DOMElementNode) -> Optional[str]:
        """Tries to click an element, falling back to JavaScript click if necessary."""
        navigation_errors = ("Timeout", "Target closed", "Execution context was destroyed")
        
        try:
            logger.debug("🖱️ Attempting regular click...")
            if not await element_handle.is_visible():
                new_element = await self._relocate_element(element_node)
                if new_element is None:
                    return None
                element_handle = new_element
                    
            return await self._perform_click(
                page,
                lambda: element_handle.click(timeout=self.timeouts['click']),
                element_handle
            )
        except Exception as e:
            if any(err in str(e) for err in navigation_errors):
                logger.debug("⚠️ Click likely triggered navigation. Suppressing error.")
                return None
                
            logger.warning(f"⚠️ Regular click failed, attempting JavaScript click. Error: {str(e)}")
            
            try:
                return await self._perform_click(
                    page,
                    lambda: page.evaluate('(el) => el.click()', element_handle),
                    element_handle
                )
            except Exception as js_e:
                if any(err in str(js_e) for err in navigation_errors):
                    return None
                logger.error(f"❌ JavaScript click failed: {str(js_e)}")
                return None
            
    async def _click_with_navigation(self, page: Page, element_handle: ElementHandle, element_node: DOMElementNode) -> Optional[str]:
        """Handles clicking elements that might trigger navigation."""
        try:
            async with page.expect_navigation(wait_until="load", timeout=self.timeouts['navigation']) as navigation_info:
                result = await self._attempt_click(page, element_handle, element_node)

            await navigation_info.value
            await page.wait_for_timeout(500)

            return result
        except PlaywrightTimeoutError:
            logger.warning(f"⏳ Navigation timeout. Retrying click...")
            return await self._attempt_click(page, element_handle, element_node)

        except Exception as e:
            logger.error(f"❌ Failed during navigation click: {str(e)}")
            return None

    async def click_element_node(self, element_node: DOMElementNode) -> Optional[str]:
        """Attempts to click an element, with error handling, retries, and JavaScript fallback."""
        page = await self.get_current_page()

        try:
            element_handle = await self.get_locate_element(element_node)
            if not element_handle:
                logger.warning(f"⚠️ Element {repr(element_node)} not found!")
                return None

            await self._handle_popups(page)

            if not await self._manage_element_state(element_node, element_handle):
                return None

            return await self._click_with_navigation(page, element_handle, element_node)

        except Exception as e:
            logger.error(f"❌ Failed to click element: {str(e)}", exc_info=True)

        return None

    async def click_with_retry(self, element_node: DOMElementNode, retries=3, delay=2):
        """Attempts to click an element multiple times with delay between attempts."""
        page = await self.get_current_page()
        previous_url = page.url

        for attempt in range(retries):
            result = await self.click_element_node(element_node)
            
            if page.url != previous_url:
                logger.info(f"✅ Navigation detected after click! New URL: {page.url}")
                return result
            if result:
                return result

            logger.warning(f"🔄 Retry {attempt + 1}/{retries}: Element not clickable, waiting {delay} seconds...")
            await asyncio.sleep(delay)

        raise Exception("Element remained unclickable after retries")