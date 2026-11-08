from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import psutil
from pydantic import BaseModel

from .config import ARTIFACT_DIR, BROWSER_STATE_FILE, DOWNLOADS_DIR, LOG_DIR, PROFILE_DIR, frontend_dist, prepare_runtime

prepare_runtime()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from browser_use import Agent, Browser  # noqa: E402
from browser_use.agent.views import ActionResult  # noqa: E402
from browser_use.browser.events import NavigateToUrlEvent  # noqa: E402

from .artifacts import build_sources, collect_artifacts, repair_xhs_links  # noqa: E402
from .intent import chat_reply, needs_browser  # noqa: E402
from .providers import PROVIDERS, build_llm, get_saved_key, provider_list, save_key  # noqa: E402
from .search_tools import build_tools  # noqa: E402
from .storage import (  # noqa: E402
	add_history,
	clear_history,
	delete_chat,
	load_chats,
	load_history,
	load_preferences,
	save_chat,
	save_preferences,
)

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
CURRENT_BROWSER: Browser | None = None
STOP_REQUESTED = False
LOGIN_SESSION: Browser | None = None
LOGIN_SITE: str | None = None
LOGIN_PREPARE_TASK: asyncio.Task | None = None
LOGIN_WATCH_TASK: asyncio.Task | None = None
LOGIN_LOCK = asyncio.Lock()
VIEW_SESSION: Browser | None = None
VIEW_LOCK = asyncio.Lock()
HUMAN_STATE: dict[str, Any] = {'active': False, 'reason': '', 'cancelled': False, 'event': None}
LOGIN_URLS = {
	'taobao': ('淘宝', 'https://login.taobao.com/member/login.jhtml'),
	'jd': ('京东', 'https://passport.jd.com/new/login.aspx'),
	'xiaohongshu': ('小红书', 'https://www.xiaohongshu.com/login'),
	'douyin': ('抖音', 'https://www.douyin.com/'),
}

# Douyin's /login URL redirects to an SSO callback page with a missing-parameter error.
# Open the homepage instead and click the login button to show the QR-code dialog.
LOGIN_PREPARE_CLICKS = {'douyin'}

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
	search_engine: str = 'auto'
	previous_context: str | None = None


class LoginRequest(BaseModel):
	site: str


class OpenUrlRequest(BaseModel):
	url: str


def _cleanup_stale_browser_profile() -> None:
	"""Kill leftover BrowserBuddy Chrome processes and remove stale profile locks."""
	profile_marker = str(PROFILE_DIR)
	victims: list[psutil.Process] = []
	for proc in psutil.process_iter(['pid', 'cmdline']):
		try:
			cmdline = ' '.join(proc.info.get('cmdline') or [])
			if profile_marker in cmdline and 'Google Chrome' in cmdline:
				proc.terminate()
				victims.append(proc)
		except Exception:
			continue

	if victims:
		_, alive = psutil.wait_procs(victims, timeout=5)
		for proc in alive:
			try:
				proc.kill()
			except Exception:
				continue
		if alive:
			psutil.wait_procs(alive, timeout=2)

	for lock_name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
		try:
			(PROFILE_DIR / lock_name).unlink(missing_ok=True)
		except Exception:
			pass


def _allow_manual_close(browser: Browser) -> None:
	"""Let the user close the last BrowserBuddy window without watchdog tab recovery."""
	watchdog = getattr(browser, '_aboutblank_watchdog', None)
	if watchdog is not None:
		setattr(watchdog, '_stopping', True)

	manager = getattr(browser, 'session_manager', None)
	if manager is None or getattr(manager, '_bb_allow_manual_close', False):
		return

	original_recover = manager._recover_agent_focus

	async def recover_without_reopening(crashed_target_id: str) -> None:
		if not manager.get_all_page_targets():
			logger.info('Browser window closed by user; skipping automatic tab recovery')
			return
		await original_recover(crashed_target_id)

	manager._recover_agent_focus = recover_without_reopening
	manager._bb_allow_manual_close = True


