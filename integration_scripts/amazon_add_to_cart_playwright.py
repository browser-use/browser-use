"""
Simple Playwright script to navigate to a product URL and attempt to add to cart.
This script demonstrates both coordinate click and JS click (scrollIntoView + el.click()) fallbacks.

Requirements:
- Install playwright and browsers: python -m pip install playwright; playwright install
- Run with: python amazon_add_to_cart_playwright.py

Note: This script runs a visible browser by default for debugging; set headless=True in playwright.launch() to run headless.
"""
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import time
import sys
import os

PRODUCT_URL = "https://www.amazon.in/SWORNOF-Womens-Banarasi-Patola-Blouse/dp/B099NX2BGX/ref=sxin_15_pa_sp_search_thematic_sspa?adgrpid=1322714098021561&content-id=amzn1.sym.9a76411d-317d-49e2-91d3-88a4af9140e5%3Aamzn1.sym.9a76411d-317d-49e2-91d3-88a4af9140e5&cv_ct_cx=flipkart%2Bonline%2Bshopping&hvadid=82669890077094&hvbmt=be&hvdev=c&hvlocphy=143956&hvnetw=o&hvqmt=e&hvtargid=kwd-82670515805048%3Aloc-90&hydadcr=26727_2475685&keywords=flipkart%2Bonline%2Bshopping&mcid=1350bbd75b8a3786bea44c79f0a75293&pd_rd_i=B099NX2BGX&pd_rd_r=1f4565dd-908f-42c7-b302-952bb8a46077&pd_rd_w=d86JP&pd_rd_wg=qtIET&pf_rd_p=9a76411d-317d-49e2-91d3-88a4af9140e5&pf_rd_r=KEQVZ6R468R0F3046VCH&qid=1760035107&sbo=RZvfv%2F%2FHxDF%2BO5021pAnSA%3D%3D&sr=1-1-ced4eeeb-b190-41d6-902a-1ecb3fb8b7c4-spons&sp_csd=d2lkZ2V0TmFtZT1zcF9zZWFyY2hfdGhlbWF0aWM&th=1"
ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), 'artifacts')


def ensure_artifacts_dir():
    try:
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    except Exception:
        pass


def close_common_cookie_banners(page):
    # Try several common selectors for cookie/consent banners
    candidates = [
        '#sp-cc-accept',
        'input[name="accept"]',
        'button#accept',
        'button[data-action="accept-cookies"]',
        'button[data-testid="accept"]',
        'button.cookie-accept',
        'div.cookieBanner button',
    ]
    for sel in candidates:
        try:
            el = page.query_selector(sel)
            if el:
                try:
                    el.click(timeout=1000)
                    print('Closed cookie/consent via', sel)
                    time.sleep(0.4)
                except Exception:
                    try:
                        page.evaluate("(s)=>{const e=document.querySelector(s); if(e) e.remove();}", sel)
                        print('Removed cookie element via JS', sel)
                    except Exception:
                        pass
        except Exception:
            continue


