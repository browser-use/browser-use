#!/usr/bin/env python3
"""Send the same captured contexts CONCURRENTLY (server batches them) and check
whether batched decode degrades the output vs the batch-1 (correct) replay."""
import json, os, sys, asyncio
sys.path.insert(0, '/Users/shiqihe/Desktop/3_Project/browser-use')
from openai import AsyncOpenAI
from pydantic import TypeAdapter
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer

_MSGS = TypeAdapter(list[BaseMessage])
TEMP = float(sys.argv[1]) if len(sys.argv) > 1 else 0.2
ROOT = '/Users/shiqihe/Desktop/3_Project/browser-use'
OUT = 'simulator/runs/WebVoyager-GAIA-topk32-32b-20260624'
STEPS = [
	('webvoyager__Allrecipes--0', 'step_001'),
	('webvoyager__Allrecipes--0', 'step_003'),
	('webvoyager__Allrecipes--1', 'step_002'),
	('webvoyager__Allrecipes--2', 'step_001'),
]
client = AsyncOpenAI(base_url='http://localhost:10000/v1', api_key='EMPTY')

def load(task, step):
	td = os.path.join(ROOT, OUT, task); sd = os.path.join(td, step)
	q = json.load(open(os.path.join(td, 'meta.json')))['question']
	schema = json.loads(open(os.path.join(td, 'tool_schema.json')).read())
	msgs = _MSGS.validate_python(json.loads(open(os.path.join(sd, 'messages.json')).read())['messages'])
	ser = OpenAIMessageSerializer.serialize_messages(msgs)
	rf = {'type': 'json_schema', 'json_schema': {'name': schema['name'], 'strict': True, 'schema': schema['schema']}}
	return q, ser, rf

async def one(task, step):
	q, ser, rf = load(task, step)
	r = await client.chat.completions.create(model='tree-sparse', messages=ser, response_format=rf,
	                                          temperature=TEMP, max_completion_tokens=1024)
	c = r.choices[0].message.content or ''
	try:
		o = json.loads(c); ng = o.get('next_goal', ''); act = o.get('action')
	except Exception:
		ng = '(unparseable)'; act = c[:60]
	ontask = any(w in (ng + json.dumps(act)).lower() for w in ['lasagna', 'recipe', 'vegetarian'])
	return task, step, q, ng, act, ontask

async def main():
	print(f"=== BATCHED ({len(STEPS)} concurrent) @ temp {TEMP} ===")
	res = await asyncio.gather(*[one(t, s) for t, s in STEPS])
	ok = 0
	for task, step, q, ng, act, ontask in res:
		ok += ontask
		print(f"  {'OK ' if ontask else 'OFF'} {task}/{step}")
		print(f"      next_goal: {ng[:115]}")
		print(f"      action:    {json.dumps(act)[:80]}")
	print(f"on-task: {ok}/{len(res)}")

asyncio.run(main())