def _browser_has_pages(browser: Browser | None) -> bool:
	if browser is None or not browser.is_cdp_connected:
		return False
	manager = getattr(browser, 'session_manager', None)
	if manager is None:
		return False
	try:
		return bool(manager.get_all_page_targets())
	except Exception:
		return False


def _contains_chinese(text: str) -> bool:
	return any('\u4e00' <= char <= '\u9fff' for char in text)


def _language_instruction(task: str) -> str:
	instruction = (
		'Always answer in the same language as the user task. '
		'If the task is written in Chinese, the final answer MUST be in Chinese; '
		'do not switch to English unless the user explicitly asks. '
		'Keep URLs, code, product names, and quoted page text in their original language when necessary.'
	)
	if _contains_chinese(task):
		instruction += ' The current task is in Chinese: write the final answer in Chinese.'
	return instruction


async def _request_human_help(reason: str) -> ActionResult:
	global STOP_REQUESTED

	event = asyncio.Event()
	HUMAN_STATE.update({'active': True, 'reason': reason, 'cancelled': False, 'event': event})
	HUB.publish({'type': 'needs_human', 'reason': reason})
	await event.wait()
	cancelled = bool(HUMAN_STATE.get('cancelled'))
	HUMAN_STATE.update({'active': False, 'event': None})
	HUB.publish({'type': 'human_resolved', 'cancelled': cancelled})
	if cancelled:
		STOP_REQUESTED = True
		return ActionResult(error='用户取消了人工协助')
	return ActionResult(extracted_content='用户已完成登录或验证，请继续执行任务。')


async def _prepare_login_page(site: str, browser: Browser) -> None:
	if site not in LOGIN_PREPARE_CLICKS:
		return
	try:
		for _ in range(40):
			try:
				page = await browser.must_get_current_page()
				result = await page.evaluate(
					"""() => {
						const clickable = Array.from(document.querySelectorAll('button, [role="button"], a'));
						const target = clickable.find((element) => (element.textContent || '').trim() === '登录');
						if (!target) return 'missing';
						target.click();
						return 'clicked';
					}"""
				)
			except Exception:
				await asyncio.sleep(0.5)
				continue
			if 'clicked' in str(result):
				return
			await asyncio.sleep(0.5)
		logger.info(f'No login button found for {site}; the profile may already be signed in')
	except asyncio.CancelledError:
		raise
	except Exception as e:
		logger.warning(f'Could not open login panel for {site}: {type(e).__name__}: {e}')


async def _close_login_browser(cancelled: bool = False) -> None:
	global LOGIN_SESSION, LOGIN_SITE, LOGIN_PREPARE_TASK, LOGIN_WATCH_TASK

	if LOGIN_PREPARE_TASK is not None and not LOGIN_PREPARE_TASK.done():
		LOGIN_PREPARE_TASK.cancel()
	LOGIN_PREPARE_TASK = None
	LOGIN_WATCH_TASK = None
	browser = LOGIN_SESSION
	LOGIN_SESSION = None
	LOGIN_SITE = None
	if browser is not None:
		alive = _browser_has_pages(browser)
		if alive and not cancelled:
			try:
				await browser.export_storage_state(BROWSER_STATE_FILE)
			except Exception as e:
				logger.warning(f'Could not export login storage state: {type(e).__name__}: {e}')
		if alive:
			try:
				await asyncio.wait_for(browser.kill(), timeout=10)
			except Exception as e:
				logger.warning(f'Could not close login browser: {type(e).__name__}: {e}')
				await asyncio.to_thread(_cleanup_stale_browser_profile)
		else:
			await asyncio.to_thread(_cleanup_stale_browser_profile)
	HUB.publish({'type': 'login_finished', 'cancelled': cancelled})


