import asyncio
import os
import time
import logging
import requests
from pathlib import Path
from urllib.parse import urljoin
from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr
from browser_use import ActionResult, Agent, Controller, BrowserConfig
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig
import fitz # PyMuPDF for PDF text extraction
from gemini_flash import GeminiFlash # Gemini-Flash Support
from langchain_google_genai import ChatGoogleGenerativeAI

# Set up logging configuration for better debugging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
BEARER_TOKEN = os.getenv('BEARER_TOKEN')

if not api_key:
    raise ValueError('GEMINI_API_KEY is not set')
if not BEARER_TOKEN:
    raise ValueError('BEARER_TOKEN is not set')

# Initialize Gemini and Browser
llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))

browser = Browser(
    config=BrowserConfig(
        new_context_config=BrowserContextConfig(viewport_expansion=0)
    )
)

controller = Controller(exclude_actions=['search_google'])


# Define the Pydantic Models for Data Validation
class Person(BaseModel):
    name: str
    email: str | None = None


class PersonList(BaseModel):
    people: list[Person]


# Define the Scraping and PDF Handling Function
async def scrape_and_read_pdfs_with_gemini_flash(
    browser: Agent,
    url: str,
    output_dir: str = "downloads/pdfs",
    click_more: bool = True,
    timeout_ms: int = 10000,
    extract_text: bool = True,
    summarize: bool = False,
    max_summary_sentences: int = 5
) -> ActionResult:
    """
    Scrapes PDFs from the provided URL, downloads them, and extracts or summarizes the text.
    Integrates Gemini-Flash for advanced interactions with the extracted data.

    :param browser: The browser instance for interaction
    :param url: URL of the webpage to scrape PDFs from
    :param output_dir: Directory to store the downloaded PDFs
    :param click_more: Whether to click "More" or "Next" buttons to reveal hidden PDFs
    :param timeout_ms: Timeout duration for actions in milliseconds
    :param extract_text: Whether to extract text from the PDFs
    :param summarize: Whether to summarize the extracted text
    :param max_summary_sentences: Maximum number of sentences for the summary
    :return: ActionResult containing success or failure details
    """
    context = browser.context
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    try:
        page.goto(url, wait_until="load")
        time.sleep(2)  # Allow the page to load completely
    except Exception as e:
        logging.error(f"Error loading page: {e}")
        return ActionResult(error=f"Page timeout while loading: {url}")

    pdf_links = set()

    # Helper function to collect all PDF links on the page
    def collect_pdfs(frame):
        try:
            hrefs = frame.eval_on_selector_all("a[href$='.pdf']", "els => els.map(e => e.href)")
            srcs = frame.eval_on_selector_all("iframe[src$='.pdf'], embed[src$='.pdf']", "els => els.map(e => e.src)")
            pdf_links.update(hrefs + srcs)
        except Exception as e:
            logging.error(f"Error while collecting PDFs: {e}")

    # Function to handle "Next" or "More" button clicks
    def try_click_more():
        if click_more:
            try:
                for el in page.query_selector_all("button, a"):
                    if "more" in el.inner_text().lower() or "next" in el.inner_text().lower():
                        el.click()
                        time.sleep(1)  # Wait for new content to load
                        collect_pdfs(page)
            except Exception as e:
                logging.warning(f"Error while clicking more buttons: {e}")

    collect_pdfs(page)
    try_click_more()

    # Remove duplicate PDF links
    pdf_links = set(pdf_links)

    if not pdf_links:
        return ActionResult(error="No PDFs found on the page.")

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    downloaded_files = []
    for pdf_url in pdf_links:
        try:
            pdf_url = urljoin(url, pdf_url)  # Resolve relative URLs
            file_name = os.path.join(output_dir, os.path.basename(pdf_url))
            if not os.path.exists(file_name):
                response = requests.get(pdf_url, stream=True, timeout=timeout_ms / 1000)
                if response.status_code == 200:
                    with open(file_name, "wb") as f:
                        for chunk in response.iter_content(1024):
                            f.write(chunk)
                    downloaded_files.append(file_name)
                    logging.info(f"Downloaded: {file_name}")
                else:
                    logging.warning(f"Failed to download PDF: {pdf_url}")
        except Exception as e:
            logging.error(f"Error downloading {pdf_url}: {e}")

    text_data = {}
    if extract_text:
        # Extract text from the downloaded PDFs
        for file in downloaded_files:
            try:
                doc = fitz.open(file)
                text = ""
                for page_num in range(doc.page_count):
                    text += doc.load_page(page_num).get_text()
                text_data[file] = text
                logging.info(f"Extracted text from: {file}")
            except Exception as e:
                logging.error(f"Error extracting text from {file}: {e}")

        # Summarize the extracted text if required
        if summarize:
            from sumy.parsers.plaintext import PlaintextParser
            from sumy.nlp.tokenizers import Tokenizer
            from sumy.summarizers.lsa import LsaSummarizer

            summarized_data = {}
            for file, text in text_data.items():
                parser = PlaintextParser.from_string(text, Tokenizer())
                summarizer = LsaSummarizer()
                summary = summarizer(parser.document, sentences_count=max_summary_sentences)
                summarized_text = " ".join([str(sentence) for sentence in summary])
                summarized_data[file] = summarized_text
                logging.info(f"Summarized text for: {file}")

            text_data = summarized_data

        # Save extracted or summarized text into files
        for file, text in text_data.items():
            summary_file = file.replace(".pdf", ".txt")
            with open(summary_file, "w") as f:
                f.write(text)
            logging.info(f"Saved text from {file} to {summary_file}")

    # Integrate Gemini-Flash for advanced interaction
    gemini_flash = GeminiFlash(api_key=os.getenv('GEMINI_FLASH_API_KEY'))
    gemini_flash.interact_with_data(text_data)

    return ActionResult(success=True, data={"downloaded_files": downloaded_files, "extracted_texts": text_data})


# Function to execute the agent task
async def main():
    names = [
        'Ruedi Aebersold', 'Bernd Bodenmiller', 'Eugene Demler', 'Erich Fischer', 'Pietro Gambardella',
        'Matthias Huss', 'Reto Knutti', 'Maksym Kovalenko', 'Antonio Lanzavecchia', 'Maria Lukatskaya'
    ]

    task = 'Use scrape_and_read_pdfs_with_gemini_flash with "find PDFs related to the following names" for each name and extract text from PDFs.'
    task += '\n' + '\n'.join(names)

    agent = Agent(task=task, llm=llm, controller=controller)

    history = await agent.run()

    result = history.final_result()
    if result:
        parsed: PersonList = PersonList.model_validate_json(result)
        for person in parsed.people:
            print(f'{person.name} - {person.email}')
    else:
        print('No result')


if __name__ == '__main__':
    asyncio.run(main())
