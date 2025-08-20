"""
Goal: Searches for job listings, evaluates relevance based on a CV, and applies

@dev You need to add OPENAI_API_KEY to your environment variables.
Also you have to install PyPDF2 to read pdf files: pip install PyPDF2
"""

import asyncio
import csv
import logging
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel
from PyPDF2 import PdfReader  # type: ignore

from browser_use import ActionResult, Agent, ChatOpenAI, Controller
from browser_use.browser import BrowserProfile, BrowserSession

required_env_vars = ['AZURE_OPENAI_KEY', 'AZURE_OPENAI_ENDPOINT']
for var in required_env_vars:
	if not os.getenv(var):
		raise ValueError(f'{var} is not set. Please add it to your environment variables.')

logger = logging.getLogger(__name__)
# full screen mode
controller = Controller()

# NOTE: This is the path to your cv file
# create a dummy cv
CV = Path.cwd() / 'dummy_cv.pdf'
with open(CV, 'w') as f:
	f.write('Hi I am a machine learning engineer with 3 years of experience in the field')

logger.info(f'Using dummy cv at {CV}')


class Job(BaseModel):
	title: str
	link: str
	company: str
	fit_score: float
	location: str | None = None
	salary: str | None = None


@controller.action('Save jobs to file - with a score how well it fits to my profile', param_model=Job)
def save_jobs(job: Job):
	with open('jobs.csv', 'a', newline='') as f:
		writer = csv.writer(f)
		writer.writerow([job.title, job.company, job.link, job.salary, job.location])

	return 'Saved job to file'


@controller.action('Read jobs from file')
def read_jobs():
	with open('jobs.csv') as f:
		return f.read()


@controller.action('Read my cv for context to fill forms')
def read_cv():
	pdf = PdfReader(CV)
	text = ''
	for page in pdf.pages:
		text += page.extract_text() or ''
	logger.info(f'Read cv with {len(text)} characters')
	return ActionResult(extracted_content=text, include_in_memory=True)


@controller.action(
	'Upload cv to element - call this function to upload if element is not found, try with different index of the same upload element',
)
async def upload_cv(index: int, browser_session: BrowserSession):
	path = str(CV.absolute())

	# Get the element by index
	dom_element = await browser_session.get_element_by_index(index)

	if dom_element is None:
		logger.info(f'No element found at index {index}')
		return ActionResult(error=f'No element found at index {index}')

	# Check if it's a file input element
	if not browser_session.is_file_input(dom_element):
		logger.info(f'Element at index {index} is not a file upload element')
		return ActionResult(error=f'Element at index {index} is not a file upload element')

	try:
		# Dispatch upload file event with the file input element
		from browser_use.browser.events import UploadFileEvent

		event = browser_session.event_bus.dispatch(UploadFileEvent(node=dom_element, file_path=path))
		await event
		await event.event_result(raise_if_any=True, raise_if_none=False)
		msg = f'Successfully uploaded file "{path}" to index {index}'
		logger.info(msg)
		return ActionResult(extracted_content=msg)
	except Exception as e:
		logger.debug(f'Error in upload: {str(e)}')
		return ActionResult(error=f'Failed to upload file to index {index}')


browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		disable_security=True,
		user_data_dir='~/.config/browseruse/profiles/default',
	)
)


async def main():
	# ground_task = (
	# 	'You are a professional job finder. '
	# 	'1. Read my cv with read_cv'
	# 	'2. Read the saved jobs file '
	# 	'3. start applying to the first link of Amazon '
	# 	'You can navigate through pages e.g. by scrolling '
	# 	'Make sure to be on the english version of the page'
	# )
	ground_task = (
		'You are a professional job finder. '
		'1. Read my cv with read_cv'
		'find ml internships in and save them to a file'
		'search at company:'
	)
	tasks = [
		ground_task + '\n' + 'Google',
		# ground_task + '\n' + 'Amazon',
		# ground_task + '\n' + 'Apple',
		# ground_task + '\n' + 'Microsoft',
		# ground_task
		# + '\n'
		# + 'go to https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Taiwan%2C-Remote/Fulfillment-Analyst---New-College-Graduate-2025_JR1988949/apply/autofillWithResume?workerSubType=0c40f6bd1d8f10adf6dae42e46d44a17&workerSubType=ab40a98049581037a3ada55b087049b7 NVIDIA',
		# ground_task + '\n' + 'Meta',
	]
	model = ChatOpenAI(model='gpt-4.1-mini')

	agents = []
	for task in tasks:
		agent = Agent(task=task, llm=model, controller=controller, browser_session=browser_session)
		agents.append(agent)

	await asyncio.gather(*[agent.run() for agent in agents])


if __name__ == '__main__':
	asyncio.run(main())
