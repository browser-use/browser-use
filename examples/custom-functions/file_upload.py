import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from lmnr import Laminar

try:
	Laminar.initialize(project_api_key=os.getenv('LMNR_PROJECT_API_KEY'))
except Exception:
	pass

from browser_use import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.llm import ChatOpenAI

logger = logging.getLogger(__name__)

controller = Controller()


@controller.action('Upload file to interactive element with file path')
async def upload_file(index: int, path: str, browser_session: BrowserSession, available_file_paths: list[str]):
	if path not in available_file_paths:
		return ActionResult(error=f'File path {path} is not available')

	if not os.path.exists(path):
		return ActionResult(error=f'File {path} does not exist')

	file_upload_dom_el = await browser_session.find_file_upload_element_by_index(index, max_height=3, max_descendant_depth=3)

	if file_upload_dom_el is None:
		msg = f'No file upload element found at index {index}'
		logger.info(msg)
		return ActionResult(error=msg)

	file_upload_el = await browser_session.get_locate_element(file_upload_dom_el)

	if file_upload_el is None:
		msg = f'No file upload element found at index {index}'
		logger.info(msg)
		return ActionResult(error=msg)

	try:
		await file_upload_el.set_input_files(path)
		msg = f'Successfully uploaded file to index {index}'
		logger.info(msg)
		return ActionResult(extracted_content=msg, include_in_memory=True)
	except Exception as e:
		msg = f'Failed to upload file to index {index}: {str(e)}'
		logger.info(msg)
		return ActionResult(error=msg)


def create_file(file_type: str = 'txt'):
	with open(f'tmp.{file_type}', 'w') as f:
		f.write('test')
	file_path = Path.cwd() / f'tmp.{file_type}'
	logger.info(f'Created file: {file_path}')
	return str(file_path)


async def main():
	task = 'Go to https://kzmpmkh2zfk1ojnpxfn1.lite.vusercontent.net/ and - read the file content and upload them to fields'
	task = 'Go to https://www.freepdfconvert.com/, upload the file tmp.pdf into the field choose a file - dont click the fileupload button'
	available_file_paths = [create_file('txt'), create_file('pdf'), create_file('csv')]

	model = ChatOpenAI(model='gpt-4.1-mini')
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		available_file_paths=available_file_paths,
	)

	await agent.run()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
