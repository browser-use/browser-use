import asyncio
import logging
import os
import time
from typing import Optional

from playwright.async_api import ElementHandle, Page

from browser_use.browser.enums.click_status import ClickStatus
from browser_use.browser.models.click_config import ClickConfig
from browser_use.browser.models.click_result import ClickResult
from browser_use.dom.views import DOMElementNode

logger = logging.getLogger(__name__)


class ElementClickHandler:
    def __init__(
        self,
        get_current_page,
        enhanced_css_selector_for_element,
        update_state,
        get_locate_element,
        is_url_allowed,
        config: Optional[ClickConfig] = None,
    ):
        self.get_current_page = get_current_page
        self.enhanced_css_selector_for_element = enhanced_css_selector_for_element
        self.update_state = update_state
        self.get_locate_element = get_locate_element
        self.config = config if config is not None else ClickConfig()
        self.is_url_allowed = is_url_allowed

    async def _get_unique_filename(self, directory: str, filename: str) -> str:
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filename = filename

        while os.path.exists(os.path.join(directory, new_filename)):
            new_filename = f"{base} ({counter}){ext}"
            counter += 1

        return new_filename

    async def _handle_popups(self, page: Page) -> None:
        popup_selectors = [
            '[id*="cookie"] button',
            '[class*="popup"] button',
            '[id*="consent"] button',
            '[role="dialog"] button',
            '[class*="modal"] button[class*="close"]',
        ]

        for selector in popup_selectors:
            try:
                popup = await page.query_selector(selector)
                if popup and await popup.is_visible():
                    await popup.click(timeout=self.config.timeouts["popup"])
                    await page.wait_for_timeout(500)
                    logger.debug(
                        f"Successfully dismissed popup with selector: {selector}"
                    )
            except Exception as e:
                logger.debug(
                    f"Popup handling skipped for selector {selector}: {str(e)}"
                )
                continue

    async def _check_element_state(
        self,
        element_handle: ElementHandle,
    ) -> bool:
        try:
            state = {
                "attached": await element_handle.evaluate("el => !!el.parentElement"),
                "visible": await element_handle.is_visible(),
                "enabled": await element_handle.is_enabled(),
            }

            logger.debug(f"Element state check: {state}")

            return all(state.values())

        except Exception as e:
            logger.warning(f"Element state check failed: {str(e)}")
            return False

    async def click_element_node(
        self,
        element_node: DOMElementNode,
    ) -> ClickResult:
        page = await self.get_current_page()
        try:
            # if element_node.highlight_index is not None:
            #     await self.update_state(focus_element=element_node.highlight_index)
            element_handle: ElementHandle = await self.get_locate_element(element_node)
            if not element_handle:
                return ClickResult(
                    status=ClickStatus.ERROR, message="Unable to locate element handle"
                )
            await self._handle_popups(page)
            if not await self._check_element_state(element_handle):
                return ClickResult(
                    status=ClickStatus.ERROR, message="Element not in clickable state"
                )
            return await self.handle_click(page, element_handle)
        except Exception as e:
            return ClickResult(status=ClickStatus.ERROR, message=str(e))

    async def click_with_retry(
        self,
        element_node: DOMElementNode,
    ) -> ClickResult:
        delay = self.config.initial_retry_delay
        error_message: set[str] = set()
        for attempt in range(1, self.config.max_retries + 1):
            try:
                result: ClickResult = await self.click_element_node(element_node)
                if result.status in {
                    ClickStatus.DOWNLOAD_SUCCESS,
                    ClickStatus.SUCCESS,
                    ClickStatus.NAVIGATION_SUCCESS,
                }:
                    logger.info(f"Click successful with message: {result.message}")
                    return result
                elif result.status == ClickStatus.NAVIGATION_DISALLOWED:
                    logger.info(f"Click failed with message: {result.message}")
                    return result
                elif result.message:  # status is ERROR
                    error_message.add(result.message)
                logger.warning(
                    f"Retrying attempt: {attempt}/{self.config.max_retries}",
                )
                await asyncio.sleep(delay)
                delay *= 2
            except Exception as e:
                error_message.add(str(e))
        logger.error(f"Click failed after all attempts: {', '.join(error_message)}")
        return ClickResult(status=ClickStatus.ERROR, message=", ".join(error_message))

    async def handle_click(self, page: Page, element: ElementHandle) -> ClickResult:
        """Handle click, checking for both navigation and download events"""
        start_time = time.time()
        previous_url = page.url
        click_succeeded = False

        # Create tasks for watching events
        navigation_task = asyncio.create_task(page.wait_for_event("load"))
        download_task = asyncio.create_task(page.wait_for_event("download"))

        # Perform the click
        try:
            await element.click(
                timeout=self.config.timeouts["click"], no_wait_after=True
            )
            click_succeeded = True
        except Exception as ex:
            logger.warning(
                f"Standard click failed, attempting JavaScript click str{ex}"
            )
            try:
                await page.evaluate("(el) => el.click()", element)
                click_succeeded = True
            except Exception as e:
                logger.error(f"Both click methods failed: {str(e)}")

        # Wait for events with timeout
        done, pending = await asyncio.wait(
            [navigation_task, download_task],
            timeout=max(
                self.config.timeouts["navigation"], self.config.timeouts["download"]
            ),
            return_when=asyncio.ALL_COMPLETED,
        )

        # Cancel any pending tasks
        for task in pending:
            task.cancel()

        # Check if download happened
        download_success = False
        download_path = None
        if (
            download_task in done
            and download_task.exception() is None
            and self.config.save_downloads_path
        ):
            try:
                download_result = download_task.result()
                filename = await self._get_unique_filename(
                    self.config.save_downloads_path, download_result.suggested_filename
                )
                path = os.path.join(self.config.save_downloads_path, filename)
                await download_result.save_as(path)
                download_success = True
                download_path = path
            except (asyncio.CancelledError, Exception) as e:
                logger.debug(f"Download handling error: {str(e)}")

        # Check if navigation happened
        navigation_success = False
        navigated_url = None
        if navigation_task in done and navigation_task.exception() is None:
            try:
                navigation_task.result()
                if not await self.is_url_allowed(page.url):
                    await page.goto(previous_url)
                    return ClickResult(
                        status=ClickStatus.NAVIGATION_DISALLOWED,
                        message=f"Navigation to disallowed URL: {page.url}",
                    )
                navigation_success = True
                navigated_url = page.url
            except (asyncio.CancelledError, Exception) as e:
                logger.debug(f"Navigation handling error: {str(e)}")

        # Determine result based on what happened
        if download_success:
            return ClickResult(
                status=ClickStatus.DOWNLOAD_SUCCESS, download_path=download_path
            )
        elif navigation_success:
            return ClickResult(
                status=ClickStatus.NAVIGATION_SUCCESS,
                message="Click triggered navigation",
                navigated_url=navigated_url,
            )
        elif not click_succeeded:
            return ClickResult(
                status=ClickStatus.ERROR,
                message="Click failed with no navigation or download",
            )

        duration = time.time() - start_time
        return ClickResult(
            status=ClickStatus.SUCCESS,
            message=f"Click successful in duration: {duration:.2f}s",
        )
