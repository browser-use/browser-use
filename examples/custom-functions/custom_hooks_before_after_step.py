"""
Description: These Python modules are designed to capture detailed
browser usage datafor analysis, with both server and client
components working together to record and store the information.

Author: Carlos A. Planchón
https://github.com/carlosplanchon/

Adapt this code to your needs.

Feedback is appreciated!
"""

#####################
#                   #
#   --- UTILS ---   #
#                   #
#####################

import base64


def b64_to_png(b64_string: str, output_file):
	"""
	Convert a Base64-encoded string to a PNG file.

	:param b64_string: A string containing Base64-encoded data
	:param output_file: The path to the output PNG file
	"""
	with open(output_file, 'wb') as f:
		f.write(base64.b64decode(b64_string))


###################################################################
#                                                                 #
#   --- FASTAPI API TO RECORD AND SAVE Browser-Use ACTIVITY ---   #
#                                                                 #
###################################################################

# Save to api.py and run with `python api.py`

# ! pip install uvicorn
# ! pip install fastapi
# ! pip install prettyprinter

import json
from pathlib import Path

import prettyprinter  # type: ignore
from fastapi import FastAPI, Request

prettyprinter.install_extras()

app = FastAPI()


@app.post('/post_agent_history_step')
async def post_agent_history_step(request: Request):
	data = await request.json()
	prettyprinter.cpprint(data)

	# Ensure the "recordings" folder exists using pathlib
	recordings_folder = Path('recordings')
	recordings_folder.mkdir(exist_ok=True)

	# Determine the next file number by examining existing .json files
	existing_numbers = []
	for item in recordings_folder.iterdir():
		if item.is_file() and item.suffix == '.json':
			try:
				file_num = int(item.stem)
				existing_numbers.append(file_num)
			except ValueError:
				# In case the file name isn't just a number
				...

	if existing_numbers:
		next_number = max(existing_numbers) + 1
	else:
		next_number = 1

	# Construct the file path
	file_path = recordings_folder / f'{next_number}.json'

	# Save the JSON data to the file
	with file_path.open('w') as f:
		json.dump(data, f, indent=2)

	return {'status': 'ok', 'message': f'Saved to {file_path}'}


if __name__ == '__main__':
	import uvicorn

	uvicorn.run(app, host='0.0.0.0', port=9000)


##############################################################
#                                                            #
#   --- CLIENT TO RECORD AND SAVE Browser-Use ACTIVITY ---   #
#                                                            #
##############################################################

"""
pyobjtojson:

A Python library to safely and recursively serialize any Python object
(including Pydantic models and dataclasses) into JSON-ready structures,
gracefully handling circular references.
"""

# ! pip install -U pyobjtojson
# ! pip install -U prettyprinter

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import requests
from pyobjtojson import obj_to_json  # type: ignore

from browser_use import Agent
from browser_use.llm import ChatOpenAI

# import prettyprinter
# prettyprinter.install_extras()


def send_agent_history_step(data):
	url = 'http://127.0.0.1:9000/post_agent_history_step'
	response = requests.post(url, json=data)
	return response.json()


async def record_activity(agent_obj):
	website_html = None
	website_screenshot = None
	urls_json_last_elem = None
	model_thoughts_last_elem = None
	model_outputs_json_last_elem = None
	model_actions_json_last_elem = None
	extracted_content_json_last_elem = None

	print('--- ON_STEP_START HOOK ---')
	website_html = await agent_obj.browser_context.get_page_html()
	website_screenshot = await agent_obj.browser_context.take_screenshot()

	print('--> History:')
	# Assert agent has state to satisfy type checker
	assert hasattr(agent_obj, 'state'), 'Agent must have state attribute'
	history = agent_obj.state.history

	model_thoughts = obj_to_json(obj=history.model_thoughts(), check_circular=False)

	# print("--- MODEL THOUGHTS ---")
	if len(model_thoughts) > 0:
		model_thoughts_last_elem = model_thoughts[-1]
		# prettyprinter.cpprint(model_thoughts_last_elem)

	# print("--- MODEL OUTPUT ACTION ---")
	model_outputs = agent_obj.state.history.model_outputs()
	model_outputs_json = obj_to_json(obj=model_outputs, check_circular=False)

	if len(model_outputs_json) > 0:
		model_outputs_json_last_elem = model_outputs_json[-1]
		# prettyprinter.cpprint(model_outputs_json_last_elem)

	# print("--- MODEL INTERACTED ELEM ---")
	model_actions = agent_obj.state.history.model_actions()
	model_actions_json = obj_to_json(obj=model_actions, check_circular=False)

	if len(model_actions_json) > 0:
		model_actions_json_last_elem = model_actions_json[-1]
		# prettyprinter.cpprint(model_actions_json_last_elem)

	# print("--- EXTRACTED CONTENT ---")
	extracted_content = agent_obj.state.history.extracted_content()
	extracted_content_json = obj_to_json(obj=extracted_content, check_circular=False)
	if len(extracted_content_json) > 0:
		extracted_content_json_last_elem = extracted_content_json[-1]
		# prettyprinter.cpprint(extracted_content_json_last_elem)

	# print("--- URLS ---")
	urls = agent_obj.state.history.urls()
	# prettyprinter.cpprint(urls)
	urls_json = obj_to_json(obj=urls, check_circular=False)

	if len(urls_json) > 0:
		urls_json_last_elem = urls_json[-1]
		# prettyprinter.cpprint(urls_json_last_elem)

	model_step_summary = {
		'website_html': website_html,
		'website_screenshot': website_screenshot,
		'url': urls_json_last_elem,
		'model_thoughts': model_thoughts_last_elem,
		'model_outputs': model_outputs_json_last_elem,
		'model_actions': model_actions_json_last_elem,
		'extracted_content': extracted_content_json_last_elem,
	}

	print('--- MODEL STEP SUMMARY ---')
	# prettyprinter.cpprint(model_step_summary)

	send_agent_history_step(data=model_step_summary)

	# response = send_agent_history_step(data=history)
	# print(response)

	# print("--> Website HTML:")
	# print(website_html[:200])
	# print("--> Website Screenshot:")
	# print(website_screenshot[:200])


agent = Agent(
	task='Compare the price of gpt-4.1 and DeepSeek-V3',
	llm=ChatOpenAI(model='gpt-4.1'),
)


async def run_agent():
	try:
		await agent.run(on_step_start=record_activity, max_steps=30)
	except Exception as e:
		print(e)


asyncio.run(run_agent())
