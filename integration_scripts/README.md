Integration script to exercise click fallbacks using Playwright

Requirements:

- Python 3.11
- Playwright (install and browsers):

    python -m pip install playwright
    python -m playwright install

Run the script (visible browser for debugging):

    python integration_scripts\amazon_add_to_cart_playwright.py

Notes:
- The script tries a normal Playwright click, then a JS fallback (scrollIntoView + el.click()), then a coordinate click as a last resort.
- It performs a simple content check for string indicators of a successful add-to-cart; for reliable checks, inspect the site-specific cart UI or network events.
- Use headless=True in the script if you want headless runs, but debugging is easier in a visible browser.
