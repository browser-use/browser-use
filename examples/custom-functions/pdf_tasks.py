import os
import asyncio
import logging
import aiohttp
import fitz  # PyMuPDF
# from pathlib import Path # This import was unused, so I've removed it.
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class ActionResult:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error


async def navigate_to_page(page, url):
    try:
        await page.goto(url, wait_until='load')
        # Consider using playwright's specific wait functions if possible,
        # e.g., page.wait_for_load_state('networkidle') or waiting for a specific element.
        # However, asyncio.sleep is non-blocking.
        await asyncio.sleep(2)
        return ActionResult(data="Page loaded successfully.")
    except Exception as e:
        # logging.error(f"Error loading page: {e}") # Original code had this commented
        return ActionResult(error=f"Page timeout or error while loading: {url} - {str(e)}")


async def collect_pdfs_from_frame(frame, pdf_links: set):
    try:
        # Ensure the frame is valid and attached before interacting
        if frame.is_detached():
            logging.warning(f"Frame is detached, skipping PDF collection.")
            return

        hrefs = await frame.eval_on_selector_all(
            "a[href$='.pdf']", 'els => els.map(e => e.href)'
        )
        srcs = await frame.eval_on_selector_all(
            "iframe[src$='.pdf'], embed[src$='.pdf']", 'els => els.map(e => e.src)'
        )
        
        # Ensure URLs are absolute
        page_url = frame.page.url
        def to_absolute_url(link):
            if link.startswith(('http://', 'https://')):
                return link
            try:
                # Use a more robust way to make URL absolute if needed, e.g. urllib.parse.urljoin
                return frame.page.url_join(link, page_url) # playwright does not have page.url_join directly
                                                        # a simple way is to use urllib.parse.urljoin
                from urllib.parse import urljoin
                return urljoin(page_url, link)
            except Exception: # Fallback for malformed relative URLs or if base_url is tricky
                return link

        pdf_links.update(map(to_absolute_url, hrefs + srcs))

    except Exception as e:
        # More specific error logging can be helpful here.
        # Errors like "Target closed" can happen if the frame navigates away or closes.
        logging.error(f"Error collecting PDFs from frame ({frame.url if not frame.is_detached() else 'detached'}): {e}")


async def collect_all_pdfs(page) -> set:
    pdf_links = set()
    try:
        # Process main frame first
        await collect_pdfs_from_frame(page.main_frame, pdf_links)
        
        # Process child frames
        frames = page.frames
        for frame in frames:
            if frame != page.main_frame: # Avoid processing main frame twice
                await collect_pdfs_from_frame(frame, pdf_links)
                
    except Exception as e:
        logging.error(f"Error collecting PDFs: {e}")
    return pdf_links


async def handle_more_buttons(page, pdf_links: set):
    try:
        # Using a more specific selector might be better if possible
        buttons = await page.query_selector_all("button, a[role='button']") # Include <a> tags styled as buttons
        
        clicked_a_button = False
        for btn_handle in buttons:
            try:
                is_visible = await btn_handle.is_visible()
                if not is_visible:
                    continue

                text_content = (await btn_handle.inner_text() or "").lower()
                aria_label = (await btn_handle.get_attribute("aria-label") or "").lower()
                
                if 'more' in text_content or 'next' in text_content or \
                   'more' in aria_label or 'next' in aria_label:
                    logging.info(f"Found potential 'more' or 'next' button: {text_content or aria_label}")
                    await btn_handle.click(timeout=5000) # Add timeout to click
                    await page.wait_for_load_state('networkidle', timeout=5000) # Wait for potential content load
                    # await asyncio.sleep(2.5) # Increased sleep slightly, or use better wait
                    
                    new_links = await collect_all_pdfs(page)
                    if new_links.difference(pdf_links): # Only update and log if new links were found
                        logging.info(f"Found {len(new_links.difference(pdf_links))} new PDF links after clicking button.")
                        pdf_links.update(new_links)
                        clicked_a_button = True # Flag that we might want to re-scan for buttons
                    else:
                        logging.info("No new PDF links found after clicking button.")
            except Exception as e:
                logging.warning(f"Error interacting with a button: {e}")
                # Continue to the next button
        
        # Optional: If a button was clicked that loaded new content, re-run to find new 'more' buttons
        # This could lead to deep recursion or long loops, use with caution or add depth limit
        # if clicked_a_button:
        #     logging.info("Re-scanning for more buttons after content update.")
        #     await handle_more_buttons(page, pdf_links)

    except Exception as e:
        logging.warning(f"Error in handle_more_buttons: {e}")


async def fetch_pdf_content(session, url):
    # Added retries and timeout for robustness
    for attempt in range(3): # Try up to 3 times
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response: # 60s timeout
                response.raise_for_status()  # Raises HTTPError for bad responses (4xx or 5xx)
                return await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logging.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt == 2: # Last attempt
                raise
            await asyncio.sleep(2 ** attempt) # Exponential backoff
    return None # Should not be reached if raise works


# Helper synchronous function for writing file content
def _write_file_sync(filepath: str, content: bytes):
    with open(filepath, 'wb') as f:
        f.write(content)

async def _download_single_pdf(session, pdf_url: str, output_dir: str):
    try:
        content = await fetch_pdf_content(session, pdf_url)
        if content is None:
            return None
            
        # Sanitize filename (simple version, might need more robust sanitization)
        base_filename = os.path.basename(pdf_url.split('?')[0])
        safe_filename = "".join(c if c.isalnum() or c in ('.', '_', '-') else '_' for c in base_filename)
        if not safe_filename.lower().endswith(".pdf"): # Ensure .pdf extension
            safe_filename += ".pdf"

        filename = os.path.join(output_dir, safe_filename)
        
        await asyncio.to_thread(_write_file_sync, filename, content)
        logging.info(f"Downloaded: {filename}")
        return filename
    except Exception as e:
        logging.error(f"Failed to download {pdf_url}: {e}")
        return None

