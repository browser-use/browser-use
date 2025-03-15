import asyncio
import os
import random
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import lucidicai as lai
import openai
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
LUICIDIC_API_KEY = os.getenv('LUICIDIC_API_KEY')
LUICIDIC_AGENT_ID = os.getenv('LUICIDIC_AGENT_ID')
if not OPENAI_API_KEY:
	raise ValueError('OPENAI_API_KEY is not set in the environment variables.')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
	print('Warning: GEMINI_API_KEY not found. Browser agent functionality might be limited or use fallbacks.')
	llm_for_agent = None
else:
	# llm_for_agent = ChatGoogleGenerativeAI(model='gemini-2.0-flash', api_key=SecretStr(GEMINI_API_KEY))
	llm_for_agent = ChatOpenAI(model='gpt-4.1', api_key=SecretStr(OPENAI_API_KEY))


client = openai.OpenAI(api_key=OPENAI_API_KEY)

LLM_MODEL_FOR_SIMULATION = 'gpt-4o-mini'


async def get_llm_simulated_response(prompt_message, system_message='You are a helpful assistant simulating user responses.'):
	try:
		response = client.chat.completions.create(
			model=LLM_MODEL_FOR_SIMULATION,
			messages=[{'role': 'system', 'content': system_message}, {'role': 'user', 'content': prompt_message}],
		)
		return response.choices[0].message.content.strip()
	except Exception as e:
		print(f'LLM call failed: {e}')
		return "LLM Fallback Response: I'm not sure."


TASK_DESCRIPTION = 'Simulate a restaurant booking agent.'
MASS_SIM_ID = 'd8f6238c-ee84-4d01-9614-b5018d77eefc'


async def simulate_chat_interaction():
	lai.create_step(
		state='Gathering user preferences',
		action='Initiating LLM-driven chat with user',
		goal="Understand the user's restaurant needs (type, location, stars) via LLM simulation",
	)

	random_context_snippets = [
		'Mmm, cheap pizza sounds really good right now.',
		"I'm in the mood for something spicy, perhaps a good curry?",
		'Feeling like a fancy night out, something upscale perhaps.',
		"It's quite chilly today, so a warm and hearty meal would be perfect.",
		"Just saw a cooking show about Japanese food, now I'm craving ramen or sushi (not too expensive)",
		'Thinking of a place with a great outdoor seating area since the weather is lovely.',
		'Celebrating a special occasion, so looking for a memorable dining experience.',
		"I'm feeling adventurous, maybe I'll try a cuisine I've never had before.",
		'Looking for a cozy and casual spot for a relaxed dinner.',
	]
	selected_random_context = random.choice(random_context_snippets)

	system_prompt_user_simulation = (
		f'{selected_random_context} You are simulating a user looking for a restaurant. Respond naturally and concisely. '
		'When asked for cuisine, choose one from: Italian, Mexican, Chinese, Indian, Thai, Japanese, French, American. '
		'When asked for location, choose one major city from: New York, Los Angeles, Chicago, San Francisco, Miami, London, Paris, Tokyo. '
		"When asked for star rating, choose one from: 3-star, 4-star, 5-star, or 'any star rating'. "
		'Please try to vary your choices for cuisine, location, and star rating each time as if you are a different user or have different preferences today, perhaps influenced by the initial thought provided.'
	)

	agent_q1 = 'Hello! I can help you find a restaurant. What type of cuisine are you in the mood for?'
	print(f'Agent: {agent_q1}')
	lai.create_event(description='Agent asks for cuisine type', result='User interaction initiated for cuisine preference.')
	lai.end_event()
	user_cuisine_preference = await get_llm_simulated_response(
		f"The agent asked: '{agent_q1}'. What is your preferred cuisine? Just state the cuisine type.",
		system_prompt_user_simulation,
	)
	user_cuisine_preference = (
		user_cuisine_preference.split('.')[0].split(',')[0].replace('I want', '').replace('I would like', '').strip()
	)
	print(f'User (LLM): {user_cuisine_preference}')
	lai.create_event(
		description='User (LLM) responds with cuisine type', result=f'User prefers {user_cuisine_preference} cuisine.'
	)
	lai.end_event()

	agent_q2 = 'Great! And where are you looking for a restaurant? (e.g., city or zip code)'
	print(f'Agent: {agent_q2}')
	lai.create_event(description='Agent asks for location', result='User interaction for location preference.')
	lai.end_event()
	user_location_preference = await get_llm_simulated_response(
		f"The agent asked: '{agent_q2}'. Your preferred cuisine is {user_cuisine_preference}. What city are you looking in? Just state the city name.",
		system_prompt_user_simulation,
	)
	user_location_preference = user_location_preference.split('.')[0].split(',')[0].strip()
	print(f'User (LLM): {user_location_preference}')
	lai.create_event(
		description='User (LLM) responds with location', result=f'User prefers a restaurant in {user_location_preference}.'
	)
	lai.end_event()

	agent_q3 = 'Got it. Any preference on the star rating? (e.g., 3-star, 4-star, 5-star)'
	print(f'Agent: {agent_q3}')
	lai.create_event(description='Agent asks for star rating', result='User interaction for star rating preference.')
	lai.end_event()
	user_stars_preference = await get_llm_simulated_response(
		f"The agent asked: '{agent_q3}'. You want {user_cuisine_preference} in {user_location_preference}. What star rating? Just state the rating (e.g., '4-star' or 'any').",
		system_prompt_user_simulation,
	)
	user_stars_preference = user_stars_preference.split('.')[0].split(',')[0].strip()
	print(f'User (LLM): {user_stars_preference}')
	lai.create_event(
		description='User (LLM) responds with star rating', result=f'User prefers a {user_stars_preference} restaurant.'
	)
	lai.end_event()

	lai.end_step()
	return {
		'cuisine': user_cuisine_preference if user_cuisine_preference else 'Any',
		'location': user_location_preference if user_location_preference else 'Anywhere',
		'stars': user_stars_preference if user_stars_preference else 'any',
	}


