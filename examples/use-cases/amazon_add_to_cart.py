"""
Goal: Reads a wishlist from a text file and adds products to Amazon cart

@dev You need to add OPENAI_API_KEY to your environment variables.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

# Validate required environment variables
load_dotenv()

logger = logging.getLogger(__name__)
controller = Controller()
#Make a wishlist.txt file in the same directory as the script and add the products you want to add to the cart
WISHLIST_FILE = Path.cwd() / 'wishlist.txt'

if not WISHLIST_FILE.exists():
    raise FileNotFoundError(f'Wishlist file not found at {WISHLIST_FILE}')

class Product(BaseModel):
    name: str
    url: Optional[str] = None
    added_to_cart: bool = False

@controller.action('Read wishlist from file')
def read_wishlist():
    with open(WISHLIST_FILE, 'r') as f:
        products = [line.strip() for line in f.readlines() if line.strip()]
    return ActionResult(extracted_content="\n".join(products), include_in_memory=True)

@controller.action('Save product to file after adding to cart', param_model=Product)
def save_product(product: Product):
    return ActionResult(extracted_content=f"Processed product: {product.name}")

@controller.action('Add product to Amazon cart')
async def add_to_cart(product_name: str, browser: BrowserContext):
    try:
        # Navigate to Amazon
        await browser.goto("https://www.amazon.in")
        
        # Search for the product
        search_box = await browser.get_dom_element_by_placeholder("Search Amazon")
        if search_box:
            await search_box.type(product_name)
            await search_box.press("Enter")
        else:
            return ActionResult(error="Could not find Amazon search box")
        await asyncio.sleep(2)
        
        first_product = await browser.get_dom_element_by_xpath("//div[@data-component-type='s-search-result']//a[@class='a-link-normal s-no-outline']")
        if first_product:
            await first_product.click()
        else:
            return ActionResult(error="Could not find product in search results")
        
        await asyncio.sleep(2)
        
        # Handle "Add to Cart" button
        add_to_cart_btn = await browser.get_dom_element_by_id("add-to-cart-button")
        if not add_to_cart_btn:
            # Try alternate button selectors
            add_to_cart_btn = await browser.get_dom_element_by_xpath("//input[@id='add-to-cart-button']") or \
                             await browser.get_dom_element_by_xpath("//span[@id='submit.add-to-cart']")
        
        if add_to_cart_btn:
            await add_to_cart_btn.click()
            await asyncio.sleep(2)
            
            confirmation = await browser.get_dom_element_by_id("NATC_SMART_WAGON_CONF_MSG_SUCCESS")
            if confirmation:
                return ActionResult(
                    extracted_content=f"Successfully added {product_name} to cart",
                    data=Product(name=product_name, added_to_cart=True)
                )
            else:
                return ActionResult(error=f"Added {product_name} but couldn't verify success")
        else:
            return ActionResult(error=f"Could not find 'Add to Cart' button for {product_name}")
    
    except Exception as e:
        logger.error(f"Error adding product to cart: {str(e)}")
        return ActionResult(error=f"Failed to add {product_name} to cart: {str(e)}")

browser = Browser(
    config=BrowserConfig(
        #Currently the local brave browser is used as the browser instance
        #You can change the browser instance path to the path of the browser you want to use
        #for chrome browser 
        #chrome_instance_path='C:/Program Files/Google/Chrome/Application/chrome.exe' or the path of the chrome browser on your system
        chrome_instance_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',
        disable_security=True,
    )
)

async def main():
    ground_task = (
        "You are an automated shopping assistant. "
        "1. Read the wishlist from the file with read_wishlist "
        "2. First of all go to the website https://www.amazon.in and search for the product with the name in the wishlist in the search bar of the amazon "
        "3. click on the first product in the search results "
        "4. click on the add to cart button "
        "5. Make sure to verify the product was added successfully "
        "Handle any errors gracefully and continue with the next product"
    )
    
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = Agent(task=ground_task, llm=model, controller=controller, browser=browser)
    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())