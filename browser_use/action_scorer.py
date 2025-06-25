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
	return """You are an expert evaluator for browser automation tasks. Your job is to score actions taken by an AI agent during web browsing.

TASK BACKGROUND:
The agent is performing various web automation tasks. Your goal is to evaluate how well each action contributes to the completion of the specific task.

KEY EVALUATION PRINCIPLES:
1. Navigate efficiently to target websites
2. Interact with elements systematically 
3. Extract information as needed
4. Complete the task thoroughly
5. Avoid unnecessary repetitions or mistakes
6. Handle errors gracefully

JSON DATA STRUCTURE:
Each step contains:
- dom_state: Current webpage state (URL, interactive elements, scroll position)
- agent_response: AI's decision (thinking, evaluation, memory, next goal, actions)

SCORING CRITERIA:
Rate each action from -5 to +5 based on how well it contributes to completing the task:
- +5: Excellent action that directly advances the task
- +3 to +4: Good action that makes reasonable progress  
- +1 to +2: Acceptable action with some value
- 0: Neutral action (neither helps nor hurts)
- -1 to -2: Somewhat counterproductive action
- -3 to -4: Poor action that wastes time/effort
- -5: Very harmful action that significantly impedes progress

Consider:
- Is the action appropriate for the current state?
- Does it move toward the ultimate goal?
- Is it efficient or wasteful?
- Does it fit the systematic approach needed?
- Is the task actually completed or a hallucinated early stop?
- Don't believe what the agent said. Judge it critically."""

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
- Thinking: {agent_response['thinking']}
- Previous Goal: {agent_response['evaluation_previous_goal']}
- Memory: {agent_response['memory']}
- Next Goal: {agent_response['next_goal']}

ACTIONS: {json.dumps(agent_response['action'], indent=2)}
"""
		all_steps_info += step_info + "\n" + "="*50 + "\n"
	
	# Create comprehensive prompt
	prompt = f"""
TASK: {task_context}

Please analyze the complete task execution and score each step from -5 to +5.

REASONING PROCESS:
1. First analyze the overall strategy: What approach did the agent take?
2. Evaluate efficiency: Were there unnecessary repetitions or missed opportunities?
3. Assess each step's contribution to the ultimate goal
4. Consider context: Some actions (like pagination) are necessary even if repetitive

ALL STEPS TO EVALUATE:
{all_steps_info}

IMPORTANT: Respond with valid JSON only. No comments, no explanations outside JSON.

{{
  "task_analysis": "Your overall analysis of the task execution strategy and effectiveness",
  "step_scores": [
    {{
      "step_number": 1,
      "score": -5,
      "reasoning": "explanation here"
    }},
    {{
      "step_number": 2,
      "score": 0,
      "reasoning": "explanation here"
    }}
  ]
}}

