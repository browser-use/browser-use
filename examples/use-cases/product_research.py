"""
Goal: Research product prices across different e-commerce platforms
Requires the same environment setup as jobs script (OPENAI_API_KEY/AZURE vars)
"""

import asyncio
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

# Validate environment variables
load_dotenv()


logger = logging.getLogger(__name__)
controller = Controller()

class Product(BaseModel):
    name: str
    price: str
    platform: str
    url: str
    seller: Optional[str] = None
    rating: Optional[float] = None

@controller.action('Save product research results', param_model=Product)
def save_product(product: Product):
    with open('products.csv', 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([product.name, product.price, product.platform, 
                        product.url, product.seller, product.rating])
    return 'Saved product data'

@controller.action('Read existing research data')
def read_products():
    with open('products.csv', 'r') as f:
        return f.read()

async def get_price_from_page(browser: BrowserContext, platform: str):
    # Different selectors for different e-commerce platforms
    selectors = {
        'amazon': {'price': '.a-price-whole', 'seller': '#sellerProfileTriggerId'},
        'flipkart': {'price': '._30jeq3', 'seller': '._1RLviY'}
    }
    
    price_el = await browser.get_dom_element_by_selector(selectors[platform]['price'])
    seller_el = await browser.get_dom_element_by_selector(selectors[platform]['seller'])
    
    return {
        'price': await price_el.get_text() if price_el else 'Price not found',
        'seller': await seller_el.get_text() if seller_el else None
    }

@controller.action('Check Amazon price for product')
async def check_amazon(product_name: str, browser: BrowserContext):
    await browser.goto('https://www.amazon.in')
    await browser.type_text('input#twotabsearchtextbox', product_name)
    await browser.press_enter()
    
    await asyncio.sleep(2)  # Wait for search results
    first_result = await browser.get_dom_element_by_selector('div[data-component-type="s-search-result"]:first-child')
    
    if not first_result:
        return ActionResult(error="No results found")
        
    await first_result.click()
    await asyncio.sleep(1)  # Wait for product page load
    
    price_info = await get_price_from_page(browser, 'amazon')
    current_url = await browser.get_current_url()
    
    return ActionResult(extracted_content=str(Product(
        name=product_name,
        price=price_info['price'],
        platform='Amazon',
        url=current_url,
        seller=price_info['seller']
    )))

@controller.action('Check Flipkart price for product')
async def check_flipkart(product_name: str, browser: BrowserContext):
    await browser.goto('https://www.flipkart.com')
    await browser.type_text('input[title="Search for Products, Brands and More"]', product_name)
    await browser.press_enter()
    
    await asyncio.sleep(2)
    first_result = await browser.get_dom_element_by_selector('div._1AtVbE:first-child')
    
    if not first_result:
        return ActionResult(error="No results found")
        
    await first_result.click()
    await asyncio.sleep(1)
    
    price_info = await get_price_from_page(browser, 'flipkart')
    current_url = await browser.get_current_url()
    
    return ActionResult(extracted_content=str(Product(
        name=product_name,
        price=price_info['price'],
        platform='Flipkart',
        url=current_url,
        seller=price_info['seller']
    )))

browser = Browser(
    config=BrowserConfig(
        chrome_instance_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',
        disable_security=True,
    )
)

async def main():
    # Read wishlist from file
    with open('wishlist.txt', 'r') as f:
        wishlist = [line.strip() for line in f.readlines() if line.strip()]

    if not wishlist:
        print("No items found in wishlist.txt")
        return

    model = ChatOpenAI(
        model='gpt-4o',
        temperature=0
    )

    agent = Agent(
        task=f"Product research task list:\n{chr(10).join(wishlist)}\n\n"
             "Instructions:\n"
             "1. Process items sequentially from the list\n"
             "2. For each item:\n"
             "   a. First check Amazon.in\n"
             "      i. Navigate to amazon.in\n"
             "      ii. Perform search workflow\n"
             "      iii. Record price details\n"
             "   b. Then check Flipkart.com\n"
             "      i. Navigate to flipkart.com\n"
             "      ii. Perform search workflow\n"
             "      iii. Record price details\n"
             "   c. Complete both platforms for current product before next\n"
             "3. Strict execution order:\n"
             "   Product N → Amazon → Flipkart → Product N+1\n"
             "4. Never alternate between products or platforms\n"
             "5. Maintain website order: Always Amazon first, Flipkart second",
        llm=model,
        controller=controller,
        browser=browser
    )

    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())