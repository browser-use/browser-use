#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["browser-use", "mistralai"]
# ///

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging

from langchain_openai import ChatOpenAI
from mistralai import Mistral  # type: ignore
from pydantic import BaseModel, Field

from browser_use import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser.context import BrowserContext

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')

if not os.getenv('MISTRAL_API_KEY'):
	raise ValueError('MISTRAL_API_KEY is not set. Please add it to your environment variables.')

logger = logging.getLogger(__name__)

controller = Controller()


class PdfExtractParams(BaseModel):
	url: str = Field(description='URL to a PDF document')


@controller.registry.action(
	'Extract PDF Text',
	param_model=PdfExtractParams,
)
def extract_mistral_ocr(params: PdfExtractParams, browser: BrowserContext) -> ActionResult:
	"""
	Process a PDF URL using Mistral OCR API and return the OCR response.

	Args:
	    url: URL to a PDF document

	Returns:
	    OCR response object from Mistral API
	"""
	api_key = os.getenv('MISTRAL_API_KEY')
	client = Mistral(api_key=api_key)

	response = client.ocr.process(
		model='mistral-ocr-latest',
		document={
			'type': 'document_url',
			'document_url': params.url,
		},
		include_image_base64=False,
	)

	markdown = '\n\n'.join(f'### Page {i + 1}\n{response.pages[i].markdown}' for i in range(len(response.pages)))
	return ActionResult(
		extracted_content=markdown,
		include_in_memory=False,  ## PDF content can be very large, so we don't include it in memory
	)


async def main():
	agent = Agent(
		task="""
        Objective: Navigate to the following URL, extract its contents using the Extract PDF Text action, and explain its historical significance.

        URL: https://docs.house.gov/meetings/GO/GO00/20220929/115171/HHRG-117-GO00-20220929-SD010.pdf
        """,
		llm=ChatOpenAI(model='gpt-4o'),
		controller=controller,
	)
	result = await agent.run()
	logger.info(result)


if __name__ == '__main__':
	asyncio.run(main())