async def download_pdfs(pdf_links: set, output_dir: str):
    downloaded_files = []
    # Ensure output directory exists (synchronous is fine for one-off setup)
    # await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)
    # os.makedirs is generally fast enough not to require to_thread unless on slow FS/high concurrency scenarios
    os.makedirs(output_dir, exist_ok=True)

    # Use aiohttp.ClientSession with a connector to limit concurrent connections if needed
    # For example, limit to 10 concurrent connections:
    # conn = aiohttp.TCPConnector(limit_per_host=10, limit=50) # Limit per host and total
    # async with aiohttp.ClientSession(connector=conn) as session:
    async with aiohttp.ClientSession() as session:
        tasks = []
        for pdf_url in pdf_links:
            if not pdf_url or not pdf_url.startswith(('http://', 'https://')):
                logging.warning(f"Skipping invalid or non-HTTP(S) URL: {pdf_url}")
                continue
            tasks.append(_download_single_pdf(session, pdf_url, output_dir))
        
        results = await asyncio.gather(*tasks)
        for result in results:
            if result:
                downloaded_files.append(result)
    return downloaded_files


# Helper synchronous function for PDF text extraction
def _extract_text_sync(file_path: str):
    try:
        with fitz.open(file_path) as doc:
            text = ""
            for i in range(doc.page_count):
                page = doc.load_page(i)
                text += page.get_text()
            return text
    except Exception as e: # Catch specific fitz/PDF errors if known
        logging.error(f"Fitz error processing {file_path}: {e}")
        # Consider re-raising or returning a specific error marker
        raise # Re-raise to be caught by the async wrapper

async def _extract_single_pdf_text(file_path: str):
    try:
        text = await asyncio.to_thread(_extract_text_sync, file_path)
        logging.info(f"Text extracted from: {file_path}")
        return file_path, text
    except Exception as e:
        # Error already logged by _extract_text_sync if it was a fitz error,
        # but this catches errors from asyncio.to_thread or if _extract_text_sync doesn't log.
        logging.error(f"Text extraction task failed for {file_path}: {e}")
        return file_path, None # Return None for text if extraction fails

async def extract_text_from_pdfs(downloaded_files: list):
    text_data = {}
    tasks = []
    for file_path in downloaded_files:
        tasks.append(_extract_single_pdf_text(file_path))
    
    results = await asyncio.gather(*tasks)
    for file_path, text in results:
        if text is not None: # Only add if text extraction was successful
            text_data[file_path] = text
            
    return text_data


async def run_pdf_scraper(target_url: str, download_dir: str = "pdfs_output"):
    # Initialize Playwright outside the main try block to ensure browser is closed if setup fails
    pw_instance = None
    browser = None
    try:
        pw_instance = await async_playwright().start()
        # Consider browser launch options: e.g., proxy, user_agent
        browser = await pw_instance.chromium.launch(headless=True) # Changed from pw.chromium
        page = await browser.new_page()
        # Optional: Set a default timeout for operations
        page.set_default_timeout(30000) # 30 seconds

        result = await navigate_to_page(page, target_url)
        if result.error:
            logging.error(f"Navigation failed: {result.error}")
            # No need to close browser here, finally block will handle it.
            return result # ActionResult with error

        pdf_links = await collect_all_pdfs(page)
        logging.info(f"Initially found {len(pdf_links)} PDF links.")

        # Handle dynamic content loading (e.g., "more" buttons)
        # This might discover more PDFs, so pdf_links set is passed to be updated.
        await handle_more_buttons(page, pdf_links)

        logging.info(f"Total unique PDFs found after handling dynamic content: {len(pdf_links)}")
        
        if not pdf_links:
            logging.info("No PDF links found.")
            return ActionResult(data={}) # Return empty data if no PDFs

        downloaded_files = await download_pdfs(pdf_links, download_dir)
        if not downloaded_files:
            logging.info("No PDFs were successfully downloaded.")
            # Decide if this is an error or just empty data
            return ActionResult(data={}, error="No PDFs could be downloaded.")

        text_data = await extract_text_from_pdfs(downloaded_files)

        return ActionResult(data=text_data)

    except Exception as e:
        logging.error(f"An error occurred in run_pdf_scraper: {e}", exc_info=True)
        return ActionResult(error=str(e))
    finally:
        if browser:
            await browser.close()
        if pw_instance:
            await pw_instance.stop()


async def main():
    # Example usage:
    # Replace with a URL that you know has PDFs and possibly "more" buttons
    # test_url = "https://www.example.com/research-papers" 
    # test_url = "https://www.africau.edu/images/default/sample.pdf" # Direct PDF link test
    test_url = "https://www.google.com/search?q=filetype%3Apdf+annual+report" # Test with a search results page
    
    logging.info(f"Starting PDF scraper for URL: {test_url}")
    result = await run_pdf_scraper(target_url=test_url, download_dir="downloaded_pdfs")

    if result.error:
        logging.error(f"Scraper finished with error: {result.error}")
    else:
        logging.info(f"Scraper finished successfully. Extracted text from {len(result.data)} PDFs.")
        # For demonstration, print snippet of extracted text:
        # for filepath, text_content in result.data.items():
        #     logging.info(f"--- Text from: {filepath} ---")
        #     logging.info(f"{text_content[:200]}...") # Print first 200 chars
        #     logging.info("--- End of Snippet ---")

if __name__ == "__main__":
    # To run the asyncio main function:
    asyncio.run(main())
