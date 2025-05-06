import os
import asyncio
import logging
import aiohttp
import fitz  # PyMuPDF
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class ActionResult:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error


async def navigate_to_page(page, url):
    try:
        await page.goto(url, wait_until='load')
        await asyncio.sleep(2)
        return ActionResult(data="Page loaded successfully.")
    except Exception as e:
        logging.error(f"Error loading page: {e}")
        return ActionResult(error=f"Page timeout while loading: {url}")


async def collect_pdfs_from_frame(frame, pdf_links: set):
    try:
        hrefs = await frame.eval_on_selector_all(
            "a[href$='.pdf']", 'els => els.map(e => e.href)'
        )
        srcs = await frame.eval_on_selector_all(
            "iframe[src$='.pdf'], embed[src$='.pdf']", 'els => els.map(e => e.src)'
        )
        pdf_links.update(hrefs + srcs)
    except Exception as e:
        logging.error(f"Error collecting PDFs from frame: {e}")


async def collect_all_pdfs(page) -> set:
    pdf_links = set()
    try:
        frames = page.frames
        for frame in frames:
            await collect_pdfs_from_frame(frame, pdf_links)
        await collect_pdfs_from_frame(page.main_frame, pdf_links)
    except Exception as e:
        logging.error(f"Error collecting PDFs: {e}")
    return pdf_links


async def handle_more_buttons(page, pdf_links):
    try:
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            text = (await btn.inner_text()).lower()
            if 'more' in text or 'next' in text:
                await btn.click()
                await asyncio.sleep(1.5)
                new_links = await collect_all_pdfs(page)
                pdf_links.update(new_links)
    except Exception as e:
        logging.warning(f"Error clicking 'more' buttons: {e}")


async def fetch_pdf(session, url):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.read()


async def download_pdfs(pdf_links, output_dir):
    downloaded_files = []
    os.makedirs(output_dir, exist_ok=True)
    async with aiohttp.ClientSession() as session:
        for pdf_url in pdf_links:
            try:
                content = await fetch_pdf(session, pdf_url)
                filename = os.path.join(output_dir, os.path.basename(pdf_url.split('?')[0]))
                with open(filename, 'wb') as f:
                    f.write(content)
                downloaded_files.append(filename)
                logging.info(f"Downloaded: {filename}")
            except Exception as e:
                logging.error(f"Failed to download {pdf_url}: {e}")
    return downloaded_files


async def extract_text_from_pdfs(downloaded_files):
    text_data = {}
    for file_path in downloaded_files:
        try:
            with fitz.open(file_path) as doc:
                text = ''.join([doc.load_page(i).get_text() for i in range(doc.page_count)])
            text_data[file_path] = text
            logging.info(f"Text extracted from: {file_path}")
        except Exception as e:
            logging.error(f"Text extraction failed for {file_path}: {e}")
    return text_data


async def run_pdf_scraper(target_url: str, download_dir: str = "pdfs"):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        result = await navigate_to_page(page, target_url)
        if result.error:
            await browser.close()
            return result

        pdf_links = await collect_all_pdfs(page)
        await handle_more_buttons(page, pdf_links)

        logging.info(f"Total unique PDFs found: {len(pdf_links)}")
        downloaded_files = await download_pdfs(pdf_links, download_dir)
        text_data = await extract_text_from_pdfs(downloaded_files)

        await browser.close()
        return ActionResult(data=text_data)
