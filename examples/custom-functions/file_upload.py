"""
Example of implementing file upload functionality.

This shows how to upload files to file input elements on web pages.
"""

import asyncio
import logging
import os
import sys

import aiofiles

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import ChatOpenAI
from browser_use.agent.service import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.events import UploadFileEvent

logger = logging.getLogger(__name__)

# Initialize controller
controller = Controller()


@controller.action('Upload file to interactive element with file path')
async def upload_file(index: int, path: str, browser_session: BrowserSession, available_file_paths: list[str]):
	if path not in available_file_paths:
		return ActionResult(error=f'File path {path} is not available')

	if not os.path.exists(path):
		return ActionResult(error=f'File {path} does not exist')

	try:
		# Get the DOM element by index
		dom_element = await browser_session.get_dom_element_by_index(index)

		if dom_element is None:
			msg = f'No element found at index {index}'
			logger.info(msg)
			return ActionResult(error=msg)

		# Check if it's a file input element
		if dom_element.tag_name.lower() != 'input' or dom_element.attributes.get('type') != 'file':
			msg = f'Element at index {index} is not a file input element'
			logger.info(msg)
			return ActionResult(error=msg)

		# Dispatch the upload file event
		event = browser_session.event_bus.dispatch(UploadFileEvent(node=dom_element, file_path=path))
		await event

		msg = f'Successfully uploaded file to index {index}'
		logger.info(msg)
		return ActionResult(extracted_content=msg, include_in_memory=True)

	except Exception as e:
		msg = f'Failed to upload file to index {index}: {str(e)}'
		logger.info(msg)
		return ActionResult(error=msg)


async def main():
	"""Main function to run the example"""
	browser_session = BrowserSession()
	await browser_session.start()
	llm = ChatOpenAI(model='gpt-4.1-mini')

	# List of file paths the agent is allowed to upload
	# In a real scenario, you'd want to be very careful about what files
	# the agent can access and upload
	available_file_paths = [
		'/tmp/test_document.pdf',
		'/tmp/test_image.jpg',
	]

	# Create test files if they don't exist
	for file_path in available_file_paths:
		if not os.path.exists(file_path):
			async with aiofiles.open(file_path, 'w') as f:
				await f.write('Test file content for upload example')

	# Create the agent with file upload capability
	agent = Agent(
		task="""
            Go to https://www.w3schools.com/howto/howto_html_file_upload_button.asp and try to upload one of the available test files.
        """,
		llm=llm,
		browser_session=browser_session,
		controller=controller,
		# Pass the available file paths to the controller context
		custom_context={'available_file_paths': available_file_paths},
	)

	# Run the agent
	await agent.run(max_steps=10)

	# Cleanup
	await browser_session.kill()

	# Clean up test files
	for file_path in available_file_paths:
		if os.path.exists(file_path):
			os.remove(file_path)


if __name__ == '__main__':
	asyncio.run(main())