async def _watch_login_browser(browser: Browser) -> None:
	"""Publish login_finished when the user closes the login browser manually."""
	try:
		while LOGIN_SESSION is browser:
			await asyncio.sleep(1)
			if LOGIN_SESSION is not browser:
				return
			if _browser_has_pages(browser):
				continue
			await asyncio.sleep(1)
			if LOGIN_SESSION is browser and not _browser_has_pages(browser):
				logger.info('Login browser was closed by the user')
				await _close_login_browser(cancelled=True)
				return
	except asyncio.CancelledError:
		raise
	except Exception as e:
		logger.warning(f'Login browser watcher failed: {type(e).__name__}: {e}')


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
	global CURRENT_AGENT, CURRENT_BROWSER, CURRENT_TASK, STOP_REQUESTED

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

		if not await needs_browser(request.task, llm, request.previous_context):
			reply = await chat_reply(llm, request.task, request.previous_context)
			result = {
				'text': reply,
				'sources': [],
				'files': [],
				'images': [],
				'success': True,
				'duration': round(time.time() - started_at, 1),
				'steps': 0,
				'mode': 'chat',
			}
			STATE['result'] = result
			STATE['finished_at'] = time.time()
			HUB.publish({'type': 'result', **result})
			return

		agent_task = request.task
		if request.previous_context:
			agent_task = (
				'以下是上一次任务的结果，请把它作为上下文继续使用。\n\n'
				f'{request.previous_context[:12000]}\n\n'
				f'本次任务：{request.task}'
			)
		await asyncio.to_thread(_cleanup_stale_browser_profile)
		await asyncio.sleep(0.3)
		browser = Browser(
			headless=request.headless,
			user_data_dir=str(PROFILE_DIR),
			storage_state=str(BROWSER_STATE_FILE),
			downloads_path=str(DOWNLOADS_DIR),
			keep_alive=False,
		)
		CURRENT_BROWSER = browser
		tools = build_tools(request.search_engine)

		@tools.action(
			'Ask the user to complete a human action such as login, QR code scan, CAPTCHA, SMS verification, '
			'or payment confirmation. Use this instead of guessing or entering credentials. '
			'The app pauses the task and shows a prompt; after the user clicks continue, the task resumes.'
		)
		async def request_human_help(reason: str) -> ActionResult:
			if request.headless:
				return ActionResult(error='当前是后台运行模式，无法进行人工登录。请先取消任务，在设置中关闭后台运行后重试。')
			return await _request_human_help(reason)

		agent = Agent(
			task=agent_task,
			llm=llm,
			browser=browser,
			tools=tools,
			use_vision=request.use_vision,
			auto_recovery=True,
			use_judge=False,
			extend_system_message=(
				'For web searches, use the `web_search` action instead of navigating directly to a search engine URL. '
				'The app selects a working search engine and handles regional fallbacks. '
				'When the task asks to search on a specific site such as 小红书, 抖音, 淘宝, or 京东, '
				'navigate to that site directly and search inside it instead of using `web_search`. '
				'When returning 小红书 results, open each note from the search results and copy the full URL shown in the '
				'address bar. That URL must keep its `xsec_token` and `xsec_source` query parameters '
				'(for example https://www.xiaohongshu.com/search_result/<id>?xsec_token=...&xsec_source=pc_search). '
				'Never return a bare https://www.xiaohongshu.com/explore/<id> URL or strip its query string: '
				'those links show 404 or a mobile QR login wall on desktop. '
				'When returning 抖音 results, use the canonical video URL https://www.douyin.com/video/<video_id> '
				'instead of a short link or the homepage. '
				'If the page requires login, QR code scan, CAPTCHA, SMS verification, or another human action, '
				'call `request_human_help` with a short Chinese reason instead of guessing or entering credentials. '
				+ _language_instruction(request.task)
			),
			register_new_step_callback=_on_step,
			register_should_stop_callback=_should_stop,
		)
		CURRENT_AGENT = agent

		history = await agent.run(max_steps=int(request.max_steps))
		text = history.final_result() or '任务完成，但模型没有返回文本结果。'
		text = repair_xhs_links(text, history.urls())
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
	except asyncio.CancelledError:
		STATE['error'] = '任务已停止'
		STATE['finished_at'] = time.time()
		HUB.publish({'type': 'stopped'})
		raise
	except Exception as e:
		logger.exception('Task failed')
		message = f'{type(e).__name__}: {e}'
		STATE['error'] = message
		STATE['finished_at'] = time.time()
		HUB.publish({'type': 'error', 'message': message})
	finally:
		STATE['running'] = False
		CURRENT_AGENT = None
		if CURRENT_BROWSER is not None:
			try:
				await CURRENT_BROWSER.kill()
			except Exception:
				pass
			CURRENT_BROWSER = None
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
	if LOGIN_SESSION is not None and not _browser_has_pages(LOGIN_SESSION):
		await _close_login_browser(cancelled=True)
	return {
		**STATE,
		'login_active': LOGIN_SESSION is not None,
		'login_site': LOGIN_SITE,
		'human_active': bool(HUMAN_STATE.get('active')),
		'human_reason': HUMAN_STATE.get('reason') or '',
	}


