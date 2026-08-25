import asyncio

from browser_use import Agent, Browser, ChatOpenAI

llm = ChatOpenAI(
	model='ultrafast',
	base_url='https://browser-use-org--q38-bench-sgl-dflash2-k8-serve.modal.run/v1',
	api_key='ultrafast-bench',
	temperature=0.7,
	top_p=0.8,
	presence_penalty=0.0,
	frequency_penalty=0.0,
	extra_body={
		'top_k': 20,
		'chat_template_kwargs': {'enable_thinking': False, 'preserve_thinking': False},
	},
)

browser = Browser(
	executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	user_data_dir='~/Library/Application Support/Google/Chrome',
	profile_directory='Default',
)

task = '''
Go to target.com and add these to the cart, set for delivery (not pickup):
- Hues and Cues board game
- Pack of big claw hair clips
- Starbursts
- Birthday wrapping paper for a young girl
Add them one at a time, confirming each is in the cart before starting the next.
Then go to checkout and stop as soon as it asks for a credit card or address.
'''

asyncio.run(Agent(task=task, llm=llm, browser=browser, ultrafast=True).run(max_steps=120))
