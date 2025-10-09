"""
Flipkart Add-to-Cart Integration Script (Enhanced)
--------------------------------------------------
This script:
- Opens a Flipkart product page
- Handles popups and interstitials
- Selects the first variant if required
- Clicks Add to Cart (with Playwright + JS + coordinate fallback)
- Detects cart update or login modal
- Saves artifacts on failure
"""

import time
import os
from playwright.sync_api import sync_playwright

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# ✅ Use a real product URL
PRODUCT_URL = "https://www.flipkart.com/google-pixel-9-obsidian-256-gb/p/itm330ed8ebeefe1"

# Common selectors for Add to Cart buttons
SELECTORS = [
    "button[data-testid='add-to-cart-button']",
    "button[aria-label*='Add to cart']",
    "button:has-text('Add to Cart')",
    "._2KpZ6l._2U9uOA._3v1-ww",  # Common Flipkart button class
]

def remove_interstitials(page):
    """Remove Flipkart popups or interstitial elements."""
    try:
        removed = page.evaluate(
            """
            () => {
                const elements = Array.from(document.querySelectorAll('._2MlkI1, ._2QfC02, ._3dsJAO'));
                elements.forEach(e => e.remove());
                return elements.length;
            }
            """
        )
        if removed:
            print(f"Removed interstitial elements via JS ({removed} elements)")
        return removed
    except Exception:
        return 0


def select_first_variant(page):
    """Select the first available product variant (size, color, etc.)."""
    try:
        variants = page.query_selector_all("._1fGeJ5, ._3aPjap, ._2YxCDZ")
        if variants:
            variants[0].click()
            print("Selected first available variant")
            time.sleep(1)
    except Exception:
        pass


def click_with_fallback(page, selector):
    """Try Playwright click, JS click, coordinate click, and wait for cart reaction."""
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=5000):
            page.click(selector, timeout=5000)
        print("Clicked via Playwright + navigation wait")
        return True
    except Exception:
        pass

    try:
        res = page.evaluate(
            "(sel)=>{const e=document.querySelector(sel); if(!e) return false;"
            "e.scrollIntoView({block:'center'}); e.click(); return true;}", selector
        )
        if res:
            print("Clicked via JS fallback")
            return True
    except Exception:
        pass

    try:
        rect = page.eval_on_selector(selector, "el => el.getBoundingClientRect()")
        x = rect["x"] + rect["width"] / 2
        y = rect["y"] + rect["height"] / 2
        page.mouse.click(x, y)
        print("Clicked via coordinate fallback")
        return True
    except Exception:
        pass

    return False


def check_cart(page):
    """Check if cart or login popup appeared."""
    try:
        url = page.url.lower()
        if "viewcart" in url or "cart" in url:
            print("✅ Redirected to cart page")
            return True

        # Detect Flipkart login modal
        if page.query_selector("form._36yFo0") or page.query_selector("input._2IX_2-"):
            print("⚠️  Login modal detected — item not yet added")
            return False

        # Check cart badge count
        cart_el = page.query_selector("span._2d0we9") or page.query_selector("span._3zBRUB")
        if cart_el:
            count_text = cart_el.inner_text().strip() or "0"
            count = int(''.join(filter(str.isdigit, count_text)) or "0")
            if count > 0:
                print(f"✅ Cart count updated: {count}")
                return True
    except Exception as e:
        print("Cart check error:", e)

    # Fallback: text-based detection
    try:
        body = page.evaluate("() => document.body.innerText.toLowerCase()")
        if "added to cart" in body or "added successfully" in body:
            print("✅ Add-to-cart success text detected")
            return True
    except Exception:
        pass

    return False


def save_artifacts(page, prefix="flipkart_failure"):
    """Save screenshot and HTML for debugging."""
    ts = int(time.time())
    base = os.path.join(ARTIFACTS_DIR, f"{prefix}_{ts}")
    page.screenshot(path=f"{base}.png", full_page=True)
    with open(f"{base}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    with open(f"{base}.dom.html", "w", encoding="utf-8") as f:
        f.write(page.evaluate("() => document.documentElement.outerHTML"))
    print(f"Saved artifacts: {base}.png {base}.html {base}.dom.html")


def run_flipkart_add_to_cart():
    """Main function."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        page = browser.new_page()
        page.goto(PRODUCT_URL, wait_until="domcontentloaded")
        print(f"Trying host variant: www.flipkart.com {PRODUCT_URL}")

        remove_interstitials(page)
        select_first_variant(page)

        success = False
        for selector in SELECTORS:
            try:
                remove_interstitials(page)
                page.wait_for_selector(selector, timeout=5000)
                if click_with_fallback(page, selector):
                    time.sleep(5)
                    if check_cart(page):
                        success = True
                        break
            except Exception:
                continue

        if not success:
            print("❌ Add to cart failed; saving artifacts")
            save_artifacts(page)

        browser.close()


if __name__ == "__main__":
    run_flipkart_add_to_cart()