@app.post('/api/login/start')
async def login_start(request: LoginRequest) -> dict:
	global LOGIN_PREPARE_TASK, LOGIN_SESSION, LOGIN_SITE, LOGIN_WATCH_TASK

	if request.site not in LOGIN_URLS:
		raise HTTPException(status_code=400, detail='不支持的登录站点')
	if CURRENT_TASK is not None and not CURRENT_TASK.done():
		raise HTTPException(status_code=409, detail='请先等待当前任务结束')

	async with LOGIN_LOCK:
		if LOGIN_SESSION is not None:
			if _browser_has_pages(LOGIN_SESSION) and LOGIN_SITE == request.site:
				label, _ = LOGIN_URLS.get(LOGIN_SITE or '', ('登录', ''))
				return {'ok': True, 'label': label, 'site': request.site, 'already_open': True}
			# The user closed the previous login window, or chose another platform.
			await _close_login_browser(cancelled=True)

		await asyncio.to_thread(_cleanup_stale_browser_profile)
		await asyncio.sleep(0.3)
		label, url = LOGIN_URLS[request.site]
		browser = Browser(
			headless=False,
			user_data_dir=str(PROFILE_DIR),
			storage_state=str(BROWSER_STATE_FILE),
			downloads_path=str(DOWNLOADS_DIR),
			keep_alive=True,
		)
		try:
			await asyncio.wait_for(browser.start(), timeout=30)
			_allow_manual_close(browser)
			event = browser.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))
			await event
			await asyncio.wait_for(event.event_result(raise_if_any=True, raise_if_none=False), timeout=20)
			LOGIN_PREPARE_TASK = asyncio.create_task(_prepare_login_page(request.site, browser))
		except asyncio.TimeoutError as e:
			try:
				await asyncio.wait_for(browser.kill(), timeout=10)
			except Exception:
				await asyncio.to_thread(_cleanup_stale_browser_profile)
			raise HTTPException(
				status_code=500,
				detail='打开登录窗口超时，请重试；如果反复失败，请确认 Mac 上已安装 Google Chrome。',
			) from e
		except Exception as e:
			try:
				await asyncio.wait_for(browser.kill(), timeout=10)
			except Exception:
				await asyncio.to_thread(_cleanup_stale_browser_profile)
			raise HTTPException(status_code=500, detail=f'打开登录页失败: {type(e).__name__}: {e}') from e

		LOGIN_SESSION = browser
		LOGIN_SITE = request.site
		LOGIN_WATCH_TASK = asyncio.create_task(_watch_login_browser(browser))
		HUB.publish({'type': 'login_started', 'site': request.site, 'label': label})
		return {'ok': True, 'label': label, 'site': request.site}


@app.post('/api/login/finish')
async def login_finish() -> dict:
	await _close_login_browser(cancelled=False)
	return {'ok': True}


@app.post('/api/login/cancel')
async def login_cancel() -> dict:
	await _close_login_browser(cancelled=True)
	return {'ok': True}


async def _navigate_view_browser(browser: Browser, url: str) -> None:
	page = await browser.must_get_current_page()
	await page.goto(url)


async def _discard_view_browser() -> None:
	global VIEW_SESSION

	browser = VIEW_SESSION
	VIEW_SESSION = None
	if browser is None:
		return

	manager = getattr(browser, 'session_manager', None)
	has_pages = bool(manager.get_all_page_targets()) if manager is not None else False
	if not browser.is_cdp_connected or not has_pages:
		await asyncio.to_thread(_cleanup_stale_browser_profile)
		return

	try:
		await asyncio.wait_for(browser.kill(), timeout=10)
	except Exception as e:
		logger.warning(f'Could not close source browser: {type(e).__name__}: {e}')
		await asyncio.to_thread(_cleanup_stale_browser_profile)


