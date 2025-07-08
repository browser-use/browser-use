# ==============================================================================================================
# This is the LLM as a judge evaluation system from the OSU-NLP Group paper
# Any adaptiations made should be explicitly stated here:
# Adaptations:
# We are using our own wrapper for the OpenAI API
# This means we changed model.generate to model.invoke. The behavior of the model should be identical.
# Added a Online_Mind2Web_eval_with_retry wrapper with retry logic in case of API rate limiting or other issues.


# @article{xue2025illusionprogressassessingcurrent,
#       title={An Illusion of Progress? Assessing the Current State of Web Agents},
#       author={Tianci Xue and Weijian Qi and Tianneng Shi and Chan Hee Song and Boyu Gou and Dawn Song and Huan Sun and Yu Su},
#       year={2025},
#       eprint={2504.01382},
#       archivePrefix={arXiv},
#       primaryClass={cs.AI},
#       url={https://arxiv.org/abs/2504.01382},
# }

# @inproceedings{deng2023mind2web,
#  author = {Deng, Xiang and Gu, Yu and Zheng, Boyuan and Chen, Shijie and Stevens, Sam and Wang, Boshi and Sun, Huan and Su, Yu},
#  booktitle = {Advances in Neural Information Processing Systems},
#  editor = {A. Oh and T. Naumann and A. Globerson and K. Saenko and M. Hardt and S. Levine},
#  pages = {28091--28114},
#  publisher = {Curran Associates, Inc.},
#  title = {Mind2Web: Towards a Generalist Agent for the Web},
#  url = {https://proceedings.neurips.cc/paper_files/paper/2023/file/5950bf290a1570ea401bf98882128160-Paper-Datasets_and_Benchmarks.pdf},
#  volume = {36},
#  year = {2023}
# }
# ==============================================================================================================
import asyncio
import base64
import io
import logging
import re

from PIL import Image

MAX_IMAGE = 5


logger = logging.getLogger(__name__)


def encode_image(image):
	"""Convert a PIL image to base64 string."""
	if image.mode == 'RGBA':
		image = image.convert('RGB')
	buffered = io.BytesIO()
	image.save(buffered, format='JPEG')
	return base64.b64encode(buffered.getvalue()).decode('utf-8')


async def identify_key_points(task, model):
	system_msg = """You are an expert tasked with analyzing a given task to identify the key points explicitly stated in the task description.

**Objective**: Carefully analyze the task description and extract the critical elements explicitly mentioned in the task for achieving its goal.

**Instructions**:
1. Read the task description carefully.
2. Identify and extract **key points** directly stated in the task description.
   - A **key point** is a critical element, condition, or step explicitly mentioned in the task description.
   - Do not infer or add any unstated elements.
   - Words such as "best," "highest," "cheapest," "latest," "most recent," "lowest," "closest," "highest-rated," "largest," and "newest" must go through the sort function(e.g., the key point should be "Filter by highest").

**Respond with**:
- **Key Points**: A numbered list of the explicit key points for completing this task, one per line, without explanations or additional details."""
	prompt = """Task: {task}"""
	text = prompt.format(task=task)
	messages = [
		{'role': 'system', 'content': system_msg},
		{
			'role': 'user',
			'content': [{'type': 'text', 'text': text}],
		},
	]
	response = await model.ainvoke(messages)
	return response.completion


async def judge_image(task, image_path, key_points, model):
	system_msg = """You are an expert evaluator tasked with determining whether an image contains information about the necessary steps to complete a task.

**Objective**: Analyze the provided image and decide if it shows essential steps or evidence required for completing the task. Use your reasoning to explain your decision before assigning a score.

**Instructions**:
1. Provide a detailed description of the image, including its contents, visible elements, text (if any), and any notable features.

2. Carefully examine the image and evaluate whether it contains necessary steps or evidence crucial to task completion:  
- Identify key points that could be relevant to task completion, such as actions, progress indicators, tool usage, applied filters, or step-by-step instructions.  
- Does the image show actions, progress indicators, or critical information directly related to completing the task?  
- Is this information indispensable for understanding or ensuring task success?
- If the image contains partial but relevant information, consider its usefulness rather than dismissing it outright.

3. Provide your response in the following format:  
- **Reasoning**: Explain your thought process and observations. Mention specific elements in the image that indicate necessary steps, evidence, or lack thereof.  
- **Score**: Assign a score based on the reasoning, using the following scale:  
    - **1**: The image does not contain any necessary steps or relevant information.  
    - **2**: The image contains minimal or ambiguous information, unlikely to be essential.  
    - **3**: The image includes some relevant steps or hints but lacks clarity or completeness.  
    - **4**: The image contains important steps or evidence that are highly relevant but not fully comprehensive.  
    - **5**: The image clearly displays necessary steps or evidence crucial for completing the task.

Respond with:  
1. **Reasoning**: [Your explanation]  
2. **Score**: [1-5]"""

	jpg_base64_str = encode_image(Image.open(image_path))

	prompt = """**Task**: {task}

**Key Points for Task Completion**: {key_points}

The snapshot of the web page is shown in the image."""
	text = prompt.format(task=task, key_points=key_points)

	messages = [
		{'role': 'system', 'content': system_msg},
		{
			'role': 'user',
			'content': [
				{'type': 'text', 'text': text},
				{
					'type': 'image_url',
					'image_url': {'url': f'data:image/jpeg;base64,{jpg_base64_str}', 'detail': 'high'},
				},
			],
		},
	]
	response = await model.ainvoke(messages)
	return response.completion