You MUST provide scores for all {len(steps_data)} steps. Make sure the JSON is valid with proper quotes and commas.
"""
	
	messages = [
		SystemMessage(content=system_prompt),
		HumanMessage(content=prompt)
	]
	
	try:
		print("Making single API call to score all steps...")
		response = llm.invoke(messages)
		score_data = json.loads(response.content)
		
		# Convert to the expected format
		results = []
		task_analysis = score_data.get('task_analysis', '')
		
		for step_score in score_data.get('step_scores', []):
			results.append({
				'step_number': step_score['step_number'],
				'scores': {
					'step_score': step_score['score'],
					'overall_reasoning': step_score['reasoning']
				},
				'raw_response': response.content
			})
		
		# Add task analysis to the first result
		if results:
			results[0]['task_analysis'] = task_analysis
			
		print(f"✓ Successfully scored {len(results)} steps in one API call")
		return results
		
	except json.JSONDecodeError as e:
		print(f"JSON parsing failed: {e}")
		print("Full response content:", response.content)
		
		# Try to extract JSON from markdown code blocks
		import re
		json_match = re.search(r'```json\s*(\{.*?\})\s*```', response.content, re.DOTALL)
		if json_match:
			try:
				json_content = json_match.group(1)
				print(f"Extracted JSON length: {len(json_content)} characters")
				score_data = json.loads(json_content)
				print("✓ Successfully extracted JSON from markdown")
			except Exception as json_err:
				print(f"✗ Failed to parse extracted JSON: {json_err}")
				print("Full extracted content:", json_content)
				print("✗ Failed to parse extracted JSON")
				# Fallback: return error for all steps
				return [{
					'step_number': step['step_number'],
					'scores': None,
					'raw_response': response.content,
					'error': f'Failed to parse JSON response: {e}'
				} for step in steps_data]
		else:
			# Fallback: return error for all steps
			return [{
				'step_number': step['step_number'],
				'scores': None,
				'raw_response': response.content,
				'error': f'Failed to parse JSON response: {e}'
			} for step in steps_data]
	except Exception as e:
		print(f"Error in batch scoring: {e}")
		import traceback
		traceback.print_exc()
		return [{
			'step_number': step['step_number'],
			'scores': None,
			'raw_response': '',
			'error': f'Unexpected error: {e}'
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
	
	# Save results
	if output_path is None:
		output_path = json_path.replace('.json', '_scored.json')
	
	result = {
		'session_info': session_data.get('session_info', {'task': task_context}),
		'scoring_metadata': {
			'total_steps': len(session_data['steps']),
			'scoring_model': getattr(llm, 'model_name', 'unknown'),
			'task': task_context
		},
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
	parser.add_argument('--model', default='gpt-4o-mini', help='LLM model to use for scoring')
	parser.add_argument('--api-key', help='OpenAI API key')
	
	args = parser.parse_args()
	
	# If no file provided, look for JSON files in current directory
	if not args.json_file:
		json_files = [f for f in os.listdir('.') if f.endswith('.json') and 'session' in f]
		if json_files:
			args.json_file = json_files[0]
			print(f"Using found JSON file: {args.json_file}")
		else:
			print("No JSON file specified and none found in current directory")
			print("Usage: python action_scorer.py <json_file>")
			return
	
	# Check if file exists
	if not os.path.exists(args.json_file):
		print(f"Error: File '{args.json_file}' not found!")
		print(f"Current directory: {os.getcwd()}")
		print("Available files:")
		for f in os.listdir('.'):
			if f.endswith('.json'):
				print(f"  - {f}")
		return
	
	# Set up API key from api_key.py
	try:
		from api_key import OpenAI_API_KEY, OPENAI_BASE_URL
		api_key = OpenAI_API_KEY
		base_url = OPENAI_BASE_URL
		print(f"✓ Loaded API key from api_key.py")
		print(f"✓ Base URL: {base_url}")
	except ImportError:
		print("Error: api_key.py not found!")
		# Fallback to command line or environment
		api_key = args.api_key or os.getenv('OPENAI_API_KEY')
		base_url = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')
		if not api_key:
			print("Please either:")
			print("1. Create api_key.py with OpenAI_API_KEY and OPENAI_BASE_URL")
			print("2. Set OPENAI_API_KEY environment variable") 
			print("3. Use --api-key parameter")
			return
	except Exception as e:
		print(f"Error loading from api_key.py: {e}")
		return
	
	# Initialize LLM
	try:
		from langchain_openai import ChatOpenAI
		llm = ChatOpenAI(
			model=args.model, 
			temperature=0,
			api_key=api_key,
			base_url=base_url,
			max_tokens=None,  # 无token限制
			timeout=300  # 5分钟超时
		)
		print(f"✓ Initialized {args.model} with base_url: {base_url}")
	except ImportError:
		print("Error: langchain_openai not installed!")
		print("Install with: pip install langchain-openai")
		return
	except Exception as e:
		print(f"Error initializing LLM: {e}")
		return
	
	# Score actions
	try:
		score_all_actions(args.json_file, llm, args.output)
	except Exception as e:
		print(f"Error during scoring: {e}")
		import traceback
		traceback.print_exc()

if __name__ == "__main__":
	main()