@app.post('/api/open-url')
async def open_url(request: OpenUrlRequest) -> dict:
	"""Open a source link in the app's logged-in browser profile."""
	global VIEW_SESSION

	url = request.url.strip()
	parsed = urlparse(url)
	if parsed.scheme not in ('http', 'https') or not parsed.netloc:
		raise HTTPException(status_code=400, detail='仅支持 http 或 https 链接')
	if CURRENT_TASK is not None and not CURRENT_TASK.done():
		raise HTTPException(status_code=409, detail='任务运行中，请等任务结束后再打开来源链接')
	if LOGIN_SESSION is not None:
		raise HTTPException(status_code=409, detail='请先完成或关闭登录窗口')

	async with VIEW_LOCK:
		if VIEW_SESSION is not None:
			manager = getattr(VIEW_SESSION, 'session_manager', None)
			has_pages = bool(manager.get_all_page_targets()) if manager is not None else False
			if not VIEW_SESSION.is_cdp_connected or not has_pages:
				await _discard_view_browser()
			else:
				try:
					await asyncio.wait_for(_navigate_view_browser(VIEW_SESSION, url), timeout=60)
					return {'ok': True}
				except Exception as e:
					logger.warning(f'Could not reuse source browser: {type(e).__name__}: {e}')
					await _discard_view_browser()

		await asyncio.to_thread(_cleanup_stale_browser_profile)
		await asyncio.sleep(0.3)
		browser = Browser(
			headless=False,
			user_data_dir=str(PROFILE_DIR),
			storage_state=str(BROWSER_STATE_FILE),
			downloads_path=str(DOWNLOADS_DIR),
			keep_alive=True,
		)
		try:
			await browser.start()
			_allow_manual_close(browser)
			await _navigate_view_browser(browser, url)
		except Exception as e:
			try:
				await browser.kill()
			except Exception:
				pass
			raise HTTPException(status_code=500, detail=f'打开来源链接失败: {type(e).__name__}: {e}') from e

		VIEW_SESSION = browser
		return {'ok': True}


@app.post('/api/human/continue')
async def human_continue() -> dict:
	event = HUMAN_STATE.get('event')
	if isinstance(event, asyncio.Event):
		HUMAN_STATE['cancelled'] = False
		event.set()
	return {'ok': True}


@app.post('/api/human/cancel')
async def human_cancel() -> dict:
	event = HUMAN_STATE.get('event')
	if isinstance(event, asyncio.Event):
		HUMAN_STATE['cancelled'] = True
		event.set()
	return {'ok': True}


@app.get('/api/chats')
async def chats() -> list[dict]:
	return load_chats()


@app.post('/api/chats')
async def create_chat(thread: dict) -> list[dict]:
	return save_chat(thread)


@app.delete('/api/chats/{thread_id}')
async def remove_chat(thread_id: str) -> dict:
	delete_chat(thread_id)
	return {'ok': True}


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
	if LOGIN_SESSION is not None:
		raise HTTPException(status_code=409, detail='请先完成登录或取消登录')
	if CURRENT_TASK is not None and not CURRENT_TASK.done():
		raise HTTPException(status_code=409, detail='已有任务正在执行')

	CURRENT_TASK = asyncio.create_task(_run_agent(request))
	return {'ok': True}


@app.post('/api/stop')
async def stop() -> dict:
	global CURRENT_TASK, STOP_REQUESTED

	STOP_REQUESTED = True
	if CURRENT_TASK is not None and not CURRENT_TASK.done():
		CURRENT_TASK.cancel()
	human_event = HUMAN_STATE.get('event')
	if isinstance(human_event, asyncio.Event):
		HUMAN_STATE['cancelled'] = True
		human_event.set()
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


@app.post('/api/open-downloads')
async def open_downloads() -> dict:
	DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
	await asyncio.create_subprocess_exec('open', str(DOWNLOADS_DIR))
	return {'ok': True, 'path': str(DOWNLOADS_DIR)}


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
