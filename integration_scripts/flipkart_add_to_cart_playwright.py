"""
Playwright script to attempt Add-to-Cart on a Flipkart product page.
Falls back through: Playwright.click() -> JS scrollIntoView + el.click() -> coordinate click.
Saves timestamped artifacts on failure.

Run:
    python flipkart_add_to_cart_playwright.py

Requirements:
    python -m pip install playwright
    python -m playwright install
"""
from playwright.sync_api import sync_playwright
import time
import os

# Example Flipkart product (replace with your URL)
PRODUCT_URL = "https://www.flipkart.com/example-product/p/itmexample"
ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), 'artifacts')
HOST_VARIANTS = [
    'www.flipkart.com',
    'flipkart.com',
    'www.flipkart.in',
    'flipkart.in',
    'm.flipkart.com',
]


def ensure_artifacts_dir():
    try:
        os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    except Exception:
        pass


def close_common_popups(page):
    # Close login modal or cookie banner
    candidates = [
        'button._2KpZ6l._2doB4z',  # Flipkart close button for login modal
        'button._2KpZ6l._2doB4z',
        'button._2KpZ6l._2doB4z',
        'button[data-testid="cookie-policy-accept"]',
        'button[aria-label="Close"]',
    ]
    for sel in candidates:
        try:
            el = page.query_selector(sel)
            if el:
                try:
                    el.click(timeout=1000)
                    print('Closed popup via', sel)
                    time.sleep(0.3)
                except Exception:
                    try:
                        page.evaluate("(s)=>{const e=document.querySelector(s); if(e) e.remove();}", sel)
                        print('Removed popup via JS', sel)
                    except Exception:
                        pass
        except Exception:
            continue


def select_first_variant(page):
    # Flipkart uses variants like size/color as buttons inside a container with class _2J4LW6 or similar
    selectors = [
        'div._2J4LW6',
        'div._1KHd47',
        'div._2J4LW6._3Ik3zX',
    ]
    for sel in selectors:
        try:
            container = page.query_selector(sel)
            if not container:
                continue
            buttons = container.query_selector_all('button')
            for b in buttons:
                try:
                    b.click()
                    print('Clicked variant button inside', sel)
                    time.sleep(0.3)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def try_click_with_fallbacks(page, selector):
    try:
        page.click(selector, timeout=4000)
        print('Clicked via playwright click')
        return True
    except Exception as e:
        print('Playwright click failed:', e)

    try:
        res = page.evaluate("(sel)=>{const el=document.querySelector(sel); if(!el) return false; el.scrollIntoView({block:'center'}); el.click(); return true;}", selector)
        if res:
            print('Clicked via JS fallback')
            return True
    except Exception as e:
        print('JS fallback failed:', e)

    try:
        rect = page.eval_on_selector(selector, "el=>el.getBoundingClientRect()")
        x = rect['x'] + rect['width']/2
        y = rect['y'] + rect['height']/2
        page.mouse.click(x, y)
        print('Clicked via coordinate click')
        return True
    except Exception as e:
        print('Coordinate click failed:', e)

    return False


def click_by_text_fallback(page, text_patterns=('add to cart', "add to bag", 'add to basket')):
    """Search buttons/links/inputs for common add-to-cart text and click the first match via JS."""
    try:
        # Robust JS: normalize whitespace, prefer visible elements, click nearest clickable ancestor
        script = '''(patterns)=>{
            const pats = patterns.map(p=>new RegExp(p,'i'));
            const els = Array.from(document.querySelectorAll('button,a,input'));
            function visible(el){
                try{
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width>0 && rect.height>0 && style && style.visibility!=='hidden' && style.display!=='none';
                }catch(e){return false}
            }
            for(const e of els){
                if(!visible(e)) continue;
                const t = ((e.innerText||e.value||'')+'').replace(/\s+/g,' ').trim();
                if(!t) continue;
                for(const r of pats){
                    if(r.test(t)){
                        try{
                            // prefer clicking the element itself, otherwise try the closest ancestor that is clickable
                            e.scrollIntoView({block:'center'});
                            e.click();
                            return {clicked:true, tag:e.tagName, text:t, cls:e.className||null};
                        }catch(err){
                            try{
                                const anc = e.closest('button,a'); if(anc){ anc.scrollIntoView({block:'center'}); anc.click(); return {clicked:true, tag:anc.tagName, text:anc.innerText||null, cls:anc.className||null}; }
                            }catch(e2){}
                        }
                    }
                }
            }
            return {clicked:false};
        }'''

        res = page.evaluate(script, list(text_patterns))
        if isinstance(res, dict) and res.get('clicked'):
            print('Clicked via text-based JS fallback ->', res.get('tag'), res.get('cls'), res.get('text')[:120])
            return True
    except Exception as e:
        print('Text-based JS fallback failed:', e)
    return False


