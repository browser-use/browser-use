"""
Example demonstrating advanced OmniParser integration for complex UI scenarios.

This example shows how to use BrowserUse with OmniParser to handle:
1. Dynamically generated UI elements that traditional DOM selectors might miss
2. Complex forms with various input types
3. Advanced UI components like carousels, modals, and accordions
4. Extracting structured data from visual elements
"""

import asyncio
import logging
import sys
import os
import json
import base64
from datetime import datetime

# Add root to path to run as a script
sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig
from browser_use.browser.config import BrowserExtractionConfig
from browser_use.omniparser.views import OmniParserSettings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run the complex OmniParser example."""
    # Create a browser
    browser = Browser()
    await browser._init()

    # Configure browser with enhanced OmniParser integration
    context_config = BrowserContextConfig(
        extraction_config=BrowserExtractionConfig(
            # Enable hybrid extraction (combining DOM and OmniParser)
            use_hybrid_extraction=True,
            # Configure advanced OmniParser settings
            omniparser=OmniParserSettings(
                enabled=True,                 # Enable OmniParser
                confidence_threshold=0.4,     # Lower threshold for complex UIs
                captcha_detection=True,       # Enable specialized CAPTCHA detection
                merge_with_dom=True,          # Combine DOM and OmniParser results
                prefer_over_dom=True,        # Force OmniParser usage over DOM
                use_api=True                  # Use the hosted API if local installation is not available
            )
        )
    )

    # Create a browser context with the config
    context = await browser.new_context(config=context_config)
    
    try:
        # PART 1: Handle a complex form with dynamically generated elements
        await handle_complex_form(context)
        
        # PART 2: Work with a dynamic UI component (carousel/slider)
        await handle_dynamic_component(context)
        
        # PART 3: Extract structured information from a visually complex page
        await extract_visual_information(context)
        
    finally:
        # Clean up
        await context.close()
        await browser.close()


async def handle_complex_form(context):
    """Handle a complex form with dynamically generated fields."""
    logger.info("PART 1: Handling complex form interaction...")
    
    # Navigate to a page with a complex form
    # Using Airbnb's search form which has dynamic dropdowns and date pickers
    page = await context.get_current_page()
    await page.goto("https://www.airbnb.com/")
    
    # Wait for page to fully load
    await asyncio.sleep(3)
    
    # Get the initial state
    state = await context.get_state()
    logger.info(f"Initial state has {len(state.selector_map)} elements")
    
    # Take a screenshot of the initial state
    screenshot_base64 = await context.take_screenshot(full_page=False)
    with open("airbnb_initial.png", "wb") as f:
        f.write(base64.b64decode(screenshot_base64))
    logger.info("Saved initial screenshot to airbnb_initial.png")
    
    # Based on the screenshot, we can see multiple ways to identify the search field
    logger.info("Looking for the search/location input field...")
    
    # Try a direct approach first - click on the visible search bar
    try:
        # The search bar has "Where" label and "Search destinations" placeholder
        # Try clicking directly on elements with these texts
        await page.click("text=Where")
        logger.info("Successfully clicked on 'Where' field")
        
        await asyncio.sleep(1)
        
        # Type a search query
        await page.keyboard.type("London")
        logger.info("Entered 'London' as search text")
        
        await asyncio.sleep(1)
        
        # Take a screenshot with the search bar focused
        screenshot_base64 = await context.take_screenshot(full_page=False)
        with open("airbnb_search_active.png", "wb") as f:
            f.write(base64.b64decode(screenshot_base64))
        logger.info("Saved search screenshot to airbnb_search_active.png")
        
        # Try clicking on a suggestion if available
        try:
            await page.click("text=London, UK", timeout=3000)
            logger.info("Clicked on London, UK suggestion")
        except Exception as e:
            logger.info(f"No exact suggestion match found: {str(e)}")
            # Try a more general selector for a dropdown item
            try:
                await page.click("[data-testid='option-0']", timeout=3000)
                logger.info("Clicked on the first suggestion")
            except Exception as e2:
                logger.info(f"Could not click on suggestion: {str(e2)}")
        
        # Take a final screenshot
        await asyncio.sleep(1)
        screenshot_base64 = await context.take_screenshot(full_page=False)
        with open("airbnb_selection.png", "wb") as f:
            f.write(base64.b64decode(screenshot_base64))
        logger.info("Saved selection screenshot to airbnb_selection.png")
        
    except Exception as e:
        logger.info(f"Could not interact with search field using direct selectors: {str(e)}")
        
        # Fallback to more generic approach
        logger.info("Trying alternative search approach...")
        
        # Function to find potential search field elements
        search_elements = []
        def find_search_elements(element, depth=0):
            if not element:
                return
                
            # Check if this element looks like a search field
            is_search = False
            if hasattr(element, "attributes") and element.attributes:
                for attr, value in element.attributes.items():
                    # Check various attributes that might indicate a search field
                    if attr in ["placeholder", "aria-label", "title", "name", "class"]:
                        lower_value = value.lower()
                        if any(term in lower_value for term in ["where", "search", "destination", "location"]):
                            is_search = True
                            break
            
            # Check element text content
            if hasattr(element, "text") and element.text:
                lower_text = element.text.lower()
                if any(term in lower_text for term in ["where", "search destination"]):
                    is_search = True
            
            if is_search and hasattr(element, "highlight_index") and element.highlight_index is not None:
                search_elements.append(element)
            
            # Recursively check children
            if hasattr(element, "children") and element.children:
                for child in element.children:
                    find_search_elements(child, depth + 1)
        
        # Analyze the DOM to find search elements
        find_search_elements(state.element_tree)
        
        if search_elements:
            logger.info(f"Found {len(search_elements)} potential search elements")
            
            # Try to interact with the search element
            try:
                # Click the first search element found
                await page.click(f"xpath={search_elements[0].xpath}")
                logger.info(f"Clicked on search element with xpath: {search_elements[0].xpath}")
                
                await asyncio.sleep(1)
                
                # Enter search text
                await page.keyboard.type("London")
                logger.info("Entered 'London' as search text")
                
                # Take a screenshot
                screenshot_base64 = await context.take_screenshot(full_page=False)
                with open("airbnb_search_fallback.png", "wb") as f:
                    f.write(base64.b64decode(screenshot_base64))
                logger.info("Saved fallback search screenshot to airbnb_search_fallback.png")
            except Exception as e:
                logger.info(f"Failed to interact with search element: {str(e)}")
        else:
            logger.info("Could not find any search input field")
    
    logger.info("Complex form interaction complete")


async def handle_dynamic_component(context):
    """Work with a dynamic UI component like a carousel or slider."""
    logger.info("\nPART 2: Handling dynamic UI components...")
    
    # Navigate to a page with carousel/slider elements
    page = await context.get_current_page()
    await page.goto("https://getbootstrap.com/docs/5.3/examples/carousel/")
    
    # Wait for page to fully load
    await asyncio.sleep(2)
    
    # Take a screenshot of the initial carousel state
    screenshot_base64 = await context.take_screenshot(full_page=False)
    with open("carousel_initial.png", "wb") as f:
        f.write(base64.b64decode(screenshot_base64))
    logger.info("Saved initial carousel screenshot to carousel_initial.png")
    
    # Get the carousel state
    state = await context.get_state()
    
    # Look for carousel navigation buttons
    carousel_buttons = []
    
    # Function to detect carousel controls
    def find_carousel_controls(element, depth=0):
        if not element:
            return
            
        # Check for button or carousel attributes
        is_control = False
        if hasattr(element, "attributes") and element.attributes:
            for attr, value in element.attributes.items():
                if "carousel" in attr.lower() or "slide" in attr.lower():
                    is_control = True
                if attr == "class" and any(term in value for term in ["carousel", "prev", "next"]):
                    is_control = True
        
        if is_control and hasattr(element, "highlight_index") and element.highlight_index is not None:
            carousel_buttons.append({
                "tag": element.tag_name if hasattr(element, "tag_name") else "unknown",
                "highlight_index": element.highlight_index,
                "text": element.text if hasattr(element, "text") and element.text else None
            })
        
        # Recursively check children
        if hasattr(element, "children") and element.children:
            for child in element.children:
                find_carousel_controls(child, depth + 1)
    
    find_carousel_controls(state.element_tree)
    
    if carousel_buttons:
        logger.info(f"Found {len(carousel_buttons)} potential carousel controls")
        
        # Try to click "Next" button to navigate carousel
        next_buttons = [btn for btn in carousel_buttons if btn.get("text") and "next" in btn.get("text").lower()]
        
        if not next_buttons:  # If no buttons with "next" text found, try alternative approach
            next_buttons = [btn for btn in carousel_buttons if btn.get("tag") == "button"]
        
        if next_buttons:
            logger.info(f"Clicking carousel 'Next' button...")
            page = await context.get_current_page()
            # Use page.click with an appropriate selector
            if next_buttons[0].get("tag") == "button":
                await page.click("button.carousel-control-next")  # Common Bootstrap class for next button
            else:
                # Try to click by index if we can identify it
                await page.click(".carousel-control-next")
            await asyncio.sleep(1)
            
            # Take a screenshot after clicking next
            screenshot_base64 = await context.take_screenshot(full_page=False)
            with open("carousel_next.png", "wb") as f:
                f.write(base64.b64decode(screenshot_base64))
            logger.info("Saved carousel 'next' screenshot to carousel_next.png")
            
            # Try to click once more to see another slide
            await page.click(".carousel-control-next")
            await asyncio.sleep(1)
            
            # Take a final screenshot
            screenshot_base64 = await context.take_screenshot(full_page=False)
            with open("carousel_final.png", "wb") as f:
                f.write(base64.b64decode(screenshot_base64))
            logger.info("Saved final carousel screenshot to carousel_final.png")
        else:
            logger.info("Could not identify carousel next button")
    else:
        logger.info("No carousel controls detected")
    
    logger.info("Dynamic component interaction complete")


async def extract_visual_information(context):
    """Extract structured information from a visually complex page."""
    logger.info("\nPART 3: Extracting visual information...")
    
    # Navigate to a visually complex page with tabular or structured data
    # Using GitHub's trending page as an example
    page = await context.get_current_page()
    await page.goto("https://github.com/trending")
    
    # Wait for page to fully load
    await asyncio.sleep(3)
    
    # Take a screenshot
    screenshot_base64 = await context.take_screenshot(full_page=True)
    with open("github_trending.png", "wb") as f:
        f.write(base64.b64decode(screenshot_base64))
    logger.info("Saved GitHub trending page screenshot to github_trending.png")
    
    # Get the page state
    state = await context.get_state()
    
    # Structure to store repository information
    repositories = []
    
    # Function to extract repository information from elements
    def extract_repositories(element, in_repo_section=False, current_repo=None):
        """Extract repository information from DOM elements."""
        if not element:
            return
            
        # Check if this element has attributes
        if not hasattr(element, "attributes"):
            # Process children
            if hasattr(element, "children") and element.children:
                for child in element.children:
                    extract_repositories(child, in_repo_section, current_repo)
            return
            
        # Look for repository articles or repository elements
        # GitHub trending uses article elements with specific classes
        if element.tag_name == "article" or (
            hasattr(element, "attributes") and 
            element.attributes.get("class") and 
            "Box-row" in element.attributes.get("class", "")
        ):
            # Found a new repository entry
            current_repo = {"name": "", "description": "", "stars": "", "language": ""}
            repositories.append(current_repo)
            in_repo_section = True
            
            # Process this element's children
            if hasattr(element, "children") and element.children:
                for child in element.children:
                    extract_repositories(child, in_repo_section, current_repo)
            return
            
        # If we're inside a repository section, look for specific elements
        if in_repo_section and current_repo is not None:
            # Look for h1/h2/h3 elements with repo name or links with repo path
            if element.tag_name in ["h1", "h2", "h3"] or (
                element.tag_name == "a" and 
                hasattr(element, "attributes") and
                "href" in element.attributes and
                "/" in element.attributes["href"] and
                not element.attributes["href"].startswith("http")
            ):
                text = get_element_text(element)
                if text and not current_repo.get("name"):
                    # For repo names, we often need to check children or href attribute
                    if "/" in text:
                        current_repo["name"] = text.strip()
                    elif "href" in element.attributes:
                        href = element.attributes["href"].strip()
                        if href.startswith("/") and href.count("/") == 2:
                            # GitHub repo href format: /owner/repo
                            current_repo["name"] = href[1:]  # Remove leading slash
            
            # Look for repository description
            if element.tag_name == "p" and not current_repo.get("description"):
                text = get_element_text(element)
                if text and len(text) > 10:  # Likely a description
                    current_repo["description"] = text.strip()
            
            # Look for star count
            if (element.tag_name == "a" and 
                hasattr(element, "attributes") and
                "href" in element.attributes and
                "stargazers" in element.attributes["href"]):
                text = get_element_text(element)
                if text and not current_repo.get("stars"):
                    current_repo["stars"] = text.strip()
                    
            # Look for programming language
            if (hasattr(element, "attributes") and
                element.attributes.get("itemprop") == "programmingLanguage"):
                text = get_element_text(element)
                if text and not current_repo.get("language"):
                    current_repo["language"] = text.strip()
                    
        # Special case for repository name detection
        # Check if this element has a specific pattern matching GitHub repo names
        if in_repo_section and current_repo and not current_repo.get("name"):
            # Direct examination of the element's appearance
            if hasattr(element, "attributes") and element.attributes.get("href"):
                href = element.attributes["href"]
                
                # Handle login redirects
                if "login?return_to=" in href:
                    # Extract the actual repository path from the redirect URL
                    repo_path = href.split("return_to=")[1]
                    if repo_path.startswith("%2F"):  # URL-encoded slash
                        # Convert URL-encoded path to regular path
                        repo_path = repo_path.replace("%2F", "/")
                        if "/" in repo_path:
                            current_repo["name"] = repo_path.strip()
                elif href.startswith("/") and "/" in href[1:]:  # Simple /user/repo pattern
                    current_repo["name"] = href[1:]  # Remove leading slash
            
            # Try to find repo name patterns in the element text
            text = get_element_text(element)
            if text and "/" in text:
                # Check if it looks like a GitHub repo name (user/repo format)
                parts = text.split("/")
                if len(parts) == 2 and all(part.strip() for part in parts):
                    current_repo["name"] = text.strip()
        
        # Recursively process children
        if hasattr(element, "children") and element.children:
            for child in element.children:
                extract_repositories(child, in_repo_section, current_repo)
    
    # Helper to extract text from an element
    def get_element_text(element):
        """Get text content from an element."""
        if hasattr(element, "text") and element.text:
            return element.text
        elif hasattr(element, "attributes") and element.attributes:
            for attr in ["text", "aria-label", "title", "alt"]:
                if attr in element.attributes:
                    return element.attributes[attr]
        # Check children for text
        if hasattr(element, "children") and element.children:
            texts = []
            for child in element.children:
                if hasattr(child, "text") and child.text:
                    texts.append(child.text)
            if texts:
                return " ".join(texts)
        return None
    
    # Extract repository information
    extract_repositories(state.element_tree)
    
    # Clean up repository names (remove leading slashes)
    for repo in repositories:
        if repo["name"].startswith("/"):
            repo["name"] = repo["name"][1:]
    
    # Display extracted information
    if repositories:
        logger.info(f"Extracted information about {len(repositories)} trending repositories:")
        for i, repo in enumerate(repositories[:5], start=1):  # Show top 5
            logger.info(f"{i}. {repo.get('name', 'Unknown')}")
            if repo.get('description'):
                desc = repo['description']
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                logger.info(f"   Description: {desc}")
        
        # Save the extracted data to a JSON file
        with open("trending_repos.json", "w") as f:
            json.dump(
                {
                    "extraction_date": datetime.now().isoformat(),
                    "repositories": repositories[:10]  # Save top 10
                },
                f, 
                indent=2
            )
        logger.info("Saved extracted repository data to trending_repos.json")
    else:
        logger.info("No repository information could be extracted")
    
    logger.info("Visual information extraction complete")


if __name__ == "__main__":
    asyncio.run(main())
