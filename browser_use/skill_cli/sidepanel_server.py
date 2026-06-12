"""Local HTTP bridge for the Browser Use Chrome side-panel extension."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from dotenv import load_dotenv

from browser_use.accounts.service import AccountService
from browser_use.assistant.research import BrowserResearchAssistant, ResearchAssistantConfig, render_report
from browser_use.browser import BrowserSession
from browser_use.skill_cli.credential_store import AutofillField, CredentialStore, ensure_credential_store

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765


@dataclass
class SidePanelServerConfig:
	host: str = DEFAULT_HOST
	port: int = DEFAULT_PORT
	model: str | None = None
	fallback_model: str | None = None
	cdp_url: str | None = None
	auto_discover_cdp: bool = True
	max_steps: int = 14
	max_recommendations: int = 3
	llm_timeout: int = 180
	credential_store_path: str | None = None
	accounts_file: str | None = None
	use_vision: bool = True


def _cors_response(data: dict[str, Any], status: int = 200) -> web.Response:
	return web.json_response(
		data,
		status=status,
		headers={
			'Access-Control-Allow-Origin': '*',
			'Access-Control-Allow-Headers': 'Content-Type',
			'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
		},
	)


def _page_context_prompt(page_context: dict[str, Any] | None) -> str:
	if not page_context:
		return ''

	title = str(page_context.get('title') or page_context.get('browserTitle') or '').strip()
	url = str(page_context.get('url') or page_context.get('browserUrl') or '').strip()
	text = str(page_context.get('text') or '').strip()
	links = page_context.get('links') or []
	link_lines: list[str] = []
	if isinstance(links, list):
		for item in links[:30]:
			if not isinstance(item, dict):
				continue
			label = str(item.get('text') or '').strip()
			href = str(item.get('href') or '').strip()
			if label or href:
				link_lines.append(f'- {label or href} | {href}')

	return (
		'\n\nCurrent browser page context supplied by the side-panel extension:\n'
		f'Title: {title or "unknown"}\n'
		f'URL: {url or "unknown"}\n'
		'Visible text excerpt:\n'
		f'{text[:12000] or "empty"}\n'
		'Visible links:\n'
		+ ('\n'.join(link_lines) if link_lines else 'none')
		+ '\n\nUse this current page context as an already-open source when it is relevant. '
		'If it is a verification, login, empty, or skeleton page, say so explicitly and continue with other allowed sources.'
	)


def _is_browser_action_task(task: str) -> bool:
	"""Return True for direct browser-control tasks that should run the Agent."""

	text = task.strip().lower()
	if re.search(r'https?://', text) and re.search(
		r'\b(go|open|visit|navigate|click|fill|type|login|log in|sign in|submit|solve|complete|download|upload)\b',
		text,
	):
		return True
	if re.search(
		r'\b(go to|open|visit|navigate to|click|fill|type|login|log in|sign in|submit|solve|complete|download|upload)\b',
		text,
	):
		return True
	if re.search(r'(打开|访问|进入|点击|填写|输入|登录|登陆|提交|完成|下载|上传|验证码)', task):
		return True
	return False


def _should_use_research_assistant(task: str, payload: dict[str, Any]) -> bool:
	"""Route side-panel requests to report mode only when they are research-like."""

	if payload.get('assistant_mode') == 'agent':
		return False
	if payload.get('assistant_mode') == 'research':
		return True
	if _is_browser_action_task(task):
		return False
	text = task.lower()
	if re.search(r'\b(recommend|compare|comparison|research|investigate|analyze|analysis|survey|best|buy|choose)\b', text):
		return True
	if re.search(r'(推荐|比较|对比|调研|研究|分析|总结|选购|购买|哪个好|哪款)', task):
		return True
	return False


class SidePanelServer:
	def __init__(self, config: SidePanelServerConfig):
		self.config = config
		self._discovered_cdp_url: str | None = None
		self.credential_store = CredentialStore(config.credential_store_path)
		# Initialize account service if accounts file is configured
		self.account_service: AccountService | None = None
		accounts_path = config.accounts_file or os.getenv('BROWSER_USE_ACCOUNTS_FILE')
		if accounts_path:
			self.account_service = AccountService(path=accounts_path)

	async def health(self, request: web.Request) -> web.Response:
		model = self.config.model or os.getenv('BROWSER_USE_LLM_MODEL') or os.getenv('DEFAULT_LLM') or 'auto'
		return _cors_response(
			{
				'ok': True,
				'model': model,
				'fallback_model': self.config.fallback_model,
				'cdp_url': self._resolve_cdp_url(),
				'use_vision': self.config.use_vision,
				'accounts_loaded': self.account_service is not None and len(self.account_service.get_all_accounts()) > 0,
			}
		)

	async def options(self, request: web.Request) -> web.Response:
		return _cors_response({})

	async def autofill_preview(self, request: web.Request) -> web.Response:
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			return _cors_response({'error': 'Invalid JSON body'}, status=400)

		url = str(payload.get('url') or '').strip()
		if not url:
			return _cors_response({'error': 'url is required'}, status=400)

		try:
			return _cors_response({'matches': self.credential_store.preview_matches(url)})
		except Exception as exc:
			return _cors_response({'error': str(exc)}, status=500)

	async def autofill_resolve(self, request: web.Request) -> web.Response:
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			return _cors_response({'error': 'Invalid JSON body'}, status=400)

		url = str(payload.get('url') or '').strip()
		if not url:
			return _cors_response({'error': 'url is required'}, status=400)

		profile_id = str(payload.get('profile_id') or '').strip() or None
		try:
			resolved = self.credential_store.resolve_values(url, profile_id=profile_id)
		except Exception as exc:
			return _cors_response({'error': str(exc)}, status=500)
		if not resolved:
			return _cors_response({'error': 'No matching autofill profile for this URL'}, status=404)
		return _cors_response({'profile': resolved})

	async def autofill_create(self, request: web.Request) -> web.Response:
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			return _cors_response({'error': 'Invalid JSON body'}, status=400)

		label = str(payload.get('label') or '').strip()
		url = str(payload.get('url') or '').strip()
		login_method = str(payload.get('login_method') or '').strip()
		if not label:
			return _cors_response({'error': 'label is required'}, status=400)
		if not url.lower().startswith(('http://', 'https://')):
			return _cors_response({'error': 'url must start with http:// or https://'}, status=400)
		if login_method not in {'password', 'phone'}:
			return _cors_response({'error': 'login_method must be "password" or "phone"'}, status=400)

		fields: list[AutofillField] = []
		if login_method == 'password':
			username = str(payload.get('username') or '').strip()
			password = str(payload.get('password') or '')
			if not username or not password:
				return _cors_response({'error': 'username and password are required'}, status=400)
			fields.extend(
				[
					AutofillField(
						name='username',
						value=username,
						field_type='username',
						aliases=['email', 'login', 'account', '账号', '用户名'],
					),
					AutofillField(
						name='password',
						value=password,
						field_type='password',
						aliases=['password', 'pwd', '密码'],
					),
				]
			)
		else:
			phone = str(payload.get('phone') or '').strip()
			if not phone:
				return _cors_response({'error': 'phone is required'}, status=400)
			fields.append(
				AutofillField(
					name='phone',
					value=phone,
					field_type='phone',
					aliases=['phone', 'mobile', 'tel', '手机号', '手机'],
				)
			)

		try:
			profile = self.credential_store.add_profile(label=label, url=url, fields=fields)
			preview = self.credential_store.preview_matches(url)
		except Exception as exc:
			return _cors_response({'error': str(exc)}, status=500)
		return _cors_response({'profile': profile.model_dump(mode='json'), 'matches': preview}, status=201)

	def _resolve_cdp_url(self, requested_cdp_url: str | None = None) -> str | None:
		if requested_cdp_url:
			return requested_cdp_url
		if self.config.cdp_url:
			return self.config.cdp_url
		env_cdp_url = os.getenv('BROWSER_USE_CDP_URL') or os.getenv('CDP_URL')
		if env_cdp_url:
			return env_cdp_url
		if not self.config.auto_discover_cdp:
			return None
		if self._discovered_cdp_url is not None:
			return self._discovered_cdp_url
		try:
			from browser_use.skill_cli.utils import discover_chrome_cdp_url

			self._discovered_cdp_url = discover_chrome_cdp_url()
		except RuntimeError:
			self._discovered_cdp_url = None
		return self._discovered_cdp_url

	async def _run_browser_agent(
		self,
		task: str,
		payload: dict[str, Any],
		cdp_url: str | None,
		use_vision: bool,
	) -> dict[str, Any]:
		from browser_use.agent.service import Agent
		from browser_use.assistant.research import resolve_llm

		llm = resolve_llm(str(payload.get('model') or self.config.model or '') or None)
		fallback_model = str(payload.get('fallback_model') or self.config.fallback_model or '') or None
		fallback_llm = resolve_llm(fallback_model) if fallback_model else None
		browser_kwargs: dict[str, Any] = {'enable_default_extensions': True}
		if cdp_url:
			browser_kwargs['cdp_url'] = cdp_url
		else:
			browser_kwargs['headless'] = False
		browser = BrowserSession(**browser_kwargs)
		agent = Agent(
			task=task,
			llm=llm,
			fallback_llm=fallback_llm,
			browser=browser,
			accounts_file=self.config.accounts_file or os.getenv('BROWSER_USE_ACCOUNTS_FILE'),
			use_vision='auto' if use_vision else False,
			llm_timeout=int(payload.get('llm_timeout') or self.config.llm_timeout),
			max_actions_per_step=3,
		)
		history = await agent.run(max_steps=int(payload.get('max_steps') or self.config.max_steps))
		return {
			'result': history.final_result() if history else '',
			'mode': 'agent',
			'is_done': history.is_done() if history else False,
			'is_successful': history.is_successful() if history else None,
			'visited_urls': history.urls() if history else [],
			'action_names': history.action_names() if history else [],
			'errors': [error for error in (history.errors() if history else []) if error],
			'cdp_url': cdp_url,
		}

	async def assistant(self, request: web.Request) -> web.Response:
		try:
			payload = await request.json()
		except json.JSONDecodeError:
			return _cors_response({'error': 'Invalid JSON body'}, status=400)

		task = str(payload.get('task') or '').strip()
		if not task:
			return _cors_response({'error': 'task is required'}, status=400)

		page_context = payload.get('page_context')
		if page_context is not None and not isinstance(page_context, dict):
			return _cors_response({'error': 'page_context must be an object'}, status=400)

		requested_cdp_url = str(payload.get('cdp_url') or '').strip() or None
		cdp_url = self._resolve_cdp_url(requested_cdp_url)

		# Determine use_vision: prefer request payload, then server config
		use_vision = payload.get('use_vision')
		if use_vision is None:
			use_vision = self.config.use_vision

		if not _should_use_research_assistant(task, payload):
			try:
				return _cors_response(await self._run_browser_agent(task, payload, cdp_url, bool(use_vision)))
			except Exception as exc:
				return _cors_response({'error': str(exc), 'mode': 'agent'}, status=500)

		enriched_task = task + _page_context_prompt(page_context)

		config = ResearchAssistantConfig(
			task=enriched_task,
			model=str(payload.get('model') or self.config.model or '') or None,
			fallback_model=str(payload.get('fallback_model') or self.config.fallback_model or '') or None,
			locale=payload.get('locale'),
			max_steps=int(payload.get('max_steps') or self.config.max_steps),
			max_recommendations=int(payload.get('max_recommendations') or self.config.max_recommendations),
			llm_timeout=int(payload.get('llm_timeout') or self.config.llm_timeout),
			use_vision=bool(use_vision),
			shopping_sites=list(payload.get('shopping_sites') or []),
			review_sites=list(payload.get('review_sites') or []),
			official_sites=list(payload.get('official_sites') or []),
			web_sites=list(payload.get('web_sites') or []),
		)

		try:
			assistant = BrowserResearchAssistant(config)
			if bool(payload.get('dry_run', False)):
				task_plan = await assistant._analyze_task()
				return _cors_response(
					{
						'result': 'dry_run',
						'task_plan': task_plan.model_dump(mode='json'),
						'stage_results': [],
						'candidate_catalog': [],
						'cdp_url': cdp_url,
					}
				)
			artifacts = await assistant.run(cdp_url=cdp_url)
		except Exception as exc:
			return _cors_response({'error': str(exc)}, status=500)

		return _cors_response(
			{
				'result': render_report(artifacts.report),
				'report': artifacts.report.model_dump(mode='json'),
				'task_plan': artifacts.task_plan.model_dump(mode='json'),
				'stage_results': [stage.model_dump(mode='json') for stage in artifacts.stage_results],
				'candidate_catalog': [candidate.model_dump(mode='json') for candidate in artifacts.candidate_catalog],
				'cdp_url': cdp_url,
			}
		)


def create_app(config: SidePanelServerConfig) -> web.Application:
	server = SidePanelServer(config)
	app = web.Application()
	app.router.add_get('/health', server.health)
	app.router.add_options('/health', server.options)
	app.router.add_post('/assistant', server.assistant)
	app.router.add_options('/assistant', server.options)
	app.router.add_post('/autofill/preview', server.autofill_preview)
	app.router.add_options('/autofill/preview', server.options)
	app.router.add_post('/autofill/resolve', server.autofill_resolve)
	app.router.add_options('/autofill/resolve', server.options)
	app.router.add_post('/autofill/create', server.autofill_create)
	app.router.add_options('/autofill/create', server.options)
	return app


async def run_server(config: SidePanelServerConfig) -> None:
	load_dotenv('.env')
	store_path = ensure_credential_store(config.credential_store_path)
	app = create_app(config)
	runner = web.AppRunner(app)
	await runner.setup()
	site = web.TCPSite(runner, config.host, config.port)
	await site.start()
	print(f'Browser Use side-panel bridge listening on http://{config.host}:{config.port}', flush=True)
	print(f'Autofill profile store: {store_path}', flush=True)
	try:
		await asyncio.Event().wait()
	finally:
		await runner.cleanup()


def main() -> None:
	parser = argparse.ArgumentParser(description='Run the Browser Use side-panel local bridge')
	parser.add_argument('--host', default=DEFAULT_HOST)
	parser.add_argument('--port', type=int, default=DEFAULT_PORT)
	parser.add_argument('--model', default=None)
	parser.add_argument(
		'--fallback-model', default=None, help='Fallback LLM used when the primary model errors (e.g. bad schema output)'
	)
	parser.add_argument('--cdp-url', default=None)
	parser.add_argument('--no-auto-cdp', action='store_true')
	parser.add_argument('--max-steps', type=int, default=14)
	parser.add_argument('--max-recommendations', type=int, default=3)
	parser.add_argument('--llm-timeout', type=int, default=180)
	parser.add_argument('--credential-store', default=None)
	parser.add_argument('--accounts-file', default=None, help='Path to accounts.json for credential management')
	parser.add_argument('--no-vision', action='store_true', help='Disable vision/screenshot mode')
	args = parser.parse_args()
	config = SidePanelServerConfig(
		host=args.host,
		port=args.port,
		model=args.model,
		fallback_model=args.fallback_model,
		cdp_url=args.cdp_url,
		auto_discover_cdp=not args.no_auto_cdp,
		max_steps=args.max_steps,
		max_recommendations=args.max_recommendations,
		llm_timeout=args.llm_timeout,
		credential_store_path=args.credential_store,
		accounts_file=args.accounts_file,
		use_vision=not args.no_vision,
	)
	asyncio.run(run_server(config))


if __name__ == '__main__':
	main()
