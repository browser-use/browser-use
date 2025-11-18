"""
Quick script to list available NVIDIA Direct API models.

Setup:
1. Add your API key to .env:
   NVIDIA_DIRECT_API_KEY=nvapi-xxxxxxxxxxxxx

   Get your key from: https://build.nvidia.com/explore/discover

2. Run: uv run python browser_use/llm/nvidia/list_models_direct.py
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


async def list_models():
	"""List all available models on NVIDIA Direct API."""
	api_key = os.getenv('NVIDIA_DIRECT_API_KEY')
	if not api_key:
		print('❌ NVIDIA_DIRECT_API_KEY not found in .env file')
		print('\nGet your API key from: https://build.nvidia.com/explore/discover')
		print('Then add it to browser_use/llm/nvidia/.env:')
		print('  NVIDIA_DIRECT_API_KEY=nvapi-xxxxxxxxxxxxx\n')
		return

	print('Fetching available NVIDIA models from https://integrate.api.nvidia.com/v1...\n')

	client = AsyncOpenAI(
		base_url='https://integrate.api.nvidia.com/v1',
		api_key=api_key,
	)

	try:
		models = await client.models.list()
		print(f'✅ Found {len(models.data)} models:\n')

		# Categorize models
		llama_models = []
		nemotron_models = []
		vision_models = []
		other_models = []

		for model in models.data:
			model_id = model.id
			if 'llama' in model_id.lower():
				llama_models.append(model_id)
			elif 'nemotron' in model_id.lower():
				nemotron_models.append(model_id)
			elif any(keyword in model_id.lower() for keyword in ['vision', 'phi-3', 'deplot', 'kosmos']):
				vision_models.append(model_id)
			else:
				other_models.append(model_id)

		if nemotron_models:
			print('🎯 NVIDIA Nemotron Models:')
			for m in nemotron_models:
				print(f'  - {m}')
			print()

		if llama_models:
			print('🦙 Llama Models:')
			for m in llama_models:
				print(f'  - {m}')
			print()

		if vision_models:
			print('👁️  Vision/Multimodal Models:')
			for m in vision_models:
				print(f'  - {m}')
			print()

		if other_models:
			print('🔧 Other Models:')
			for m in other_models:
				print(f'  - {m}')
			print()

		print('\n💡 Recommended for browser-use:')
		print('  - nvidia/llama-3.1-nemotron-70b-instruct (strong general model)')
		print('  - meta/llama-3.1-70b-instruct (Llama 3.1)')
		print('  - microsoft/phi-3-vision-128k-instruct (vision support)')

	except Exception as e:
		print(f'❌ Error listing models: {e}')
		print('\nMake sure:')
		print('  1. Your API key is valid')
		print('  2. You have network connectivity')
		print('  3. The API endpoint is accessible')


if __name__ == '__main__':
	asyncio.run(list_models())
