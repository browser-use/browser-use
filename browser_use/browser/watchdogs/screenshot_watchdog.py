"""Screenshot watchdog for handling screenshot requests using CDP."""

from typing import TYPE_CHECKING, Any, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.page import CaptureScreenshotParameters

from browser_use.browser.events import ScreenshotEvent
from browser_use.browser.views import BrowserError
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.observability import observe_debug

if TYPE_CHECKING:
    pass


class ScreenshotWatchdog(BaseWatchdog):
    """Handles screenshot requests using CDP."""

    # Events this watchdog listens to
    LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [ScreenshotEvent]

    # Events this watchdog emits
    EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

    @observe_debug(
        ignore_input=True, ignore_output=True, name="screenshot_event_handler"
    )
    async def on_ScreenshotEvent(self, event: ScreenshotEvent) -> str:
        """Handle screenshot request using CDP.

        Args:
                event: ScreenshotEvent with optional full_page and clip parameters

        Returns:
                Dict with 'screenshot' key containing base64-encoded screenshot or None
        """
        self.logger.debug(
            "[ScreenshotWatchdog] Handler START - on_ScreenshotEvent called"
        )
        cdp_session = None
        try:
            # Get CDP client and session for current target
            cdp_session = await self.browser_session.get_or_create_cdp_session()

            # Prepare screenshot parameters
            params = CaptureScreenshotParameters(
                format="jpeg", quality=60, captureBeyondViewport=False
            )

            # Take screenshot using CDP
            self.logger.debug(
                f"[ScreenshotWatchdog] Taking screenshot with params: {params}"
            )
            result = await cdp_session.cdp_client.send.Page.captureScreenshot(
                params=params, session_id=cdp_session.session_id
            )

            # Return base64-encoded screenshot data
            if result and "data" in result:
                self.logger.debug(
                    "[ScreenshotWatchdog] Screenshot captured successfully"
                )
                return result["data"]

            raise BrowserError("[ScreenshotWatchdog] Screenshot result missing data")
        except Exception as e:
            self.logger.error(f"[ScreenshotWatchdog] Screenshot failed: {e}")
            # Retry once against a confirmed top-level page target if available
            if "top-level targets" in str(e):
                try:
                    current_session = cdp_session
                    top_level_session = await self._get_top_level_page_session(
                        fallback=current_session
                    )
                    if top_level_session and top_level_session is not current_session:
                        self.logger.info(
                            "[ScreenshotWatchdog] Retrying screenshot after refocusing top-level target"
                        )
                        params = CaptureScreenshotParameters(
                            format="jpeg", quality=60, captureBeyondViewport=False
                        )
                        result = await top_level_session.cdp_client.send.Page.captureScreenshot(
                            params=params,
                            session_id=top_level_session.session_id,
                        )
                        if result and "data" in result:
                            self.logger.info(
                                "[ScreenshotWatchdog] Screenshot captured successfully on retry"
                            )
                            return result["data"]
                except Exception as retry_error:
                    self.logger.error(
                        f"[ScreenshotWatchdog] Retry after top-level refocus failed: {retry_error}"
                    )
            raise BrowserError(f"[ScreenshotWatchdog] Screenshot failed: {e}") from e
        finally:
            # Try to remove highlights even on failure
            try:
                await self.browser_session.remove_highlights()
            except Exception:
                pass

    async def _get_top_level_page_session(self, fallback=None):
        """Return a CDP session that is guaranteed to target a top-level page."""
        candidates = []

        # Start with the agent focus if available
        if self.browser_session.agent_focus:
            candidates.append(self.browser_session.agent_focus)

        # Add any pooled sessions we know about
        if hasattr(self.browser_session, "_cdp_session_pool"):
            candidates.extend(self.browser_session._cdp_session_pool.values())

        for session in candidates:
            if session is None or session is fallback:
                continue
            try:
                info = await session.get_target_info()
                if info.get("type") == "page":
                    return session
            except Exception as e:
                self.logger.debug(
                    f"[ScreenshotWatchdog] Failed to inspect session {getattr(session, 'target_id', '?')}: {e}"
                )

        # Fall back to the original session if nothing better was found
        return fallback
