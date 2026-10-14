"""CDP-based browser backend.

Implements the BrowserBackend abstraction on top of cdp_use's raw CDP client,
reusing the same launch/attach/navigate/snapshot logic that BrowserSession
(browser_use/browser/session.py) uses internally via its watchdogs:

- Local Chrome launch + CDP URL discovery (mirrors LocalBrowserWatchdog._launch_browser)
- Target.createTarget / Target.attachToTarget session management (mirrors CDPSession.for_target)
- DOMSnapshot.captureSnapshot (mirrors browser_use.dom.service)
- Accessibility.getFullAXTree (mirrors browser_use.dom.service)
- Page.captureScreenshot (mirrors ScreenshotWatchdog)
- Input.dispatchMouseEvent / Runtime.evaluate clicks (mirrors DefaultActionWatchdog)
"""

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path

from cdp_use import CDPClient

from browser_use.browser.backends.base import BrowserBackend
from browser_use.browser.profile import BrowserProfile
from browser_use.dom.enhanced_snapshot import REQUIRED_COMPUTED_STYLES

logger = logging.getLogger('browser_use.backends.cdp')


class CdpBackend(BrowserBackend):
    """Browser backend driven by raw Chrome DevTools Protocol via cdp_use."""

    def __init__(self, profile: BrowserProfile):
        self.profile = profile
        self.cdp_client: CDPClient | None = None
        self._browser_process: subprocess.Popen | None = None
        # page_id (== CDP targetId) -> session_id
        self._sessions: dict[str, str] = {}
        self._owns_browser = False

    # ------------------------------------------------------------------
    # Launch / connection
    # ------------------------------------------------------------------
    async def launch(self):
        """Launch a local Chrome process (if needed) and connect over CDP."""
        if self.cdp_client is not None:
            return  # already launched

        cdp_url = self.profile.cdp_url
        if not cdp_url:
            cdp_url = await self._launch_local_browser()

        # Connect the root CDP client (same flow as BrowserSession.connect())
        self.cdp_client = CDPClient(cdp_url)
        await self.cdp_client.start()
        await self.cdp_client.send.Target.setAutoAttach(
            params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True}
        )
        logger.debug(f'CDP backend connected to {cdp_url}')

        # Make sure at least one page exists and is attached
        targets = await self.cdp_client.send.Target.getTargets()
        page_targets = [t for t in targets['targetInfos'] if t.get('type') == 'page']
        if not page_targets:
            new_target = await self.cdp_client.send.Target.createTarget(params={'url': 'about:blank'})
            await self._attach(new_target['targetId'])
        else:
            for t in page_targets:
                try:
                    await self._attach(t['targetId'])
                except Exception as e:
                    logger.debug(f'Failed to attach to existing target {t["targetId"]}: {e}')

    async def _launch_local_browser(self) -> str:
        """Launch local Chrome subprocess and wait for its CDP WebSocket URL.

        Mirrors LocalBrowserWatchdog._launch_browser from browser_use/browser/watchdogs/local_browser_watchdog.py.
        """
        profile = self.profile
        launch_args = profile.get_args()

        debug_port = self._find_free_port()
        launch_args.append(f'--remote-debugging-port={debug_port}')

        browser_path = profile.executable_path or self._find_installed_browser_path()
        if not browser_path:
            raise RuntimeError('No local Chrome/Chromium install found; set profile.executable_path or cdp_url')

        logger.debug(f'Launching browser subprocess: {browser_path} with {len(launch_args)} args on port {debug_port}')
        self._browser_process = subprocess.Popen(
            [browser_path, *launch_args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._owns_browser = True

        cdp_url = await self._wait_for_cdp_url(debug_port)
        return cdp_url

    @staticmethod
    def _find_free_port() -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            port = s.getsockname()[1]
        return port

    @staticmethod
    def _find_installed_browser_path() -> str | None:
        """Find a chrome/chromium binary from common locations."""
        candidates = [
            '/usr/bin/google-chrome',
            '/usr/bin/google-chrome-stable',
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        # fall back to PATH lookup
        for name in ('google-chrome', 'chromium', 'chromium-browser', 'chrome'):
            found = shutil.which(name)
            if found:
                return found
        return None

    @staticmethod
    async def _wait_for_cdp_url(port: int, timeout: float = 30.0) -> str:
        """Poll http://localhost:PORT/json/version until the CDP websocket URL is available."""
        import httpx

        last_error = None
        for _ in range(int(timeout * 10)):
            try:
                response = await httpx.AsyncClient().get(f'http://localhost:{port}/json/version', timeout=1)
                if response.status_code == 200:
                    data = response.json()
                    ws_url = data.get('webSocketDebuggerUrl')
                    if ws_url:
                        return ws_url
                    last_error = 'webSocketDebuggerUrl missing from /json/version response'
                else:
                    last_error = f'HTTP {response.status_code}'
            except Exception as e:
                last_error = str(e)
            await asyncio.sleep(0.1)
        raise TimeoutError(f'Browser CDP never became ready on port {port}: {last_error}')

    # ------------------------------------------------------------------
    # Session (per-target) management — mirrors CDPSession.for_target/attach in session.py
    # ------------------------------------------------------------------
    async def _attach(self, target_id: str, domains: list[str] | None = None) -> str:
        """Attach to a target via Target.attachToTarget and enable the required CDP domains."""
        assert self.cdp_client is not None, 'CDP client not initialized - call launch() first'
        if target_id in self._sessions:
            return self._sessions[target_id]

        result = await self.cdp_client.send.Target.attachToTarget(
            params={
                'targetId': target_id,
                'flatten': True,
                'filter': [
                    {'type': 'page', 'exclude': False},
                    {'type': 'iframe', 'exclude': False},
                ],
            }
        )
        session_id = result['sessionId']

        domains = domains or ['Page', 'DOM', 'DOMSnapshot', 'Accessibility', 'Runtime', 'Inspector']
        enable_tasks = []
        for domain in domains:
            domain_api = getattr(self.cdp_client.send, domain, None)
            enable_kwargs = {} if domain in ['Browser', 'Target'] else {'session_id': session_id}
            assert domain_api and hasattr(domain_api, 'enable'), (
                f'{domain_api} is not a recognized CDP domain with a .enable() method'
            )
            enable_tasks.append(domain_api.enable(**enable_kwargs))

        results = await asyncio.gather(*enable_tasks, return_exceptions=True)
        if any(isinstance(r, Exception) for r in results):
            raise RuntimeError(f'Failed to enable requested CDP domain: {results}')

        # Disable breakpoints so the page never pauses on debugger statements
        try:
            await self.cdp_client.send.Debugger.setSkipAllPauses(params={'skip': True}, session_id=session_id)
        except Exception:
            pass

        self._sessions[target_id] = session_id
        return session_id

    def _get_session_id(self, page_id: str) -> str:
        if page_id not in self._sessions:
            raise ValueError(f'No CDP session for page_id={page_id}. Did you call new_page()?')
        return self._sessions[page_id]

    # ------------------------------------------------------------------
    # BrowserBackend interface
    # ------------------------------------------------------------------
    async def new_page(self, url: str):
        """Create a new tab via Target.createTarget and attach to it. Returns the page/target id."""
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        result = await self.cdp_client.send.Target.createTarget(params={'url': url})
        target_id = result['targetId']
        await self._attach(target_id)
        await self.cdp_client.send.Target.activateTarget(params={'targetId': target_id})
        return target_id

    async def navigate(self, page_id: str, url: str):
        """Navigate a page to a URL via Page.navigate (same call as NavigationWatchdog in session.py)."""
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        session_id = self._get_session_id(page_id)
        result = await self.cdp_client.send.Page.navigate(
            params={'url': url, 'transitionType': 'address_bar'},
            session_id=session_id,
        )
        # Wait for the page to start loading / settle briefly
        try:
            load_event_id = result.get('loaderId')
            frame_id = result.get('frameId')
            for _ in range(50):
                ready = await self.cdp_client.send.Runtime.evaluate(
                    params={'expression': 'document.readyState', 'returnByValue': True},
                    session_id=session_id,
                )
                state = ready.get('result', {}).get('value')
                if state in ('interactive', 'complete'):
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.debug(f'document.readyState poll after navigate failed (non-fatal): {e}')
        return result

    async def get_dom_snapshot(self, page_id: str):
        """Capture a DOM snapshot via DOMSnapshot.captureSnapshot (same params as dom/service.py)."""
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        session_id = self._get_session_id(page_id)
        return await self.cdp_client.send.DOMSnapshot.captureSnapshot(
            params={
                'computedStyles': REQUIRED_COMPUTED_STYLES,
                'includePaintOrder': True,
                'includeDOMRects': True,
                'includeBlendedBackgroundColors': False,
                'includeTextColorOpacities': False,
            },
            session_id=session_id,
        )

    async def get_ax_tree(self, page_id: str):
        """Get the full accessibility tree via Accessibility.getFullAXTree (as dom/service.py does)."""
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        session_id = self._get_session_id(page_id)
        result = await self.cdp_client.send.Accessibility.getFullAXTree(session_id=session_id)
        return result  # {'nodes': [...]}

    async def screenshot(self, page_id: str):
        """Capture a PNG screenshot via Page.captureScreenshot, returns base64-encoded data."""
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        session_id = self._get_session_id(page_id)
        result = await self.cdp_client.send.Page.captureScreenshot(
            params={'format': 'png', 'captureBeyondViewport': False},
            session_id=session_id,
        )
        if not result or 'data' not in result:
            raise RuntimeError('Screenshot result missing data')
        return result['data']

    async def click(self, page_id: str, selector: str = None, x: int = None, y: int = None):
        """Click by x,y coordinates or by CSS selector.

        x/y clicking uses Input.dispatchMouseEvent directly (mouseMoved -> mousePressed ->
        mouseReleased), mirroring DefaultActionWatchdog. Selector clicking resolves the
        element's center via Runtime.evaluate then dispatches the same mouse events.
        """
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        session_id = self._get_session_id(page_id)

        if x is None or y is None:
            if not selector:
                raise ValueError('click() requires either a selector or x and y coordinates')
            x, y = await self._resolve_selector_center(page_id, selector)

        # Move mouse over the target
        await self.cdp_client.send.Input.dispatchMouseEvent(
            params={'type': 'mouseMoved', 'x': x, 'y': y},
            session_id=session_id,
        )
        await asyncio.sleep(0.05)

        # Mouse down
        await self.cdp_client.send.Input.dispatchMouseEvent(
            params={'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1, 'modifiers': 0},
            session_id=session_id,
        )
        await asyncio.sleep(0.08)

        # Mouse up
        await self.cdp_client.send.Input.dispatchMouseEvent(
            params={'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1, 'modifiers': 0},
            session_id=session_id,
        )

    async def _resolve_selector_center(self, page_id: str, selector: str) -> tuple[int, int]:
        """Resolve a CSS selector to viewport-center coordinates via Runtime.evaluate."""
        assert self.cdp_client is not None
        session_id = self._get_session_id(page_id)
        expression = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('No element found for selector: ' + {json.dumps(selector)});
                el.scrollIntoView({{block: 'center', inline: 'center'}});
                const rect = el.getBoundingClientRect();
                return JSON.stringify({{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}});
            }})()
        """
        result = await self.cdp_client.send.Runtime.evaluate(
            params={'expression': expression, 'returnByValue': True},
            session_id=session_id,
        )
        value = result.get('result', {}).get('value')
        if not value:
            raise ValueError(f'Could not resolve selector to coordinates: {selector}')
        center = json.loads(value)
        return int(center['x']), int(center['y'])

    async def type_text(self, page_id: str, selector: str, text: str):
        """Focus an element by CSS selector, clear it, and type text via Input.insertText."""
        assert self.cdp_client is not None, 'Browser not launched - call launch() first'
        session_id = self._get_session_id(page_id)

        # Focus + clear the element via JS
        focus_expression = f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error('No element found for selector: ' + {json.dumps(selector)});
                el.scrollIntoView({{block: 'center', inline: 'center'}});
                el.focus();
                if ('value' in el) {{
                    el.value = '';
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                }}
                return true;
            }})()
        """
        await self.cdp_client.send.Runtime.evaluate(
            params={'expression': focus_expression, 'returnByValue': True},
            session_id=session_id,
        )

        # Insert the text into the focused element
        await self.cdp_client.send.Input.insertText(params={'text': text}, session_id=session_id)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    async def close(self):
        """Disconnect CDP and terminate any locally-launched browser process."""
        if self.cdp_client is not None:
            try:
                await self.cdp_client.stop()
            except Exception:
                pass
            self.cdp_client = None
        self._sessions.clear()

        if self._owns_browser and self._browser_process is not None:
            try:
                self._browser_process.terminate()
                self._browser_process.wait(timeout=5)
            except Exception:
                try:
                    self._browser_process.kill()
                except Exception:
                    pass
            self._browser_process = None
