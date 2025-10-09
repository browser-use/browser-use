"""
Integration script that uses Browser-Use's BrowserSession + CDP to exercise the DefaultActionWatchdog click path.

Usage:
  - Start Chrome/Chromium with --remote-debugging-port=9222 (or let the script start it)
  - Run: python flipkart_add_to_cart_cdp.py

This script tries to reproduce headless click behavior using the same code paths as the watchdog.
"""
import asyncio
import os
import sys
import tempfile
import time
import subprocess
import shutil

from urllib.parse import urlparse, urlunparse

# Import browser-use internals
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
from browser_use.dom.service import DomService

# Flipkart product URL - replace with the real product you want to test
PRODUCT_URL = "https://www.flipkart.com/example-product/p/itmexample"
ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), 'artifacts')


def ensure_artifacts_dir():
    try:
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    except Exception:
        pass


async def start_chrome_with_debug_port(port: int = 9222):
    # Start Chrome with remote debugging port; reuse existing if already running
    # This helper is simplified - for production use pick a robust approach
    try:
        # Check if port already serves CDP
        import aiohttp
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f'http://localhost:{port}/json/version', timeout=1) as resp:
                    if resp.status == 200:
                        print('Found existing Chrome CDP on port', port)
                        return None
            except Exception:
                pass
    except Exception:
        pass

    # Try to find chrome executable heuristically
    chrome_cmds = ['chrome', 'google-chrome', 'chromium', 'chromium-browser']
    chrome_exe = None
    for cmd in chrome_cmds:
        if shutil.which(cmd):
            chrome_exe = cmd
            break

    if not chrome_exe:
        raise RuntimeError('Chrome/Chromium not found in PATH; please start Chrome with --remote-debugging-port=9222 manually')

    user_data = tempfile.mkdtemp(prefix='browser-use-cdp-')
    proc = subprocess.Popen([chrome_exe, f'--remote-debugging-port={port}', f'--user-data-dir={user_data}', '--no-first-run', '--no-default-browser-check', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # wait for CDP to be ready
    for _ in range(20):
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f'http://localhost:{port}/json/version', timeout=1) as resp:
                    if resp.status == 200:
                        return proc
        except Exception:
            await asyncio.sleep(1)
    proc.terminate()
    raise RuntimeError('Failed to start Chrome with CDP')


async def main():
    ensure_artifacts_dir()

    # Use an existing Chrome with CDP at localhost:9222
    cdp_url = 'http://localhost:9222'
    session = BrowserSession(cdp_url=cdp_url)

    # Wait for session to initialize and create CDP connections
    # Set agent_focus to the initial tab
    try:
        # Create or get a CDP session for the root target (None) and activate
        await session.get_or_create_cdp_session()
    except Exception as e:
        print('Failed to initialize BrowserSession CDP session:', e)
        return

    # Navigate to product URL using session.navigate_to
    try:
        await session.navigate_to(PRODUCT_URL, new_tab=False)
    except Exception as e:
        print('Navigate failed:', e)

    # Wait a bit for page to load
    await asyncio.sleep(3)

    # Use DomService to capture DOM snapshot and build EnhancedDOMTree (serialized + EnhancedDOMTreeNode)
    dom_service = DomService(session)
    async with dom_service:
        targets = await session._cdp_get_all_pages()
        if not targets:
            print('No page targets found')
            return
        target_id = targets[-1]['targetId']
        print('Using target id', target_id)

        # Ensure our agent focus is set to this target so get_serialized_dom_tree() can use it
        try:
            await session.get_or_create_cdp_session(target_id=target_id, focus=True)
        except Exception:
            pass

        # capture serialized DOM state and the enhanced DOM root
        try:
            serialized_state, enhanced_root, timings = await dom_service.get_serialized_dom_tree(None)
        except Exception as e:
            print('DOM capture/serialization failed:', e)
            return

    # Traverse EnhancedDOMTreeNode to find candidate interactive nodes (buttons/inputs) whose
    # meaningful text contains "add to" or variants (case-insensitive).
    candidates: list = []

    def traverse_and_collect(node):
        try:
            # Use the helper that aggregates meaningful text for LLM
            text = node.get_meaningful_text_for_llm().lower() if hasattr(node, 'get_meaningful_text_for_llm') else ''
        except Exception:
            text = ''

        # Check attributes and tag heuristics
        attrs = getattr(node, 'attributes', {}) or {}
        tag = (getattr(node, 'tag_name', None) or '').lower()

        is_button_like = tag in ('button', 'a', 'input')
        class_attr = (attrs.get('class') or '').lower()

        if ('add to' in text) or ('addtocart' in class_attr) or ('add-to-cart' in class_attr) or ('add to cart' in text):
            candidates.append(node)
        elif is_button_like and any(k in text for k in ('add', 'add to cart', 'add to')):
            candidates.append(node)

        for child in getattr(node, 'children_nodes', []) or []:
            traverse_and_collect(child)

    traverse_and_collect(enhanced_root)

    print('Found candidate EnhancedDOMTreeNode count:', len(candidates))

    # Build watchdog instance
    DefaultActionWatchdog.model_rebuild()
    watchdog = DefaultActionWatchdog(event_bus=session.event_bus, browser_session=session)

    if not candidates:
        print('No candidates found in enhanced DOM — try a different product URL or selector')
        return

    # Try clicking the top candidate(s) using the watchdog internal click implementation.
    # Save artifacts (screenshot + HTML) if the click fails for debugging.
    cdp_session = await session.get_or_create_cdp_session(target_id=target_id, focus=True)

    for idx, node in enumerate(candidates[:3]):
        print(f'Attempting watchdog click on candidate {idx}: "{node.get_meaningful_text_for_llm()[:80]}"')
        try:
            result = await watchdog._click_element_node_impl(node, while_holding_ctrl=False)
            print('Click result metadata:', result)
            # Give the page a moment to react
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f'Watchdog click on candidate {idx} failed: {e}')
            # Capture screenshot and HTML for analysis
            ts = int(time.time())
            try:
                ss = await cdp_session.cdp_client.send.Page.captureScreenshot(session_id=cdp_session.session_id)
                img_data = ss.get('data')
                if img_data:
                    img_path = os.path.join(ARTIFACTS_DIR, f'flipkart_watchdog_failure_{ts}.png')
                    with open(img_path, 'wb') as f:
                        import base64

                        f.write(base64.b64decode(img_data))
                    print('Saved screenshot to', img_path)
            except Exception as se:
                print('Failed to capture screenshot:', se)

            try:
                html_eval = await cdp_session.cdp_client.send.Runtime.evaluate(
                    params={'expression': 'document.documentElement.outerHTML', 'returnByValue': True},
                    session_id=cdp_session.session_id,
                )
                html = html_eval.get('result', {}).get('value')
                if html:
                    html_path = os.path.join(ARTIFACTS_DIR, f'flipkart_watchdog_failure_{ts}.html')
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(html)
                    print('Saved HTML to', html_path)
            except Exception as se:
                print('Failed to capture HTML:', se)

    print('CDP prototype run complete')

if __name__ == '__main__':
    asyncio.run(main())
