#!/usr/bin/env python3
"""
Action Scoring Script for Browser Automation Reinforcement Learning

This script evaluates the quality of actions taken during a browser automation task
by having an LLM score each action based on how well it contributes to task completion.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel

def load_session_data(json_path: str) -> Dict[str, Any]:
	"""Load the session data from JSON file"""
	with open(json_path, 'r', encoding='utf-8') as f:
		return json.load(f)

def create_scoring_prompt() -> str:
	"""Create the system prompt for action scoring"""
	return """You are an expert evaluator for browser automation tasks. Your job is to analyze the complete task execution and score each step based on its contribution to the overall success.

SCORING SCALE (-5 to +5):

HIGH SCORES (+4 to +5):
+5: Perfect action - Directly solves core problem or achieves main objective
+4: Excellent action - Major breakthrough or critical progress toward goal

MEDIUM SCORES (+1 to +3):
+3: Good action - Clear positive progress with meaningful advancement
+2: Useful action - Reasonable and correct step, standard navigation
+1: Minor help - Small progress, setup actions, or gathering needed information

NEUTRAL SCORE (0):
0: No impact - Action neither helps nor hinders (exploration, neutral attempts)

NEGATIVE SCORES (-1 to -5):
-1: Minor waste - Unnecessary but harmless action, slight inefficiency
-2: Inefficient action - Wastes time/resources, better option was available
-3: Wrong action - Clear mistake, moves away from goal
-4: Harmful action - Creates new problems or significant setback
-5: Critical failure - Severely hinders progress or causes major issues

EVALUATION CRITERIA:
1. **Direct contribution to task completion**: Does this action move closer to the goal?
2. **Efficiency and necessity**: Was this the right action at the right time?
3. **Impact on subsequent steps**: Did this enable or hinder future actions?
4. **Appropriateness for browser state**: Was this action suitable for the current page/situation?
5. **Alignment with task objective**: Does this action serve the overall purpose?

CONSISTENCY REQUIREMENTS:
- Apply the same scoring standards throughout the entire session
- Consider the full context when evaluating each step
- Be objective and focus on measurable progress toward the goal
- Justify each score with specific reasoning

IMPORTANT: You must respond with valid JSON format only. Do not include any markdown formatting, explanations, or additional text. Your response must be a single JSON object that can be parsed directly."""

def score_all_steps_batch(
	llm: BaseChatModel,
	steps_data: List[Dict[str, Any]],
	task_context: str,
	system_prompt: str
) -> List[Dict[str, Any]]:
	"""Score all steps in a single API call with reasoning first"""
	
	# Format all steps for evaluation
	all_steps_info = ""
	for step_data in steps_data:
		step_num = step_data['step_number']
		dom_state = step_data['dom_state']
		agent_response = step_data['agent_response']
		
		step_info = f"""
STEP {step_num}:
- URL: {dom_state['url']}
- Title: {dom_state.get('title', 'N/A')}
- Interactive Elements: {dom_state.get('interactive_elements_text', 'N/A')}

AGENT'S THINKING:
- Thinking: {agent_response.get('thinking', 'N/A')}
- Previous Goal: {agent_response.get('evaluation_previous_goal', 'N/A')}
- Memory: {agent_response.get('memory', 'N/A')}
- Next Goal: {agent_response.get('next_goal', 'N/A')}

ACTIONS: {json.dumps(agent_response.get('action', []), indent=2)}
"""
		all_steps_info += step_info + "\n" + "="*50 + "\n"
	
	# Create comprehensive prompt
	prompt = f"""
TASK: {task_context}

Analyze the complete execution sequence below. Follow this evaluation process:

1. **UNDERSTAND THE FULL JOURNEY**: Read through all steps to understand the complete task flow
2. **IDENTIFY KEY MOMENTS**: Find breakthrough moments, setbacks, and turning points
3. **APPLY SCORING STANDARDS**: Use the exact scoring scale provided in the system prompt
4. **JUSTIFY EACH SCORE**: Explain how each step contributed to or hindered task success

EVALUATION QUESTIONS FOR EACH STEP:
- Does this action directly advance the task goal?
- Is this the most efficient action for the current situation?
- Does this action enable or hinder subsequent steps?
- Is this action appropriate for the current browser state?
- How well does this action align with the overall task objective?

FOR THE SITUATION FIELD:
- Describe the page/form the agent was on
- Mention key elements visible (buttons, forms, links)
- Keep it concise and self-contained (1-2 sentences)
- Focus on what's relevant to understanding the action context