def remove_interstitial(page):
    """Attempt to remove known Flipkart maintenance/interstitial elements from the DOM."""
    try:
        # Use a single, well-formed IIFE string to avoid broken concatenation or escaping
        script = '''(() => {
            try {
                const r = document.getElementById('retry_btn'); if (r) { r.remove(); }
            } catch(e){}
            try {
                const nodes = Array.from(document.querySelectorAll('div,section,main'));
                for (const n of nodes) {
                    const t = (n.innerText||'').toLowerCase();
                    if (t.includes('just a quick repair') || t.includes("we're doing everything") || t.includes('we\u2019re doing everything')) {
                        n.remove();
                    }
                }
            } catch(e){}
            try {
                // remove obvious overlays with high z-index or fixed positioning
                const overlays = Array.from(document.querySelectorAll('div,section'))
                    .filter(el => {
                        try {
                            const s = window.getComputedStyle(el);
                            return (s.position === 'fixed' || s.position === 'absolute') && parseInt(s.zIndex||0) > 1000;
                        } catch(e) { return false }
                    });
                for (const o of overlays) { o.remove(); }
            } catch(e){}
            return true;
        })()'''

        page.evaluate(script)
        print('Attempted to remove interstitial elements via JS')
        time.sleep(1)
        return True
    except Exception as e:
        print('Failed to remove interstitial via JS:', e)
    return False


def check_cart_update(page, before_count=None):
    # Flipkart cart count
    try:
        cart_el = page.query_selector('span._2d0we9') or page.query_selector('span._3zBRUB')
        if cart_el:
            try:
                text = cart_el.inner_text().strip()
                n = int(text)
            except Exception:
                n = None
            if before_count is None:
                return n is not None and n > 0
            if n is not None and before_count is not None and n > before_count:
                return True
    except Exception:
        pass

    # Look for confirmation phrases
    try:
        confirm_selectors = [
            "text='Added to cart'",
            "text='Added to Cart'",
            "div._3qQ9m1",  # sometimes Flipkart shows small toast-like divs
        ]
        for cs in confirm_selectors:
            try:
                if page.query_selector(cs) or page.locator(cs).count() > 0:
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Fallback: search document text
    try:
        body_text = page.evaluate("() => document.body.innerText || ''") or ''
        lowered = body_text.lower()
        if 'added to cart' in lowered or 'added to cart' in lowered:
            return True
    except Exception:
        pass

    return False


