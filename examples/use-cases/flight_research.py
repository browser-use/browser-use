import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

load_dotenv()
controller = Controller()

class FlightSearch(BaseModel):
    source: str = "Mumbai (BOM)"
    destination: str = "Delhi (DEL)"
    date: str = "2025-04-20"
    passengers: int = 1

class Flight(BaseModel):
    airline: str
    price: float
    departure_time: str
    duration: str
    link: str

@controller.action('Set flight search parameters', param_model=FlightSearch)
def set_search_params(params: FlightSearch):
    return params

@controller.action('Search for flights')
async def search_flights(browser: BrowserContext):
    await browser.goto('https://www.goibibo.com/flights/')
    await asyncio.sleep(5)

    # Close initial popup if exists
    try:
        close_btn = await browser.get_dom_element_by_selector('[class*="sc-jlwm9r-15"]')
        if close_btn:
            await close_btn.click()
    except:
        pass

    # Fill source
    source_input = await browser.get_dom_element_by_selector('[id="autoSuggest-list"]')
    await source_input.click()
    await browser.type_text('[placeholder="From"]', "Mumbai (BOM)")
    await asyncio.sleep(1)
    await browser.press_enter()

    # Fill destination
    dest_input = await browser.get_dom_element_by_selector('[placeholder="To"]')
    await dest_input.click()
    await browser.type_text('[placeholder="To"]', "Delhi (DEL)")
    await asyncio.sleep(1)
    await browser.press_enter()

    # Select date
    date_input = await browser.get_dom_element_by_selector('[data-testid="departure-date-input"]')
    await date_input.click()
    await asyncio.sleep(2)
    
    # Navigate to April 2025
    for _ in range(12):  # Maximum 12 months forward
        month_header = await browser.get_dom_element_by_selector('[class*="DayPicker-Caption"]')
        current_month = await month_header.get_text()
        if "April 2025" in current_month:
            break
        next_month_btn = await browser.get_dom_element_by_selector('[aria-label="Next Month"]')
        await next_month_btn.click()
        await asyncio.sleep(1)

    # Select date
    day_buttons = await browser.get_dom_elements_by_selector('[class*="DayPicker-Day"]')
    for day in day_buttons:
        aria_label = await day.get_attribute("aria-label")
        if aria_label and "Apr 20 2025" in aria_label:
            await day.click()
            break

    # Confirm date
    done_btn = await browser.get_dom_element_by_selector('[data-testid="dateDone"]')
    await done_btn.click()

    # Search flights
    search_btn = await browser.get_dom_element_by_selector('[data-testid="searchFlightBtn"]')
    await search_btn.click()
    await asyncio.sleep(10)

    return "Flight search initiated"

@controller.action('Find cheapest flight')
async def get_cheapest_flight(browser: BrowserContext):
    # Get all flight prices
    price_elements = await browser.get_dom_elements_by_selector('[class*="srp-card-uistyles__PriceText"]')
    
    prices = []
    for element in price_elements:
        price_text = await element.get_text()
        price = float(price_text.replace('₹', '').replace(',', ''))
        prices.append(price)
    
    if not prices:
        return ActionResult(error="No flights found")
    
    min_price = min(prices)
    
    # Get flight details for cheapest option
    cheapest_flight_element = price_elements[prices.index(min_price)]
    parent_card = await cheapest_flight_element.find_parent_element('[class*="srp-card-uistyles__CardWrapper"]')
    
    airline_element = await parent_card.query_selector('[class*="AirlineNameText"]')
    time_element = await parent_card.query_selector('[class*="srp-card-uistyles__DepTimeText"]')
    duration_element = await parent_card.query_selector('[class*="srp-card-uistyles__DurationText"]')
    
    return Flight(
        airline=await airline_element.get_text(),
        price=min_price,
        departure_time=await time_element.get_text(),
        duration=await duration_element.get_text(),
        link=await browser.get_current_url()
    )

browser = Browser(
    config=BrowserConfig(
    )
)

async def main():
    model = ChatOpenAI(
        model='gpt-4o',
        temperature=0
    )

    agent = Agent(
        task="Goibibo Flight Search Workflow:\n"
             "1. Navigate to Goibibo flights page\n"
             "Skip the initial popup if it appears\n"
             "Skip the phone number signup if it appears\n"
             "2. Set Mumbai as source\n"
             "3. Set Delhi as destination\n"
             "4. Select 20 April 2025\n"
             "5. Initiate search\n"
             "6. Parse results page\n"
             "7. Find cheapest flight option\n"
             "8. Return flight details",
        llm=model,
        controller=controller,
        browser=browser,
        use_vision=True
    )

    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())