def select_first_size_option(page):
    # Amazon has several patterns for size/variant selectors. Try a few.
    selectors = [
        'select#native_dropdown_selected_size_name',
        'select#dropdown_selected_size_name',
        'div#variation_size_name select',
        'div#variation_size_name',
        'li[data-attrname="size_name"]',
        'div[data-asin] .a-button-text',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            tag = page.evaluate("s => document.querySelector(s) && document.querySelector(s).tagName.toLowerCase()", sel)
            if tag == 'select':
                # pick first non-disabled option
                options = page.query_selector_all(sel + ' option')
                for opt in options:
                    val = opt.get_attribute('value')
                    disabled = opt.get_attribute('disabled')
                    if val and not disabled:
                        try:
                            page.select_option(sel, value=val)
                            print('Selected size via select:', val)
                            time.sleep(0.3)
                            return True
                        except Exception:
                            continue
            else:
                # try clickable swatches inside the container
                swatches = page.query_selector_all(sel + ' li, ' + sel + ' .a-button-inner, ' + sel + ' a')
                for s in swatches:
                    try:
                        s.click()
                        print('Clicked size swatch inside', sel)
                        time.sleep(0.3)
                        return True
                    except Exception:
                        continue
        except Exception:
            continue
    return False


def try_click_with_fallbacks(page, selector, screenshot_name_prefix='click'):
    # Try normal click first (Playwright high-level)
    try:
        page.click(selector, timeout=4000)
        print('Clicked via playwright click')
        return True
    except Exception as e:
        print('Playwright click failed:', e)

    # Try scrollIntoView + JS click
    try:
        res = page.evaluate(
            "(sel) => { const el = document.querySelector(sel); if (!el) return false; el.scrollIntoView({block: 'center'}); el.click(); return true; }",
            selector,
        )
        if res:
            print('Clicked via JS fallback (scrollIntoView + click)')
            return True
        else:
            print('JS fallback returned falsy result')
    except Exception as e:
        print('JS fallback failed:', e)

    # Try coordinate-based click at center of bounding box
    try:
        rect = page.eval_on_selector(selector, "el => el.getBoundingClientRect()")
        x = rect['x'] + rect['width'] / 2
        y = rect['y'] + rect['height'] / 2
        page.mouse.click(x, y)
        print('Clicked via coordinate click')
        return True
    except Exception as e:
        print('Coordinate click failed:', e)

    return False


def check_cart_update(page, before_count=None):
    # Check cart count element
    try:
        cart_count_el = page.query_selector('#nav-cart-count') or page.query_selector('#nav-cart-count-container')
        if cart_count_el:
            text = cart_count_el.inner_text().strip()
            try:
                n = int(text)
            except Exception:
                n = None
            if before_count is None:
                return n is not None and n > 0
            if n is not None and before_count is not None and n > before_count:
                return True
    except Exception:
        pass

    # Check for side-sheet or confirmation message
    try:
        # Amazon attaches various IDs for add-to-cart side sheet
        confirm_selectors = [
            '#attach-added-to-cart-message',
            '#attachDisplayAddBase',
            '#huc-v2-order-row-confirm-text',
            "text='Added to Cart'",
            "text='Added to Your Cart'",
            '#sw-gtc-message',
            'div#addToCart_feature_div',
            '#sims-consolidated-1_feature_div',
        ]
        for cs in confirm_selectors:
            try:
                if page.query_selector(cs) or page.locator(cs).count() > 0:
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Fallback: check document text for common phrases
    try:
        body_text = page.evaluate("() => document.body.innerText || ''") or ''
        lowered = body_text.lower()
        if 'added to cart' in lowered or 'added to your cart' in lowered or 'added to cart from' in lowered:
            return True
    except Exception:
        pass

    return False


def main():
    ensure_artifacts_dir()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(PRODUCT_URL, timeout=30000)
        except Exception as e:
            print('Failed to load product URL:', e)

        time.sleep(2)

        # Close cookie/consent banners if present
        close_common_cookie_banners(page)

        # Maybe need to select size/variant before adding to cart
        selected = select_first_size_option(page)
        if selected:
            print('Selected size/variant')

        # Read current cart count
        try:
            cart_before = None
            el = page.query_selector('#nav-cart-count')
            if el:
                try:
                    cart_before = int(el.inner_text().strip())
                except Exception:
                    cart_before = None
        except Exception:
            cart_before = None

        # Common Amazon Add to Cart selectors
        selectors = [
            '#add-to-cart-button',
            '#add-to-cart-button-ubb',
            'input#add-to-cart-button',
            'button[name="add"]',
            'button#addToCart',
            'input[name="submit.add-to-cart"]',
        ]

        clicked = False
        for sel in selectors:
            try:
                if page.query_selector(sel):
                    print('Found selector:', sel)
                    clicked = try_click_with_fallbacks(page, sel)
                    print('Clicked selector:', sel, 'success=', clicked)
                    if clicked:
                        break
            except Exception as e:
                print('Selector query failed for', sel, e)

        # Wait for any cart update
        print('Waiting for cart update...')
        found = False
        for _ in range(10):
            time.sleep(0.6)
            try:
                if check_cart_update(page, before_count=cart_before):
                    found = True
                    break
            except Exception:
                pass

        if found:
            print('Add to cart likely succeeded (cart update detected)')
        else:
            print('Add to cart not detected; taking screenshot and saving HTML')
            try:
                ts = int(time.time())
                screenshot_path = os.path.join(ARTIFACTS_DIR, f'add_to_cart_failure_{ts}.png')
                html_path = os.path.join(ARTIFACTS_DIR, f'add_to_cart_failure_{ts}.html')
                page.screenshot(path=screenshot_path, full_page=True)
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(page.content())
                print('Saved screenshot and HTML to', ARTIFACTS_DIR)
                print('Files:', screenshot_path, html_path)
            except Exception as e:
                print('Failed to save artifacts:', e)

        context.close()
        browser.close()


if __name__ == '__main__':
    main()