def main():
    ensure_artifacts_dir()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        # Use a common desktop user-agent and a larger viewport to mimic a real user
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        context = browser.new_context(user_agent=ua, viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        # collect console messages
        console_messages = []
        def _on_console(msg):
            try:
                console_messages.append({'type': msg.type, 'text': msg.text})
            except Exception:
                pass
        page.on('console', _on_console)

        # Try multiple host variants in case a specific host is serving an interstitial
        base_url = PRODUCT_URL
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(PRODUCT_URL)
        orig_path = parsed.path or ''
        orig_query = ('?' + parsed.query) if parsed.query else ''

        host_attempt = 0
        last_load_exception = None
        for host in HOST_VARIANTS:
            host_attempt += 1
            attempt_url = urlunparse((parsed.scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment))
            print(f'Attempting host variant {host} ({host_attempt}/{len(HOST_VARIANTS)}):', attempt_url)
            try:
                page.goto(attempt_url, timeout=30000)
                # allow DOM to stabilize
                page.wait_for_load_state('domcontentloaded', timeout=10000)
            except Exception as e:
                last_load_exception = e
                print('Load failed for', host, e)
                time.sleep(1 + host_attempt)
                continue
            # If loaded, break and continue the normal flow
            break

        time.sleep(2)

    # Detect Flipkart maintenance / quick-repair interstitial and try to click the retry button
        # The maintenance page has a #retry_btn that appears after a short countdown
        interstitial_tries = 0
        while interstitial_tries < 4:
            try:
                # If a retry button is visible, click it and wait for reload
                retry = page.query_selector('#retry_btn')
                if retry:
                    clicked_retry = False
                    for attempt in range(3):
                        try:
                            print('Clicking interstitial Try now button (attempt', attempt+1, ')')
                            retry.click(timeout=1500)
                            clicked_retry = True
                            time.sleep(1 + attempt)
                            page.wait_for_load_state('domcontentloaded', timeout=8000)
                            break
                        except Exception:
                            try:
                                # safer evaluate: IIFE that clicks the selector
                                page.evaluate("(function(s){const e=document.querySelector(s); if(e){ e.click(); return true;} return false;})", '#retry_btn')
                                clicked_retry = True
                                time.sleep(1 + attempt)
                                page.wait_for_load_state('domcontentloaded', timeout=8000)
                                break
                            except Exception:
                                time.sleep(1)
                    if not clicked_retry:
                        try:
                            page.reload()
                        except Exception:
                            pass
                        time.sleep(2 + interstitial_tries)
                # If we still see an interstitial marker text, reload and retry
                title = page.title().lower() if page.title() else ''
                body_text = ''
                try:
                    body_text = page.evaluate("() => document.body.innerText || ''") or ''
                except Exception:
                    pass
                if 'just a quick repair' in body_text.lower() or 'retry in' in body_text.lower() or 'we\u2019re doing everything' in body_text.lower() or 'quick repair' in title or 'maintenance' in title:
                    interstitial_tries += 1
                    wait_s = 2 + interstitial_tries
                    print(f'Interstitial detected, attempt {interstitial_tries}, waiting {wait_s}s then reloading')
                    time.sleep(wait_s)
                    try:
                        page.reload()
                    except Exception:
                        pass
                    time.sleep(1)
                    continue
                # otherwise break out — assume product page loaded
                break
            except Exception:
                break

        close_common_popups(page)

        # If the interstitial still exists, attempt to remove it via JS
        try:
            remove_interstitial(page)
        except Exception:
            pass

        if select_first_variant(page):
            print('Selected variant')

        # Read current cart count
        try:
            cart_before = None
            el = page.query_selector('span._2d0we9')
            if el:
                try:
                    cart_before = int(el.inner_text().strip())
                except Exception:
                    cart_before = None
        except Exception:
            cart_before = None

        selectors = [
            "button._2KpZ6l._2U9uOA._3v1-ww",  # Add to cart typical class
            "button._2KpZ6l._2U9uOA._3v1-ww._27W44V", 
            "button._2KpZ6l._2doB4z",  # sometimes appears
            "button[aria-label*='Add to cart']",
            "button[data-testid='add-to-cart-button']",
        ]

        clicked = False
        for sel in selectors:
            try:
                if page.query_selector(sel):
                    print('Found selector:', sel)
                    # small human-like mouse move before click
                    try:
                        rect = page.eval_on_selector(sel, "el=>el.getBoundingClientRect()")
                        cx = rect['x'] + rect['width']/2
                        cy = rect['y'] + rect['height']/2
                        # move a bit offset first
                        page.mouse.move(max(0, cx-10), max(0, cy-10))
                        page.wait_for_timeout(120)
                    except Exception:
                        try:
                            page.mouse.move(100, 100)
                        except Exception:
                            pass
                    clicked = try_click_with_fallbacks(page, sel)
                    print('Clicked selector:', sel, 'success=', clicked)
                    if clicked:
                        break
            except Exception as e:
                print('Selector query failed for', sel, e)

        # If no selector succeeded, try a text-based JS fallback
        if not clicked:
            try:
                print('No selector clicked; attempting text-based JS fallback')
                clicked = click_by_text_fallback(page)
                print('Text-based fallback success=', clicked)
            except Exception as e:
                print('Text fallback raised:', e)

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
            print('Add to cart likely succeeded')
        else:
            print('Add to cart not detected; saving artifacts')
            try:
                ts = int(time.time())
                screenshot_path = os.path.join(ARTIFACTS_DIR, f'flipkart_add_to_cart_failure_{ts}.png')
                html_path = os.path.join(ARTIFACTS_DIR, f'flipkart_add_to_cart_failure_{ts}.html')
                dom_path = os.path.join(ARTIFACTS_DIR, f'flipkart_add_to_cart_failure_{ts}.dom.html')
                console_path = os.path.join(ARTIFACTS_DIR, f'flipkart_add_to_cart_console_{ts}.log')
                page.screenshot(path=screenshot_path, full_page=True)
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(page.content())
                # Save outerHTML snapshot for easier inspection
                try:
                    outer = page.evaluate("() => document.documentElement.outerHTML")
                    with open(dom_path, 'w', encoding='utf-8') as f:
                        f.write(outer)
                except Exception:
                    pass
                # Save console messages
                try:
                    with open(console_path, 'w', encoding='utf-8') as f:
                        for m in console_messages:
                            f.write(f"[{m.get('type')}] {m.get('text')}\n")
                except Exception:
                    pass
                print('Saved artifacts:', screenshot_path, html_path)
            except Exception as e:
                print('Failed to save artifacts:', e)

        context.close()
        browser.close()


if __name__ == '__main__':
    main()