async def simulate_browser_search(preferences):
	global llm_for_agent

	lai.create_step(
		state='Initializing browser agent for search',
		action='Setting up browser and agent components',
		goal='Prepare for restaurant search using browser automation principles',
	)

	if llm_for_agent is None:
		print('Warning: Agent LLM not available (GEMINI_API_KEY likely missing). Proceeding with limited simulation.')
		lai.create_event(description='Agent LLM Error', result='GEMINI_API_KEY not found, cannot initialize full agent.')
		lai.end_event()
		lai.end_step()
		print(
			f"\nAgent (simulation fallback): Okay, I'm searching for {preferences['stars']} {preferences['cuisine']} restaurants in {preferences['location']}..."
		)
		await asyncio.sleep(1)
		found_restaurant = f'The {preferences["cuisine"]} Place in {preferences["location"]}'
		print(f'Agent (simulation fallback): I found a great option: {found_restaurant}!')
		lai.create_event(
			description='Fallback restaurant search simulation', result=f'Simulated finding restaurant: {found_restaurant}'
		)
		lai.end_event()
		return found_restaurant

	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			viewport_expansion=0,
			user_data_dir='~/.config/browseruse/profiles/default',
			highlight_elements=False,
		)
	)

	agent_task = f'Find a {preferences["stars"]} {preferences["cuisine"]} restaurant in {preferences["location"]}.'
	agent = Agent(
		task=agent_task,
		llm=llm_for_agent,
		max_actions_per_step=3,
		browser_session=browser_session,
	)

	handler = lai.LucidicLangchainHandler()
	handler.attach_to_llms(agent)

	lai.create_event(description='Browser Agent Initialized', result=f'Agent ready to search for: {agent_task}')
	lai.end_event()
	lai.end_step()

	print(f'\nAgent: My browser agent is now executing the task: {agent_task} (this may open a browser window)...')
	try:
		await agent.run(max_steps=5)
		print('Agent: Browser agent run completed its cycle.')
	except Exception as e:
		print(f'Agent: Browser agent execution encountered an error: {e}')

	lai.create_step(
		state='Finalizing restaurant choice',
		action='Generating a creative name for the found restaurant type',
		goal='Present a plausible restaurant option to the user',
	)
	restaurant_prompt = f'Generate a creative and appealing name for a top-rated {preferences["stars"]} {preferences["cuisine"]} restaurant in {preferences["location"]}. Only return the name.'
	found_restaurant = await get_llm_simulated_response(restaurant_prompt, 'You are a creative naming expert for restaurants.')
	found_restaurant = found_restaurant.replace('"', '').strip()
	if not found_restaurant or 'LLM Fallback' in found_restaurant or len(found_restaurant) > 70:
		found_restaurant = f'The {preferences["cuisine"]} Gem of {preferences["location"]}'

	print(f"Agent: Based on the search, I've found a great option: {found_restaurant}!")
	lai.create_event(
		description='LLM generated restaurant name post-agent simulation', result=f'Simulated agent found: {found_restaurant}'
	)
	lai.end_event()
	lai.end_step()

	return found_restaurant


