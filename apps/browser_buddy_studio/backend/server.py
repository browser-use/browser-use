from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from pydantic import BaseModel

from .config import ARTIFACT_DIR, LOG_DIR, PROFILE_DIR, frontend_dist, prepare_runtime

prepare_runtime()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from browser_use import Agent, Browser  # noqa: E402

from .artifacts import build_sources, collect_artifacts  # noqa: E402
from .providers import PROVIDERS, build_llm, get_saved_key, provider_list, save_key  # noqa: E402
from .storage import add_history, clear_history, load_history, load_preferences, save_preferences  # noqa: E402

logger = logging.getLogger('browser_buddy.server')
logger.setLevel(logging.INFO)
if not logger.handlers:
	handler = logging.FileHandler(LOG_DIR / 'studio.log', encoding='utf-8')
	handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
	logger.addHandler(handler)


class EventHub:
	def __init__(self) -> None:
		self._subscribers: set[asyncio.Queue] = set()

	def subscribe(self) -> asyncio.Queue:
		queue: asyncio.Queue = asyncio.Queue(maxsize=200)
		self._subscribers.add(queue)
		return queue

	def unsubscribe(self, queue: asyncio.Queue) -> None:
		self._subscribers.discard(queue)

	def publish(self, event: dict[str, Any]) -> None:
		for queue in list(self._subscribers):
			try:
				queue.put_nowait(event)
			except asyncio.QueueFull:
				self._subscribers.discard(queue)


HUB = EventHub()
CURRENT_TASK: asyncio.Task | None = None
CURRENT_AGENT: Agent | None = None
STOP_REQUESTED = False

STATE: dict[str, Any] = {
	'running': False,
	'task': '',
	'provider': '',
	'model': '',
	'steps': [],
	'result': None,
	'error': None,
	'started_at': None,
	'finished_at': None,
}


class RunRequest(BaseModel):
	task: str
	provider: str
	model: str
	api_key: str | None = None
	headless: bool = False
	max_steps: int = 50
	use_vision: bool = True


def _action_names(model_output) -> list[str]:
	names: list[str] = []
	for action in getattr(model_output, 'action', []) or []:
		data = action.model_dump(exclude_unset=True)
		names.append(next(iter(data), 'unknown'))
	return names


def _publish_and_store(event: dict[str, Any]) -> None:
	HUB.publish(event)


def _on_step(browser_state_summary, model_output, step: int) -> None:
	goal = getattr(model_output, 'next_goal', '') or ''
	event = {
		'type': 'step',
		'step': step,
		'goal': goal,
		'actions': _action_names(model_output),
		'ts': time.time(),
	}
	STATE['steps'].append(event)
	_publish_and_store(event)


async def _should_stop() -> bool:
	return STOP_REQUESTED