COMPLETE EXECUTION SEQUENCE:
{all_steps_info}

Provide your analysis in JSON format:

{{
  "task_analysis": "Your comprehensive analysis of the execution flow, key decisions, and turning points. Identify the overall strategy and critical moments.",
  "step_scores": [
    {{
      "step_number": 1,
      "score": <integer_score_-5_to_5>,
      "reasoning": "Explain specifically how this step contributed to or hindered overall task success. Reference the scoring criteria.",
      "situation": "A concise description of the DOM state at this step (what page/form/content was visible, key elements available)"
    }},
    {{
      "step_number": 2,
      "score": <integer_score_-5_to_5>,
      "reasoning": "Explain specifically how this step contributed to or hindered overall task success. Reference the scoring criteria.",
      "situation": "A concise description of the DOM state at this step (what page/form/content was visible, key elements available)"
    }}
  ]
}}

SCORING REMINDER:
- +4 to +5: Major breakthroughs/direct goal achievement
- +1 to +3: Positive progress/useful actions
- 0: Neutral/no impact
- -1 to -3: Waste/mistakes/wrong direction
- -4 to -5: Harmful/severe setbacks

Score all {len(steps_data)} steps with consistent standards.
"""
	
	messages = [
		SystemMessage(content=system_prompt),
		HumanMessage(content=prompt)
	]
	
	try:
		print(f"Making single API call to score {len(steps_data)} steps...")
		response = llm.invoke(messages)
		print(f"✓ Received response from LLM")
		
		# Parse JSON response, handling possible markdown formatting
		content = response.content.strip()
		
		# Check if the response is wrapped in markdown code blocks
		if content.startswith('```json'):
			# Extract JSON from markdown code block
			content = content[7:]  # Remove ```json
			if content.endswith('```'):
				content = content[:-3]  # Remove closing ```
		elif content.startswith('```'):
			# Handle case where it's just ```
			content = content[3:]
			if content.endswith('```'):
				content = content[:-3]
		
		# Parse the cleaned content
		score_data = json.loads(content.strip())
		
		# Validate the response structure
		if 'step_scores' not in score_data:
			raise ValueError("Missing 'step_scores' in LLM response")
		
		# Convert to the expected format and validate scores
		results = []
		task_analysis = score_data.get('task_analysis', '')
		
		for step_score in score_data.get('step_scores', []):
			step_num = step_score.get('step_number')
			score = step_score.get('score')
			reasoning = step_score.get('reasoning', '')
			situation = step_score.get('situation', '')
			
			# Validate score is within expected range
			if score is None or not isinstance(score, (int, float)):
				print(f"⚠️ Warning: Invalid score for step {step_num}: {score}")
				score = 0  # Default to neutral score
			elif score < -5 or score > 5:
				print(f"⚠️ Warning: Score {score} for step {step_num} is outside -5 to +5 range")
				score = max(-5, min(5, score))  # Clamp to valid range
			
			results.append({
				'step_number': step_num,
				'scores': {
					'step_score': int(score),  # Ensure integer
					'overall_reasoning': reasoning,
					'situation': situation
				}
			})
		
		# Validate we got scores for all steps
		if len(results) != len(steps_data):
			print(f"⚠️ Warning: Got {len(results)} scores but expected {len(steps_data)}")
		
		# Add task analysis to the first result only (not duplicated in each step)
		if results:
			results[0]['task_analysis'] = task_analysis
			
		print(f"✓ Successfully scored {len(results)} steps")
		return results
		
	except Exception as e:
		print(f"✗ Error in scoring: {e}")
		print(f"Response content: {response.content if 'response' in locals() else 'No response received'}")
		return [{
			'step_number': step['step_number'],
			'scores': None,
			'raw_response': response.content if 'response' in locals() else '',
			'error': str(e)
		} for step in steps_data]

def score_all_actions(
	json_path: str,
	llm: BaseChatModel,
	output_path: str = None
) -> List[Dict[str, Any]]:
	"""Score all actions in the session data"""
	
	# Load session data
	session_data = load_session_data(json_path)
	
	# Validate session data structure
	if 'steps' not in session_data:
		raise ValueError("Missing 'steps' in JSON data")
	
	# Create prompts
	system_prompt = create_scoring_prompt()
	# Use task from session_info if available
	task_context = "Web automation task"
	if 'session_info' in session_data:
		task_context = session_data['session_info'].get('task', task_context)
	
	print(f"Scoring {len(session_data['steps'])} steps...")
	print(f"Task: {task_context}")
	
	# Score all steps in a single API call
	all_scores = score_all_steps_batch(
		llm=llm,
		steps_data=session_data['steps'],
		task_context=task_context,
		system_prompt=system_prompt
	)
	
	# Check if scoring was successful
	if not all_scores or all_scores is None:
		print("✗ Warning: No scores were returned from the scoring function!")
		return []
	elif all(score.get('scores') is None for score in all_scores):
		print("✗ Warning: All scores are None - there was likely an error in processing!")
		return []
	else:
		print(f"✓ Successfully received {len(all_scores)} scored steps")
	
	# Save results
	if output_path is None:
		output_path = json_path.replace('.json', '_scored.json')
	elif output_path and not output_path.endswith('.json'):
		from pathlib import Path
		output_dir = Path(output_path)
		output_dir.mkdir(parents=True, exist_ok=True)
		input_filename = Path(json_path).stem
		output_filename = f"{input_filename}_scored.json"
		output_path = output_dir / output_filename
	
	# Extract task analysis from first step (if available)
	task_analysis = ""
	if all_scores and len(all_scores) > 0 and 'task_analysis' in all_scores[0]:
		task_analysis = all_scores[0]['task_analysis']
		# Remove task_analysis from the first step to avoid duplication
		del all_scores[0]['task_analysis']
	
	result = {
		'session_info': session_data.get('session_info', {'task': task_context}),
		'scoring_metadata': {
			'total_steps': len(session_data['steps']),
			'scoring_model': getattr(llm, 'model_name', 'unknown'),
			'task': task_context
		},
		'task_analysis': task_analysis,
		'scored_steps': all_scores
	}
	
	with open(output_path, 'w', encoding='utf-8') as f:
		json.dump(result, f, indent=2, ensure_ascii=False)
	
	print(f"Scoring complete! Results saved to: {output_path}")
	return all_scores

def main():
	"""Main function for command-line usage"""
	import argparse
	import os
	
	parser = argparse.ArgumentParser(description='Score browser automation actions')
	parser.add_argument('json_file', nargs='?', help='Path to the session JSON file')
	parser.add_argument('--output', '-o', help='Output file path')
	parser.add_argument('--model', default='google/gemini-2.5-pro', help='LLM model to use for scoring')
	parser.add_argument('--api-key', help='OpenAI API key')
	
	args = parser.parse_args()
	

	json_file = r"D:\supie\202506\browser-use-RL\json_logs\obsidian_20250626_144509_350746.json"
	output_file = r"D:\supie\202506\browser-use-RL\score_json"
	model_name = args.model
	
	# 如果没有文件提供，查找当前目录下的JSON文件
	if not json_file or not os.path.exists(json_file):
		json_files = [f for f in os.listdir('.') if f.endswith('.json') and 'session' in f]
		if json_files:
			json_file = json_files[0]
			print(f"Using found JSON file: {json_file}")
		else:
			print("No JSON file specified and none found in current directory")
			print("Usage: python action_scorer.py <json_file>")
			return
	
	# Check if file exists
	if not os.path.exists(json_file):
		print(f"Error: File '{json_file}' not found!")
		print(f"Current directory: {os.getcwd()}")
		print("Available files:")
		for f in os.listdir('.'):
			if f.endswith('.json'):
				print(f"  - {f}")
		return
	
	# Set up API key from api_key.py
	try:
		from api_key import Openrouter_API_KEY, Openrouter_BASE_URL
		api_key = Openrouter_API_KEY
		base_url = Openrouter_BASE_URL
		print(f"✓ Loaded API key from api_key.py")
		print(f"✓ Base URL: {base_url}")
	except ImportError:
		print("Error: api_key.py not found!")
		# Fallback to command line or environment
		api_key = args.api_key or os.getenv('OPENAI_API_KEY')
		base_url = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')

	
	# Initialize LLM
	try:
		from langchain_openai import ChatOpenAI
		llm = ChatOpenAI(
			model=model_name, 
			temperature=0,
			api_key=api_key,
			base_url=base_url,
			max_tokens=None,
			timeout=300
		)
		print(f"✓ Initialized {model_name} with base_url: {base_url}")
	except ImportError:
		print("Error: langchain_openai not installed!")
		print("Install with: pip install langchain-openai")
		return
	except Exception as e:
		print(f"Error initializing LLM: {e}")
		return

	try:
		score_all_actions(json_file, llm, output_file)
	except Exception as e:
		print(f"Error during scoring: {e}")
		import traceback
		traceback.print_exc()

if __name__ == "__main__":
	main()