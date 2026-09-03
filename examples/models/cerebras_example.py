"""
Example of using Cerebras with browser-use.

To use this example:
1. Set your CEREBRAS_API_KEY environment variable
2. Run this script

Cerebras integration is working great for:
- Direct text generation
- Simple tasks without complex structured output
- Fast inference for web automation

Available Cerebras models (9 total):
Small/Fast models (8B-32B):
- cerebras_llama3_1_8b (8B parameters, fast)
- cerebras_llama_4_scout_17b_16e_instruct (17B, instruction-tuned)
- cerebras_llama_4_maverick_17b_128e_instruct (17B, extended context)
- cerebras_qwen_3_32b (32B parameters)

Large/Capable models (70B-480B):
- cerebras_llama3_3_70b (70B parameters, latest version)
- cerebras_gpt_oss_120b (120B parameters, OpenAI's model)
- cerebras_qwen_3_235b_a22b_instruct_2507 (235B, instruction-tuned)
- cerebras_qwen_3_235b_a22b_thinking_2507 (235B, complex reasoning)
- cerebras_qwen_3_coder_480b (480B, code generation)

Note: Cerebras has some limitations with complex structured output due to JSON schema compatibility.
"""

import asyncio
import os

from browser_use import Agent


async def main():
	# Set your API key (recommended to use environment variable)
	api_key = os.getenv('CEREBRAS_API_KEY')
	if not api_key:
		raise ValueError('Please set CEREBRAS_API_KEY environment variable')

	# Option 1: Use the pre-configured model instance (recommended)
	from browser_use import llm

	# Choose your model:
	# Small/Fast models:
	# model = llm.cerebras_llama3_1_8b      # 8B, fast
	# model = llm.cerebras_llama_4_scout_17b_16e_instruct  # 17B, instruction-tuned
	# model = llm.cerebras_llama_4_maverick_17b_128e_instruct  # 17B, extended context
	# model = llm.cerebras_qwen_3_32b       # 32B

	# Large/Capable models:
	# model = llm.cerebras_llama3_3_70b     # 70B, latest
	# model = llm.cerebras_gpt_oss_120b      # 120B, OpenAI's model
	# model = llm.cerebras_qwen_3_235b_a22b_instruct_2507  # 235B, instruction-tuned
	model = llm.cerebras_qwen_3_235b_a22b_thinking_2507  # 235B, complex reasoning
	# model = llm.cerebras_qwen_3_coder_480b  # 480B, code generation

	# Option 2: Create the model instance directly
	# model = ChatCerebras(
	#     model="qwen-3-coder-480b",  # or any other model ID
	#     api_key=os.getenv("CEREBRAS_API_KEY"),
	#     temperature=0.2,
	#     max_tokens=4096,
	# )

	# Create and run the agent with a simple task
	task = 'Explain the concept of quantum entanglement in simple terms.'
	agent = Agent(task=task, llm=model)

	print(f'Running task with Cerebras {model.name} (ID: {model.model}): {task}')
	history = await agent.run(max_steps=3)
	result = history.final_result()

	print(f'Result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