async def _run_agent(request: RunRequest) -> None:
	global CURRENT_AGENT, CURRENT_TASK, STOP_REQUESTED

	started_at = time.time()
	STOP_REQUESTED = False
	STATE.update(
		{
			'running': True,
			'task': request.task,
			'provider': request.provider,
			'model': request.model,
			'steps': [],
			'result': None,
			'error': None,
			'started_at': started_at,
			'finished_at': None,
		}
	)
	HUB.publish(
		{
			'type': 'run_started',
			'task': request.task,
			'provider': request.provider,
			'model': request.model,
			'started_at': started_at,
		}
	)

	try:
		key = (request.api_key or '').strip() or get_saved_key(request.provider)
		if not key:
			raise ValueError(f'缺少 {request.provider} API Key')
		if request.api_key:
			save_key(request.provider, request.api_key)

		llm = build_llm(request.provider, request.model, key)
		browser = Browser(headless=request.headless, user_data_dir=str(PROFILE_DIR))
		agent = Agent(
			task=request.task,
			llm=llm,
			browser=browser,
			use_vision=request.use_vision,
			auto_recovery=True,
			use_judge=False,
			register_new_step_callback=_on_step,
			register_should_stop_callback=_should_stop,
		)
		CURRENT_AGENT = agent

		history = await agent.run(max_steps=int(request.max_steps))
		text = history.final_result() or '任务完成，但模型没有返回文本结果。'
		sources = await build_sources(text, history.urls())
		files, images = collect_artifacts(history)
		success = history.is_successful()

		result = {
			'text': text,
			'sources': sources,
			'files': files,
			'images': images,
			'success': success,
			'duration': round(time.time() - started_at, 1),
			'steps': len(STATE['steps']),
		}
		STATE['result'] = result
		STATE['finished_at'] = time.time()
		HUB.publish({'type': 'result', **result})
	except Exception as e:
		logger.exception('Task failed')
		message = f'{type(e).__name__}: {e}'
		STATE['error'] = message
		STATE['finished_at'] = time.time()
		HUB.publish({'type': 'error', 'message': message})
	finally:
		STATE['running'] = False
		CURRENT_AGENT = None
		HUB.publish({'type': 'run_finished', 'duration': round(time.time() - started_at, 1)})
		if CURRENT_TASK is asyncio.current_task():
			CURRENT_TASK = None


app = FastAPI(title='BrowserBuddy Studio')


@app.get('/api/health')
async def health() -> dict[str, str]:
	return {'status': 'ok'}


@app.get('/api/providers')
async def providers() -> list[dict]:
	return provider_list()


@app.get('/api/state')
async def state() -> dict:
	return STATE


@app.get('/api/history')
async def history() -> list[dict]:
	return load_history()


@app.post('/api/history')
async def create_history(entry: dict) -> list[dict]:
	return add_history(entry)


@app.delete('/api/history')
async def delete_history() -> dict:
	clear_history()
	return {'ok': True}


@app.get('/api/preferences')
async def preferences() -> dict:
	return load_preferences()


@app.post('/api/preferences')
async def update_preferences(preferences: dict) -> dict:
	return save_preferences(preferences)


@app.post('/api/run')
async def run(request: RunRequest) -> dict:
	global CURRENT_TASK

	if request.provider not in PROVIDERS:
		raise HTTPException(status_code=400, detail=f'不支持的模型提供商: {request.provider}')
	if CURRENT_TASK is not None and not CURRENT_TASK.done():
		raise HTTPException(status_code=409, detail='已有任务正在执行')

	CURRENT_TASK = asyncio.create_task(_run_agent(request))
	return {'ok': True}


@app.post('/api/stop')
async def stop() -> dict:
	global STOP_REQUESTED

	STOP_REQUESTED = True
	if CURRENT_AGENT is not None:
		try:
			CURRENT_AGENT.stop()
		except Exception as e:
			logger.warning(f'Could not stop agent cleanly: {type(e).__name__}: {e}')
	HUB.publish({'type': 'stopping'})
	return {'ok': True}


@app.post('/api/open-logs')
async def open_logs() -> dict:
	LOG_DIR.mkdir(parents=True, exist_ok=True)
	await asyncio.create_subprocess_exec('open', str(LOG_DIR))
	return {'ok': True, 'path': str(LOG_DIR)}


@app.get('/api/events')
async def events() -> StreamingResponse:
	queue = HUB.subscribe()

	async def stream():
		try:
			while True:
				event = await queue.get()
				yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
		finally:
			HUB.unsubscribe(queue)

	return StreamingResponse(
		stream(),
		media_type='text/event-stream',
		headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
	)


app.mount('/artifacts', StaticFiles(directory=str(ARTIFACT_DIR)), name='artifacts')

FRONTEND_DIST = frontend_dist()
if FRONTEND_DIST.exists():
	app.mount('/', StaticFiles(directory=str(FRONTEND_DIST), html=True), name='frontend')
else:

	@app.get('/')
	async def missing_frontend() -> dict:
		return {'error': 'Frontend build not found. Run the frontend build first.'}
