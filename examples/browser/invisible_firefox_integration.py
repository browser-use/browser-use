"""Run browser-use against a patched stealth Firefox binary (proposal).

Complement, not a replacement, for the patchright stealth path already
shipped via PR #857. Useful for cases where a specific target site
flags Chromium UA by default and a Firefox-side fallback is wanted.

Background:
- invisible_playwright (https://github.com/feder-cr/invisible_playwright)
  is a drop-in Playwright Python replacement
- the patched Firefox 150 binary lives at
  https://github.com/feder-cr/invisible_firefox (MPL-2.0, same license as
  Firefox upstream); fingerprint patches at the C++ source code level so
  there are no JS shims to detect
- this file shows how a user can wire that binary into a BrowserSession
  without changes to browser-use itself

Install:
    pip install invisible_playwright
    python -m invisible_playwright fetch
"""

import asyncio

try:
    from invisible_playwright.async_api import InvisiblePlaywright
except ImportError as e:
    print(f"missing dependency: {e}")
    print("install with: pip install invisible_playwright")
    print("then run: python -m invisible_playwright fetch")
    raise SystemExit(1)

from browser_use import Agent, BrowserSession, ChatOpenAI


async def main() -> None:
    # Launch the patched Firefox via invisible_playwright's context manager.
    # The returned `browser` is a standard playwright.async_api.Browser, so
    # it slots into BrowserSession the same way any custom browser would.
    async with InvisiblePlaywright(headless=False) as browser:
        session = BrowserSession(browser=browser)
        agent = Agent(
            task="Visit a site that normally blocks automation and report the page title.",
            llm=ChatOpenAI(model="gpt-4o"),
            browser_session=session,
        )
        result = await agent.run()
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