async def Online_Mind2Web_eval(task, last_actions, images_path, model, score_threshold):
	system_msg = """You are an expert in evaluating the performance of a web navigation agent. The agent is designed to help a human user navigate a website to complete a task. Given the user's task, the agent's action history, key points for task completion, some potentially important web pages in the agent's trajectory and their reasons, your goal is to determine whether the agent has completed the task and achieved all requirements.

Your response must strictly follow the following evaluation criteria!
*Important Evaluation Criteria*:
1: The filtered results must be displayed correctly. If filters were not properly applied (i.e., missing selection, missing confirmation, or no visible effect in results), the task is not considered successful.
2: You must carefully check whether these snapshots and action history meet these key points. Ensure that specific filter conditions, such as "best," "highest," "cheapest," "latest," "most recent," "lowest," "closest," "highest-rated," "largest," and "newest" are correctly applied using the filter function(e.g., sort function).
3: Certain key points or requirements should be applied by the filter. Otherwise, a search with all requirements as input will be deemed a failure since it cannot guarantee that all results meet the requirements!
4: If the task requires filtering by a specific range of money, years, or the number of beds and bathrooms, the applied filter must exactly match the given requirement. Any deviation results in failure. To ensure the task is successful, the applied filter must precisely match the specified range without being too broad or too narrow.
Examples of Failure Cases:
- If the requirement is less than $50, but the applied filter is less than $25, it is a failure.
- If the requirement is $1500-$2500, but the applied filter is $2000-$2500, it is a failure.
- If the requirement is $25-$200, but the applied filter is $0-$200, it is a failure.
- If the required years are 2004-2012, but the filter applied is 2001-2012, it is a failure.
- If the required years are before 2015, but the applied filter is 2000-2014, it is a failure.
- If the task requires exactly 2 beds, but the filter applied is 2+ beds, it is a failure.
5: Some tasks require a submission action or a display of results to be considered successful.
6: If the retrieved information is invalid or empty(e.g., No match was found), but the agent has correctly performed the required action, it should still be considered successful.
7: If the current page already displays all available items, then applying a filter is not necessary. As long as the agent selects items that meet the requirements (e.g., the cheapest or lowest price), the task is still considered successful.

*IMPORTANT*
Format your response into two lines as shown below:

Thoughts: <your thoughts and reasoning process based on double-checking each key points and the evaluation criteria>
Status: "success" or "failure"
"""
	prompt = """User Task: {task}

Key Points: {key_points}

Action History:
{last_actions}

The potentially important snapshots of the webpage in the agent's trajectory and their reasons:
{thoughts}"""

	key_points = await identify_key_points(task, model)
	key_points = key_points.replace('\n\n', '\n')

	try:
		key_points = key_points.split('**Key Points**:')[1]
		key_points = '\n'.join(line.lstrip() for line in key_points.splitlines())
	except IndexError:
		key_points = key_points.split('Key Points:')[-1]
		key_points = '\n'.join(line.lstrip() for line in key_points.splitlines())

	tasks = [judge_image(task, image_path, key_points, model) for image_path in images_path]
	image_responses = await asyncio.gather(*tasks)

	whole_content_img = []
	whole_thoughts = []
	record = []
	pattern = r'[1-5]'
	for response, image_path in zip(image_responses, images_path):
		try:
			score_text = response.split('Score')[1]
			thought = response.split('**Reasoning**:')[-1].strip().lstrip('\n').split('\n\n')[0].replace('\n', ' ')
			score = re.findall(pattern, score_text)[0]
			record.append({'Response': response, 'Score': int(score)})
		except Exception as e:
			logger.error(f'Error processing response: {type(e).__name__}: {e}')
			score = 0
			record.append({'Response': response, 'Score': 0})

		if int(score) >= score_threshold:
			jpg_base64_str = encode_image(Image.open(image_path))
			whole_content_img.append(
				{'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{jpg_base64_str}', 'detail': 'high'}}
			)
			if thought != '':
				whole_thoughts.append(thought)

	whole_content_img = whole_content_img[:MAX_IMAGE]
	whole_thoughts = whole_thoughts[:MAX_IMAGE]
	if len(whole_content_img) == 0:
		prompt = """User Task: {task}

Key Points: {key_points}

Action History:
{last_actions}"""
	text = prompt.format(
		task=task,
		last_actions='\n'.join(f'{i + 1}. {action}' for i, action in enumerate(last_actions)),
		key_points=key_points,
		thoughts='\n'.join(f'{i + 1}. {thought}' for i, thought in enumerate(whole_thoughts)),
	)

	messages = [
		{'role': 'system', 'content': system_msg},
		{'role': 'user', 'content': [{'type': 'text', 'text': text}] + whole_content_img},
	]
	return messages, text, system_msg, record, key_points


async def Online_Mind2Web_eval_with_retry(task, last_actions, images_path, model, score_threshold, max_retries=3):
	"""
	Wrapper for Online_Mind2Web_eval with retry logic.

	Args:
	    task: The task description
	    last_actions: list of actions taken
	    images_path: list of image paths
	    model: The model to use for evaluation
	    score_threshold: Score threshold for image filtering
	    max_retries: Maximum number of retry attempts

	Returns:
	    Tuple of (messages, text, system_msg, record, key_points) or None if all retries fail
	"""
	for attempt in range(max_retries):
		try:
			return await Online_Mind2Web_eval(task, last_actions, images_path, model, score_threshold)
		except Exception as e:
			if attempt == max_retries - 1:  # Last attempt
				logger.error(f'Failed to evaluate after {max_retries} attempts. Error: {type(e).__name__}: {str(e)}')
				raise
			logger.warning(f'Attempt {attempt + 1} failed. Retrying... Error: {type(e).__name__}: {str(e)}')
			await asyncio.sleep(2**attempt)  # Exponential backoff
