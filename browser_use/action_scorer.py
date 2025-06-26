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

EVALUATION APPROACH:
1. First understand the complete task flow from start to finish
2. Identify key decision points, breakthroughs, and setbacks
3. Evaluate each step's value within the full context
4. Consider how each step enables or hinders subsequent steps
5. Score from -10 to +10 based on overall contribution to task completion

SCORING PHILOSOPHY:
- Steps are interconnected - evaluate their role in the complete strategy
- Early steps that enable later success deserve credit
- Steps that waste time or lead to dead ends should be penalized
- Key breakthrough moments that solve the core problem deserve highest scores
- Consider both immediate effects and long-term consequences

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

Analyze the complete execution sequence below. Understand the full journey from start to finish, then score each step based on its contribution to the overall task success.

Consider:
- How did the overall strategy unfold?
- Which steps were crucial breakthroughs?
- Which steps wasted time or created problems?
- How do early decisions impact later success?
- What was the turning point that led to completion?

COMPLETE EXECUTION SEQUENCE:
{all_steps_info}

Provide your analysis in JSON format:

{{
  "task_analysis": "<overall_strategy_analysis>Your comprehensive analysis of execution flow, key decisions, and turning points</overall_strategy_analysis>",
  "step_scores": [
    {{
      "step_number": 1,
      "score": <integer_score_-10_to_10>,
      "reasoning": "<contribution_analysis>Explain how this specific step contributed to or hindered the overall task success</contribution_analysis>"
    }},
    {{
      "step_number": 2,
      "score": <integer_score_-10_to_10>,
      "reasoning": "<contribution_analysis>Explain how this specific step contributed to or hindered the overall task success</contribution_analysis>"
    }}
  ]
}}

Score all {len(steps_data)} steps considering their role in the complete task flow.
"""
	
	messages = [
		SystemMessage(content=system_prompt),
		HumanMessage(content=prompt)
	]
	
	try:
		print(f"Making single API call to score {len(steps_data)} steps...")
		response = llm.invoke(messages)
		print(f"✓ Received response from LLM")
		
		# Parse JSON response directly
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
				}
			})
		
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
		output_path = json_path.replace('.json', '_scored1.json')
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
	parser.add_argument('--model', default='openai/gpt-4.1-mini', help='LLM model to use for scoring')
	parser.add_argument('--api-key', help='OpenAI API key')
	
	args = parser.parse_args()
	

	json_file = r"D:\supie\202506\browser-use-RL\json_logs\google_search_20250625_170919.json"
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
			model=model_name, 
			temperature=0,
			api_key=api_key,
			base_url=base_url,
			max_tokens=None,  # 无token限制
			timeout=300  # 5分钟超时
		)
		print(f"✓ Initialized {model_name} with base_url: {base_url}")
	except ImportError:
		print("Error: langchain_openai not installed!")
		print("Install with: pip install langchain-openai")
		return
	except Exception as e:
		print(f"Error initializing LLM: {e}")
		return
	
	# Score actions
	try:
		score_all_actions(json_file, llm, output_file)
	except Exception as e:
		print(f"Error during scoring: {e}")
		import traceback
		traceback.print_exc()

if __name__ == "__main__":
	main()