#!/usr/bin/env python3
"""Replay selected captured contexts against the server and dump the model's
thinking / next_goal / action. Run once per setting to compare (temperature,
top-k) on identical inputs.

Standalone: reads the bundled contexts in ./trajectories/ (no dependency on the
gitignored simulator/runs/). Needs the project env so `browser_use` imports
(see ../README.md). Server must be reachable at http://localhost:10000/v1.

Usage:  python replay_compare.py LABEL [TEMP=0.0] [NSAMP=1]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # <repo>/simulator/analysis/batched_decode_bug -> <repo>
sys.path.insert(0, REPO)  # fallback so `browser_use` resolves from source if not pip-installed
DATA = os.path.join(HERE, 'trajectories')

from openai import OpenAI
from pydantic import TypeAdapter
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openai.serializer import OpenAIMessageSerializer

_MSGS = TypeAdapter(list[BaseMessage])
LABEL = sys.argv[1] if len(sys.argv) > 1 else 'topk?'
TEMP = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
NSAMP = int(sys.argv[3]) if len(sys.argv) > 3 else 1
STEPS = [
	('webvoyager__Allrecipes--0', 'step_001'),
	('webvoyager__Allrecipes--0', 'step_003'),
	('webvoyager__Allrecipes--1', 'step_002'),
	('webvoyager__Allrecipes--2', 'step_001'),
]
client = OpenAI(base_url='http://localhost:10000/v1', api_key='EMPTY')
results = []
for task, step in STEPS:
	td = os.path.join(DATA, task)
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
		ontask = any(w in (ng + json.dumps(act)).lower() for w in ['lasagna', 'recipe', 'vegetarian', 'search'])
		print(f"   s{s} {'OK ' if ontask else 'OFF'} next_goal: {ng[:110]}")
		results.append({'task': task, 'step': step, 'temp': TEMP, 'sample': s, 'question': q,
		                'next_goal': ng, 'action': act, 'thinking': th, 'ontask': ontask})
json.dump(results, open(os.path.join(HERE, f'results/compare_{LABEL}.json'), 'w'), indent=2)
print(f"saved results/compare_{LABEL}.json")