async def simulate_payment(restaurant_name):
	lai.create_step(
		state='Processing payment',
		action=f'Initiating payment for booking at {restaurant_name}',
		goal='Secure the restaurant booking via simulated payment',
	)
	print(f'\nAgent: Attempting to process payment for your booking at {restaurant_name}...')
	lai.create_event(
		description='Initiating Stripe payment simulation', result='Processing payment information via fake Stripe API.'
	)
	lai.end_event()

	await asyncio.sleep(1)

	payment_succeeded = random.random() > 0.5

	if payment_succeeded:
		print('Agent: Payment successful! Your booking is confirmed.')
		lai.create_event(description='Payment simulation result', result='Payment successful.')
		lai.end_event()
	else:
		error_reason = random.choice(['Insufficient funds', 'Card declined', 'Gateway timeout'])
		print(f'Agent: Oh no, the payment failed. Reason: {error_reason}.')
		lai.create_event(description='Payment simulation result', result=f'Payment failed: {error_reason}')
		lai.end_event()

		print('Agent: Let me try to resolve this... (simulating resolution)')
		lai.create_event(description='Attempting payment resolution', result='Simulating payment issue resolution.')
		lai.end_event()
		await asyncio.sleep(2)
		print('Agent: Payment issue resolved! Your booking is now confirmed.')
		lai.create_event(description='Payment resolution result', result='Payment successfully processed after re-attempt.')
		lai.end_event()

	lai.end_step()
	return True


async def request_survey():
	lai.create_step(
		state='Post-booking follow-up', action='Requesting user feedback', goal='Gather user satisfaction via a survey'
	)
	print('\nAgent: Great! Your booking is all set. Would you mind filling out a short survey about your experience?')
	lai.create_event(description='Survey request', result='User asked to fill out a survey.')
	lai.end_event()
	await asyncio.sleep(0.5)
	print('User: Sure, I can do that.')
	lai.create_event(description='User response to survey request', result='User agreed to fill out the survey.')
	lai.end_event()
	lai.end_step()


async def run_restaurant_agent():
	lai.init(
		'Restaurant Booking Agent Simulation',
		task=TASK_DESCRIPTION,
		# mass_sim_id=MASS_SIM_ID,
		providers=['openai', 'gemini'],
	)

	preferences = await simulate_chat_interaction()
	restaurant = await simulate_browser_search(preferences)
	payment_successful = await simulate_payment(restaurant)

	if payment_successful:
		await request_survey()

	print('\nAgent: Thank you for using the Restaurant Booking Agent!')
	lai.end_session()


if __name__ == '__main__':
	asyncio.run(run_restaurant_agent())
