#!/usr/bin/env python3
"""Replay selected captured contexts against the server and dump the model's
thinking / next_goal / action. Run once per top-k setting (label via argv) to
compare full attention vs top-k 32 on identical inputs (temperature 0)."""
import json, os, sys, glob
sys.path.insert(0, '/Users/shiqihe/Desktop/3_Project/browser-use')
from openai import OpenAI
from pydantic import TypeAdapter
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer

_MSGS = TypeAdapter(list[BaseMessage])
LABEL = sys.argv[1] if len(sys.argv) > 1 else 'topk?'
TEMP = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
NSAMP = int(sys.argv[3]) if len(sys.argv) > 3 else 1
OUT = 'simulator/runs/WebVoyager-GAIA-topk32-32b-20260624'
ROOT = '/Users/shiqihe/Desktop/3_Project/browser-use'
STEPS = [
	('webvoyager__Allrecipes--0', 'step_001'),
	('webvoyager__Allrecipes--0', 'step_003'),
	('webvoyager__Allrecipes--1', 'step_002'),
	('webvoyager__Allrecipes--2', 'step_001'),
]
client = OpenAI(base_url='http://localhost:10000/v1', api_key='EMPTY')
results = []
for task, step in STEPS:
	td = os.path.join(ROOT, OUT, task)
	sd = os.path.join(td, step)
	q = json.load(open(os.path.join(td, 'meta.json')))['question']
	schema = json.loads(open(os.path.join(td, 'tool_schema.json')).read())
	msgs = _MSGS.validate_python(json.loads(open(os.path.join(sd, 'messages.json')).read())['messages'])
	serialized = OpenAIMessageSerializer.serialize_messages(msgs)
	rf = {'type': 'json_schema', 'json_schema': {'name': schema['name'], 'strict': True, 'schema': schema['schema']}}
	print(f"[{LABEL} T={TEMP}] {task}/{step}  TASK={q[:50]}")
	for s in range(NSAMP):
		resp = client.chat.completions.create(model='tree-sparse', messages=serialized, response_format=rf,
		                                      temperature=TEMP, max_completion_tokens=1024)
		content = resp.choices[0].message.content or ''
		try:
			o = json.loads(content)
			ng = o.get('next_goal', ''); act = o.get('action'); th = (o.get('thinking') or '')[:90]
		except Exception:
			ng = '(unparseable)'; act = content[:80]; th = ''
		# on-task heuristic: does next_goal mention the task's key noun?
		ontask = any(w in (ng + json.dumps(act)).lower() for w in ['lasagna', 'recipe', 'vegetarian', 'search'])
		print(f"   s{s} {'OK ' if ontask else 'OFF'} next_goal: {ng[:110]}")
		results.append({'task': task, 'step': step, 'temp': TEMP, 'sample': s, 'question': q,
		                'next_goal': ng, 'action': act, 'thinking': th, 'ontask': ontask})
json.dump(results, open(f'/tmp/tsa/compare_{LABEL}.json', 'w'), indent=2)
print(f"saved /tmp/tsa/compare_{LABEL}.json")
