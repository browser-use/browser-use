import asyncio
import json
import os
import time
import logging

from browser_use.browser.browser import Browser, BrowserConfig

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_process_dom():
    logger.info("Starting test_process_dom function")
    browser = Browser(config=BrowserConfig(headless=True))
    logger.info("Browser created")
    
    async with await browser.new_context() as context:
        logger.info("Browser context created")
        page = await context.get_current_page()
        logger.info("Got current page")
        
        # await page.goto('https://kayak.com/flights')
        # await page.goto('https://google.com/flights')
        # await page.goto('https://immobilienscout24.de')
        # await page.goto('https://seleniumbase.io/w3schools/iframes')
        await page.goto('https://www.google.com/search?q=multion')
        logger.info(f"Navigated to {page.url}")

        time.sleep(3)
        logger.info("Waited for 3 seconds")

        with open('browser_use/dom/buildDomTree.js', 'r') as f:
            js_code = f.read()
        logger.info("Read JavaScript code from file")

        # Prepare the JavaScript code
        js_function = f"""
        (js_code => {{
            const buildDomTree = eval(js_code);
            return buildDomTree({{
                doHighlightElements: true,
                focusHighlightIndex: -1,
                viewportExpansion: 0,
                debugMode: false
            }});
        }})
        """

        start = time.time()
        dom_tree = await page.evaluate(js_function, js_code)
        end = time.time()
        logger.info(f"Evaluated JavaScript code in {end - start:.2f} seconds")

        # print(dom_tree)
        logger.info(f'Time: {end - start:.2f}s')

        # Print some basic information about the DOM tree
        logger.info(f"DOM tree type: {type(dom_tree)}")
        logger.info(f"Full DOM tree: {json.dumps(dom_tree, indent=2)}")
        
        if isinstance(dom_tree, dict):
            for key, value in dom_tree.items():
                logger.info(f"Key: {key}")
                logger.info(f"Value: {json.dumps(value, indent=2)}")
            
            if 'children' in dom_tree:
                logger.info(f"Children: {json.dumps(dom_tree['children'], indent=2)}")
            
            if 'map' in dom_tree:
                map_data = dom_tree['map']
                logger.info(f"Map data: {json.dumps(map_data, indent=2)}")
                
                for node_id, node in map_data.items():
                    logger.info(f"Node ID: {node_id}")
                    logger.info(f"Node data: {json.dumps(node, indent=2)}")
        
        else:
            logger.info(f"DOM tree content: {dom_tree}")

        # Use an absolute path for the output file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        output_file = os.path.join(current_dir, 'dom_output.json')
        logger.info(f"Attempting to write output file to: {output_file}")

        try:
            with open(output_file, 'w') as f:
                json.dump(dom_tree, f, indent=2)
            logger.info(f"Successfully wrote DOM tree to {output_file}")
        except Exception as e:
            logger.error(f"Failed to write output file. Error: {str(e)}")

        # Verify file existence
        if os.path.exists(output_file):
            logger.info(f"Output file exists at {output_file}")
            logger.info(f"File size: {os.path.getsize(output_file)} bytes")
        else:
            logger.error(f"Output file does not exist at {output_file}")

        # both of these work for immobilienscout24.de
        # await page.click('.sc-dcJsrY.ezjNCe')
        # await page.click(
        #     'div > div:nth-of-type(2) > div > div:nth-of-type(2) > div > div:nth-of-type(2) > div > div > div > button:nth-of-type(2)'
        # )

        # input('Press Enter to continue...')
        logger.info("Test completed successfully")

if __name__ == '__main__':
    logger.info("Starting main execution")
    asyncio.run(test_process_dom())
    logger.info("Main execution completed")
