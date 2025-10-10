import asyncio
from playwright.async_api import async_playwright
import os

async def run_flipkart_add_to_cart():
    """
    Integration test for Flipkart Add to Cart.
    Handles interstitials and retries safely without closing browser prematurely.
    """

    product_url = "https://www.flipkart.com/google-pixel-9-obsidian-256-gb/p/itm330ed8ebeefe1"
    artifacts_dir = os.path.join(os.path.dirname(__file__), "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)

    print(f"Attempting host variant www.flipkart.com: {product_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(product_url, timeout=60000)

            # Try removing interstitial popups ("Try now" or "✕" close buttons)
            for attempt in range(1, 4):
                try:
                    print(f"Clicking interstitial Try now button (attempt {attempt})")
                    await page.click("button:has-text('Try now')", timeout=3000)
                    await asyncio.sleep(2)
                except Exception:
                    print(f"No 'Try now' button found in attempt {attempt}")

                try:
                    await page.click("button:has-text('✕')", timeout=2000)
                    print("Closed popup via '✕' button.")
                except Exception:
                    pass

                await asyncio.sleep(attempt + 1)

                # If page closed, reopen
                if page.is_closed():
                    print("⚠️ Page closed unexpectedly, reopening...")
                    page = await context.new_page()
                    await page.goto(product_url)

            # Attempt Add to Cart
            try:
                selectors = [
                    "button[data-testid='add-to-cart-button']",
                    "button[aria-label*='Add to cart']",
                    "button:has-text('Add to cart')",
                    "._2KpZ6l._2U9uOA._3v1-ww",
                ]

                clicked = False
                for selector in selectors:
                    try:
                        await page.wait_for_selector(selector, timeout=5000)
                        await page.click(selector)
                        print(f"✅ Clicked selector: {selector}")
                        clicked = True
                        break
                    except Exception:
                        continue

                if not clicked:
                    print("❌ No valid selector clicked; trying JS fallback...")
                    await page.evaluate("""
                        const btn = [...document.querySelectorAll('button')].find(b =>
                            b.textContent.toLowerCase().includes('add to cart')
                        );
                        if (btn) { btn.scrollIntoView(); btn.click(); return true; }
                        return false;
                    """)
                    print("✅ JS fallback executed.")

            except Exception as e:
                print(f"❌ Add to cart failed: {e}")

            # Wait and verify cart update
            await asyncio.sleep(5)
            current_url = page.url
            if "cart" in current_url.lower():
                print("✅ Redirected to cart page")
            else:
                print("❌ Add to cart not detected; saving artifacts...")
                try:
                    png_path = os.path.join(artifacts_dir, "flipkart_failure.png")
                    html_path = os.path.join(artifacts_dir, "flipkart_failure.html")
                    await page.screenshot(path=png_path, full_page=True)
                    html_content = await page.content()
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    print(f"🧩 Saved artifacts: {png_path}, {html_path}")
                except Exception as e:
                    print(f"⚠️ Failed to save artifacts: {e}")

        finally:
            print("🕓 Keeping browser open for inspection...")
            await asyncio.sleep(5)
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_flipkart_add_to_cart())
