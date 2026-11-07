"""
One Browser Use agent with a browser and a cloud Android phone from Mobilebox (https://mobilebox.dev).

Two custom actions call the Mobilebox REST API: phone_screen reads the screen, phone_act taps, types and opens apps.
Your code owns the phone: it is created before the run and deleted in `finally`.

Run from the repository root:
	export MOBILESANDBOX_API_KEY=...  # https://mobilebox.dev/dashboard
	export OPENAI_API_KEY=...
	uv run examples/integrations/mobilebox/phone_agent.py
"""

import asyncio
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI, Tools

API = 'https://mobilebox.dev/v1/phones'
AUTH = {'Authorization': f'Bearer {os.environ["MOBILESANDBOX_API_KEY"]}', 'Content-Type': 'application/json'}


def phones(method: str, path: str = '', body: dict | None = None):
	data = json.dumps(body).encode() if body else None
	req = urllib.request.Request(API + path, method=method, headers=AUTH, data=data)
	with urllib.request.urlopen(req) as res:
		return json.loads(res.read() or 'null')


phone = phones('POST', '?wait=ready')['id']
tools = Tools()


@tools.action('Read the phone screen as numbered elements: [ref] Type "text" (x,y)')
def phone_screen() -> str:
	return phones('GET', f'/{phone}/observe')['text']


@tools.action(
	'Run phone actions, a JSON list such as [{"type":"open_app","package":"com.android.settings"},'
	'{"type":"tap","target":{"text":"Display"}}]. Returns each result and the new screen.'
)
def phone_act(actions: str) -> str:
	try:
		done = phones('POST', f'/{phone}/actions', {'actions': json.loads(actions)})
	except urllib.error.HTTPError as error:
		return error.read().decode()  # code, message and next: what to do instead
	return json.dumps(done['results']) + '\n' + done['screen']['text']


async def main():
	try:
		task = (
			'You have a cloud Android phone: drive it with phone_screen and phone_act. On it, open Settings > About phone '
			"and read the Android version. Then find that version's release date on en.wikipedia.org."
		)
		agent = Agent(task=task, llm=ChatOpenAI(model=os.environ.get('MODEL', 'gpt-5.4-mini')), tools=tools)
		history = await agent.run(max_steps=25)
		print(history.final_result())
	finally:
		phones('DELETE', f'/{phone}')


if __name__ == '__main__':
	asyncio.run(main())
