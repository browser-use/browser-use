from browser_use.assistant.research import (
	AssistantMode,
	AssistantReport,
	BrowserResearchAssistant,
	CandidateCatalogEntry,
	CandidateEvidence,
	EvidenceSource,
	GeneratedStageSpec,
	ResearchAssistantConfig,
	SourceType,
	StageResult,
	_apply_report_confidence,
	_apply_recommendation_metadata,
	_normalize_report_sources,
	build_rtings_direct_urls,
	build_soundguys_direct_urls,
	build_sspai_direct_urls,
	build_tomsguide_direct_urls,
	build_ifanr_direct_urls,
	build_docs_direct_urls,
	build_github_repo_direct_urls,
	build_bing_rss_search_url,
	build_candidate_catalog,
	build_source_entry_urls,
	build_stage_prompt,
	adapt_query_for_source,
	_normalize_recommendations_to_shortlist,
	extract_bing_rss_results,
	extract_ifanr_api_candidate_urls,
	extract_review_candidates,
	extract_site_candidate_urls,
	extract_shopping_candidates,
	fallback_task_plan,
	get_site_adapter,
	plain_text_excerpt,
	render_report,
	infer_locale,
	infer_mode,
	rank_candidate_catalog,
	resolve_llm,
	RankedCandidate,
	SuggestedOption,
	_ifanr_review_candidate_matches_query,
	_review_candidate_matches_query,
	_source_priority_key,
	_normalize_generated_stages,
	_normalize_stage_sources,
	_requires_browser_observation,
	_stage_use_vision,
	_query_budget_limit,
	_valid_sources,
)
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.skill_cli.credential_store import CredentialStore, ensure_credential_store
from browser_use.skill_cli.main import build_parser
from browser_use.skill_cli.sidepanel_server import SidePanelServer, SidePanelServerConfig

import asyncio
import json
from pathlib import Path


def test_assistant_command_parsing():
	parser = build_parser()
	args = parser.parse_args(
		[
			'assistant',
			'\u5e2e\u6211\u63a8\u8350\u4e00\u6b3e1000\u4ee5\u5185\u7684\u8033\u673a',
			'--model',
			'openai_gpt_5_4',
			'--locale',
			'zh-CN',
			'--shopping-site',
			'jd.com',
			'--review-site',
			'smzdm.com',
			'--web-site',
			'docs.browser-use.com',
		]
	)
	assert args.command == 'assistant'
	assert args.task == '\u5e2e\u6211\u63a8\u8350\u4e00\u6b3e1000\u4ee5\u5185\u7684\u8033\u673a'
	assert args.model == 'openai_gpt_5_4'
	assert args.locale == 'zh-CN'
	assert args.shopping_sites == ['jd.com']
	assert args.review_sites == ['smzdm.com']
	assert args.web_sites == ['docs.browser-use.com']


def test_sidepanel_server_command_parsing():
	parser = build_parser()
	args = parser.parse_args(
		[
			'sidepanel-server',
			'--model',
			'gpt-5.4',
			'--port',
			'8766',
			'--cdp-url',
			'http://localhost:9222',
			'--credential-store',
			'profiles.json',
		]
	)
	assert args.command == 'sidepanel-server'
	assert args.model == 'gpt-5.4'
	assert args.port == 8766
	assert args.cdp_url == 'http://localhost:9222'
	assert args.credential_store == 'profiles.json'


def test_sidepanel_extension_manifest_and_static_files():
	extension_dir = Path('extensions/browser-use-sidebar')
	manifest = json.loads((extension_dir / 'manifest.json').read_text(encoding='utf-8'))
	sidepanel_js = (extension_dir / 'sidepanel.js').read_text(encoding='utf-8')
	sidepanel_html = (extension_dir / 'sidepanel.html').read_text(encoding='utf-8')

	assert manifest['manifest_version'] == 3
	assert manifest['side_panel']['default_path'] == 'sidepanel.html'
	assert 'sidePanel' in manifest['permissions']
	assert 'http://127.0.0.1:8765/*' in manifest['host_permissions']
	assert 'chrome.tabs.onActivated.addListener' in sidepanel_js
	assert 'chrome.tabs.onUpdated.addListener' in sidepanel_js
	assert '/autofill/preview' in sidepanel_js
	assert '/autofill/resolve' in sidepanel_js
	assert 'Autofill current page' in sidepanel_html
	assert 'Auto observe' in sidepanel_html


def test_credential_store_creates_empty_file(tmp_path):
	store_path = tmp_path / 'profiles.json'
	created_path = ensure_credential_store(store_path)
	assert created_path == store_path
	data = json.loads(store_path.read_text(encoding='utf-8'))
	assert data == {'version': 1, 'profiles': []}


def test_credential_store_matches_url_and_masks_sensitive_preview(tmp_path):
	store_path = tmp_path / 'profiles.json'
	store_path.write_text(
		json.dumps(
			{
				'version': 1,
				'profiles': [
					{
						'id': 'jd',
						'label': 'JD Account',
						'domains': ['jd.com'],
						'fields': [
							{'name': 'username', 'value': 'alice', 'field_type': 'username'},
							{'name': 'password', 'value': 'secret', 'field_type': 'password'},
						],
					}
				],
			}
		),
		encoding='utf-8',
	)

	store = CredentialStore(store_path)
	preview = store.preview_matches('https://passport.jd.com/new/login.aspx')
	assert preview[0]['label'] == 'JD Account'
	assert preview[0]['fields'][1]['masked'] is True
	assert 'value' not in preview[0]['fields'][1]
	resolved = store.resolve_values('https://passport.jd.com/new/login.aspx')
	assert resolved['fields'][1]['value'] == 'secret'


def test_sidepanel_server_health_and_bad_request(tmp_path):
	class EmptyJsonRequest:
		async def json(self):
			return {}

	async def run_checks():
		server = SidePanelServer(
			SidePanelServerConfig(model='gpt-5.4', cdp_url='http://localhost:9222', credential_store_path=str(tmp_path / 'profiles.json'))
		)
		health = await server.health(None)
		assert health.status == 200
		assert json.loads(health.text) == {'ok': True, 'model': 'gpt-5.4', 'cdp_url': 'http://localhost:9222'}

		bad_request = await server.assistant(EmptyJsonRequest())
		assert bad_request.status == 400
		assert json.loads(bad_request.text)['error'] == 'task is required'

	asyncio.run(run_checks())


def test_sidepanel_server_autofill_preview_and_resolve(tmp_path):
	store_path = tmp_path / 'profiles.json'
	store_path.write_text(
		json.dumps(
			{
				'version': 1,
				'profiles': [
					{
						'id': 'example',
						'label': 'Example Account',
						'urls': ['https://example.com/login*'],
						'fields': [
							{'name': 'username', 'value': 'demo', 'field_type': 'username'},
							{'name': 'password', 'value': 'secret', 'field_type': 'password'},
						],
					}
				],
			}
		),
		encoding='utf-8',
	)

	class PreviewRequest:
		async def json(self):
			return {'url': 'https://example.com/login?next=home'}

	class ResolveRequest:
		async def json(self):
			return {'url': 'https://example.com/login?next=home', 'profile_id': 'example'}

	async def run_checks():
		server = SidePanelServer(SidePanelServerConfig(credential_store_path=str(store_path)))
		preview_response = await server.autofill_preview(PreviewRequest())
		preview = json.loads(preview_response.text)
		assert preview_response.status == 200
		assert preview['matches'][0]['label'] == 'Example Account'
		assert 'value' not in preview['matches'][0]['fields'][1]

		resolve_response = await server.autofill_resolve(ResolveRequest())
		resolved = json.loads(resolve_response.text)
		assert resolve_response.status == 200
		assert resolved['profile']['fields'][1]['value'] == 'secret'

	asyncio.run(run_checks())


def test_sidepanel_server_passes_cdp_url_to_assistant(monkeypatch):
	class JsonRequest:
		async def json(self):
			return {'task': 'recommend headphones under 1000 RMB', 'page_context': {'title': 'JD', 'url': 'https://search.jd.com'}}

	class FakeModel:
		def model_dump(self, mode='json'):
			return {}

	class FakeArtifacts:
		report = FakeModel()
		task_plan = FakeModel()
		stage_results = []
		candidate_catalog = []

	class FakeAssistant:
		def __init__(self, config):
			self.config = config

		async def run(self, cdp_url=None):
			captured['cdp_url'] = cdp_url
			return FakeArtifacts()

	captured = {}
	monkeypatch.setattr('browser_use.skill_cli.sidepanel_server.BrowserResearchAssistant', FakeAssistant)
	monkeypatch.setattr('browser_use.skill_cli.sidepanel_server.render_report', lambda report: 'ok')

	async def run_check():
		server = SidePanelServer(SidePanelServerConfig(model='gpt-5.4', cdp_url='http://localhost:9222'))
		response = await server.assistant(JsonRequest())
		assert response.status == 200
		assert json.loads(response.text)['cdp_url'] == 'http://localhost:9222'
		assert captured['cdp_url'] == 'http://localhost:9222'

	asyncio.run(run_check())


def test_sidepanel_server_preserves_chinese_task_and_page_context(monkeypatch):
	task = '帮我推荐一款1000元以下的头戴式耳机'

	class JsonRequest:
		async def json(self):
			return {
				'task': task,
				'page_context': {
					'title': '京东耳机搜索',
					'url': 'https://search.jd.com/Search?keyword=头戴式耳机',
					'text': '当前页面包含飞利浦、索尼、漫步者等耳机商品卡片。',
					'links': [{'text': '飞利浦耳机', 'href': 'https://item.jd.com/example.html'}],
				},
				'locale': 'zh-CN',
			}

	class FakeModel:
		def model_dump(self, mode='json'):
			return {}

	class FakeArtifacts:
		report = FakeModel()
		task_plan = FakeModel()
		stage_results = []
		candidate_catalog = []

	class FakeAssistant:
		def __init__(self, config):
			captured['task'] = config.task
			captured['locale'] = config.locale

		async def run(self, cdp_url=None):
			return FakeArtifacts()

	captured = {}
	monkeypatch.setattr('browser_use.skill_cli.sidepanel_server.BrowserResearchAssistant', FakeAssistant)
	monkeypatch.setattr('browser_use.skill_cli.sidepanel_server.render_report', lambda report: 'ok')

	async def run_check():
		server = SidePanelServer(SidePanelServerConfig(model='gpt-5.4', cdp_url='http://localhost:9222'))
		response = await server.assistant(JsonRequest())
		assert response.status == 200
		assert captured['locale'] == 'zh-CN'
		assert task in captured['task']
		assert '京东耳机搜索' in captured['task']
		assert '当前页面包含飞利浦、索尼、漫步者等耳机商品卡片。' in captured['task']
		assert 'https://item.jd.com/example.html' in captured['task']

	asyncio.run(run_check())


def test_sidepanel_server_dry_run_returns_chinese_task_plan(monkeypatch):
	task = '帮我推荐一款1000元以下的头戴式耳机'

	class JsonRequest:
		async def json(self):
			return {
				'task': task,
				'locale': 'zh-CN',
				'dry_run': True,
				'page_context': {
					'title': '京东耳机搜索',
					'url': 'https://search.jd.com/Search?keyword=头戴式耳机',
					'text': '当前页面有多个1000元以内的头戴式耳机商品卡片。',
					'links': [],
				},
			}

	class FakeAssistant:
		def __init__(self, config):
			self.config = config

		async def _analyze_task(self):
			return fallback_task_plan(
				ResearchAssistantConfig(
					task=self.config.task,
					locale=self.config.locale,
					shopping_sites=self.config.shopping_sites,
					review_sites=self.config.review_sites,
				)
			)

	monkeypatch.setattr('browser_use.skill_cli.sidepanel_server.BrowserResearchAssistant', FakeAssistant)

	async def run_check():
		server = SidePanelServer(SidePanelServerConfig(model='gpt-5.4', cdp_url='http://localhost:9222'))
		response = await server.assistant(JsonRequest())
		assert response.status == 200
		payload = json.loads(response.text)
		assert payload['result'] == 'dry_run'
		assert payload['cdp_url'] == 'http://localhost:9222'
		assert payload['task_plan']['mode'] == 'recommendation'
		assert payload['task_plan']['locale'] == 'zh-CN'
		assert task in payload['task_plan']['user_task']
		assert {'jd.com', 'tmall.com', 'taobao.com'}.issubset(set(payload['task_plan']['shopping_sources']))

	asyncio.run(run_check())


def test_assistant_mode_and_locale_inference():
	assert infer_mode('\u5e2e\u6211\u63a8\u8350\u4e00\u6b3e1000\u4ee5\u5185\u7684\u8033\u673a') == AssistantMode.recommendation
	assert infer_mode('compare iphone 15 vs iphone 16') == AssistantMode.comparison
	assert infer_locale('\u5e2e\u6211\u63a8\u8350\u4e00\u6b3e1000\u4ee5\u5185\u7684\u8033\u673a') == 'zh-CN'
	assert infer_locale('recommend earbuds under $150') == 'en-US'


def test_fallback_task_plan_uses_user_sites():
	config = ResearchAssistantConfig(task='recommend headphones under 150 dollars', shopping_sites=['bestbuy.com'])
	plan = fallback_task_plan(config)
	assert plan.shopping_sources[0] == 'bestbuy.com'
	assert plan.review_sources
	assert plan.shopping_queries
	assert plan.web_sources == []


def test_fallback_task_plan_preserves_cny_budget_text():
	config = ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机')
	plan = fallback_task_plan(config)
	assert plan.locale == 'zh-CN'
	assert plan.budget == '1000元以下'
	assert plan.shopping_sources[:3] == ['jd.com', 'tmall.com', 'taobao.com']
	assert plan.review_sources[:5] == ['sspai.com', 'ifanr.com', 'zol.com.cn', 'zhihu.com', 'bilibili.com']
	assert 'rtings.com' in plan.review_sources


def test_analyze_task_fallback_preserves_chinese_domestic_sources():
	class FailingLLM:
		async def ainvoke(self, messages, output_format=None):
			raise ValueError('analysis failed')

	assistant = BrowserResearchAssistant(
		ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机，注重均衡声音和佩戴舒适度'),
		llm=FailingLLM(),
	)
	plan = asyncio.run(assistant._analyze_task())
	assert plan.locale == 'zh-CN'
	assert plan.shopping_sources[:3] == ['jd.com', 'tmall.com', 'taobao.com']
	assert plan.review_sources[:3] == ['sspai.com', 'ifanr.com', 'zol.com.cn']


def test_analyze_task_restores_recommendation_when_llm_misclassifies_chinese_task():
	class Response:
		completion = None

	class MisclassifyingLLM:
		async def ainvoke(self, messages, output_format=None):
			response = Response()
			response.completion = fallback_task_plan(ResearchAssistantConfig(task='Investigate a vague topic'))
			response.completion.user_task = 'Investigate a vague topic'
			response.completion.mode = AssistantMode.generic
			response.completion.locale = 'zh-CN'
			response.completion.shopping_sources = []
			response.completion.review_sources = []
			response.completion.web_sources = ['bing.com']
			return response

	assistant = BrowserResearchAssistant(
		ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机，注重均衡声音和佩戴舒适度'),
		llm=MisclassifyingLLM(),
	)
	plan = asyncio.run(assistant._analyze_task())
	assert plan.mode == AssistantMode.recommendation
	assert {'jd.com', 'tmall.com', 'taobao.com'}.issubset(set(plan.shopping_sources))
	assert {'sspai.com', 'ifanr.com', 'zol.com.cn'}.issubset(set(plan.review_sources))
	assert sorted(plan.shopping_sources, key=lambda item: _source_priority_key(SourceType.shopping, item, plan.locale))[:3] == [
		'jd.com',
		'tmall.com',
		'taobao.com',
	]
	assert plan.web_sources == []
	assert 'Concrete recommendations' in plan.required_deliverables


def test_analyze_task_preserves_model_generated_stages():
	class Response:
		completion = None

	class StageGeneratingLLM:
		async def ainvoke(self, messages, output_format=None):
			response = Response()
			response.completion = fallback_task_plan(ResearchAssistantConfig(task='Recommend headphones under 1000 yuan'))
			response.completion.locale = 'zh-CN'
			response.completion.generated_stages = [
				GeneratedStageSpec(
					source_type=SourceType.review,
					source='zhihu.com',
					queries=['1000元以下 头戴式耳机 知乎 佩戴舒适'],
					purpose='Check community sentiment.',
				),
				GeneratedStageSpec(
					source_type=SourceType.web,
					source='not a source',
					queries=['bad'],
				),
			]
			return response

	assistant = BrowserResearchAssistant(
		ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机，并参考知乎口碑'),
		llm=StageGeneratingLLM(),
	)
	plan = asyncio.run(assistant._analyze_task())
	assert plan.mode == AssistantMode.recommendation
	assert any(stage.source == 'zhihu.com' for stage in plan.generated_stages)
	assert all(stage.source != 'not a source' for stage in plan.generated_stages)
	assert {'jd.com', 'tmall.com', 'taobao.com'}.issubset(set(plan.shopping_sources))


def test_fallback_task_plan_for_generic_research_prefers_web_sources():
	config = ResearchAssistantConfig(task='Investigate whether browser-use supports OpenAI-compatible APIs')
	plan = fallback_task_plan(config)
	assert plan.mode == AssistantMode.research
	assert plan.web_sources == ['bing.com']
	assert plan.shopping_sources == []
	assert plan.review_sources == []
	assert 'Clear summary of findings' in plan.required_deliverables


def test_fallback_task_plan_extracts_explicit_urls_and_domains_for_web_stage():
	config = ResearchAssistantConfig(task='Check https://docs.browser-use.com and github.com/browser-use/browser-use for OpenAI compatibility details')
	plan = fallback_task_plan(config)
	assert 'https://docs.browser-use.com' in plan.web_sources
	assert 'github.com' in plan.web_sources
	assert 'bing.com' not in plan.web_sources


def test_fallback_task_plan_infers_github_domain_from_repo_wording():
	config = ResearchAssistantConfig(task='Investigate the browser-use GitHub repo for OpenAI compatibility notes')
	plan = fallback_task_plan(config)
	assert 'https://github.com/browser-use/browser-use' in plan.web_sources


def test_fallback_task_plan_dedupes_domain_when_explicit_url_exists():
	config = ResearchAssistantConfig(task='Check https://docs.browser-use.com for setup details')
	plan = fallback_task_plan(config)
	assert plan.web_sources == ['https://docs.browser-use.com']


def test_fallback_task_plan_infers_repo_url_from_docs_slug_and_github_repo_wording():
	config = ResearchAssistantConfig(task='Investigate whether browser-use supports OpenAI-compatible APIs. Prefer docs.browser-use.com and the browser-use GitHub repo.')
	plan = fallback_task_plan(config)
	assert 'https://github.com/browser-use/browser-use' in plan.web_sources


def test_stage_prompt_contains_direct_source_urls():
	plan = fallback_task_plan(ResearchAssistantConfig(task='recommend headphones under 150 dollars'))
	prompt = build_stage_prompt(plan, SourceType.shopping, ['bestbuy.com', 'walmart.com'], plan.shopping_queries, 2)
	assert 'https://www.bestbuy.com/site/searchpage.jsp?st=' in prompt
	assert 'https://www.walmart.com/search?q=' in prompt
	assert 'already be on site-specific search or result pages' in prompt
	assert 'Do not use generic web search engines' in prompt
	assert '## Candidate Options' in prompt


def test_dynamic_shopping_sources_use_browser_observation_and_auto_vision():
	config = ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机')
	assert _requires_browser_observation(SourceType.shopping, ['jd.com'])
	assert _requires_browser_observation(SourceType.shopping, ['taobao.com'])
	assert not _requires_browser_observation(SourceType.shopping, ['walmart.com'])
	assert _stage_use_vision(config, SourceType.shopping, ['jd.com']) == 'auto'
	assert _stage_use_vision(config, SourceType.shopping, ['walmart.com']) is False
	assert _stage_use_vision(config.model_copy(update={'use_vision': True}), SourceType.shopping, ['walmart.com']) is True


def test_dynamic_shopping_source_allows_related_verification_domains():
	adapter = get_site_adapter('jd.com', SourceType.shopping)
	assert 'passport.jd.com' in adapter.allowed_domains
	assert 'plogin.m.jd.com' in adapter.allowed_domains
	assert 'cfe.m.jd.com' in adapter.allowed_domains
	assert 'storage.360buyimg.com' in adapter.allowed_domains


def test_stage_prompt_for_dynamic_shopping_sources_mentions_rendered_page_observation():
	plan = fallback_task_plan(ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机'))
	prompt = build_stage_prompt(plan, SourceType.shopping, ['jd.com'], plan.shopping_queries, 3)
	assert 'Dynamic-page guidance' in prompt
	assert 'Use the rendered browser page as the source of truth' in prompt
	assert 'verification page' in prompt


def test_chinese_default_stage_schedule_tries_three_shopping_sources(monkeypatch):
	async def fake_run_stage(self, plan, source_type, sources, queries, max_steps, cdp_url):
		return StageResult(
			stage_name=f'{source_type.value}_collection',
			source_type=source_type,
			sources=sources,
			prompt='x',
		)

	monkeypatch.setattr(BrowserResearchAssistant, '_run_stage', fake_run_stage)
	assistant = BrowserResearchAssistant(ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机'), llm=None)
	assistant.llm = object()
	plan = fallback_task_plan(assistant.config)
	results = asyncio.run(assistant._run_stages(plan, cdp_url='http://localhost:9222'))
	shopping_sources = [stage.sources[0] for stage in results if stage.source_type == SourceType.shopping]
	assert shopping_sources[:3] == ['jd.com', 'tmall.com', 'taobao.com']


def test_explicit_shopping_source_keeps_stage_schedule_narrow(monkeypatch):
	async def fake_run_stage(self, plan, source_type, sources, queries, max_steps, cdp_url):
		return StageResult(
			stage_name=f'{source_type.value}_collection',
			source_type=source_type,
			sources=sources,
			prompt='x',
		)

	monkeypatch.setattr(BrowserResearchAssistant, '_run_stage', fake_run_stage)
	assistant = BrowserResearchAssistant(
		ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机', shopping_sites=['jd.com']),
		llm=None,
	)
	assistant.llm = object()
	plan = fallback_task_plan(assistant.config)
	results = asyncio.run(assistant._run_stages(plan, cdp_url='http://localhost:9222'))
	shopping_sources = [stage.sources[0] for stage in results if stage.source_type == SourceType.shopping]
	assert shopping_sources == ['jd.com']


def test_generated_stages_extend_default_stage_schedule(monkeypatch):
	async def fake_run_stage(self, plan, source_type, sources, queries, max_steps, cdp_url):
		return StageResult(
			stage_name=f'{source_type.value}_collection',
			source_type=source_type,
			sources=sources,
			prompt='x',
			final_result='ok',
		)

	monkeypatch.setattr(BrowserResearchAssistant, '_run_stage', fake_run_stage)
	assistant = BrowserResearchAssistant(ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机'), llm=None)
	assistant.llm = object()
	plan = fallback_task_plan(assistant.config)
	plan.generated_stages = [
		GeneratedStageSpec(
			source_type=SourceType.review,
			source='zhihu.com',
			queries=['1000元以下 头戴式耳机 用户体验'],
			purpose='Collect user sentiment and comfort complaints.',
		),
		GeneratedStageSpec(
			source_type=SourceType.official,
			source='sony.com',
			queries=['Sony headphones specs comfort weight'],
			purpose='Check official specifications for shortlist candidates.',
		),
	]
	results = asyncio.run(assistant._run_stages(plan, cdp_url='http://localhost:9222'))
	stage_keys = [(stage.source_type, stage.sources[0]) for stage in results]
	assert (SourceType.shopping, 'jd.com') in stage_keys
	assert (SourceType.review, 'sspai.com') in stage_keys
	assert (SourceType.review, 'zhihu.com') in stage_keys
	assert (SourceType.official, 'sony.com') in stage_keys


def test_normalize_generated_stages_filters_invalid_sources():
	fallback = fallback_task_plan(ResearchAssistantConfig(task='Recommend headphones under $150'))
	stages = _normalize_generated_stages(
		[
			GeneratedStageSpec(source_type=SourceType.web, source='Search the whole web', queries=[]),
			GeneratedStageSpec(source_type=SourceType.web, source='https://docs.browser-use.com', queries=['openai api']),
		],
		fallback,
	)
	assert [stage.source for stage in stages] == ['https://docs.browser-use.com']
	assert stages[0].queries == ['openai api']


def test_build_source_entry_urls_prefers_site_search_pages():
	urls = build_source_entry_urls(SourceType.review, ['rtings.com', 'soundguys.com'], ['best over-ear headphones under 150'])
	assert urls[0].startswith('https://www.rtings.com/search?q=')
	assert urls[1].startswith('https://www.soundguys.com/?s=')


def test_build_source_entry_urls_supports_web_search_and_direct_urls():
	urls = build_source_entry_urls(SourceType.web, ['bing.com', 'https://docs.browser-use.com'], ['browser-use openai compatible api'])
	assert urls[0].startswith('https://www.bing.com/search?q=')
	assert urls[1] == 'https://docs.browser-use.com'


def test_build_bing_rss_search_url_adds_site_filter_for_domain_sources():
	url = build_bing_rss_search_url('browser-use openai compatible api', source='docs.browser-use.com')
	assert 'format=rss' in url
	assert 'site%3Adocs.browser-use.com' in url


def test_build_docs_direct_urls_adds_llm_indexes_for_provider_queries():
	urls = build_docs_direct_urls('browser-use openai compatible api base_url')
	assert urls == [
		'https://docs.browser-use.com',
		'https://docs.browser-use.com/llms.txt',
		'https://docs.browser-use.com/llms-full.txt',
	]


def test_build_github_repo_direct_urls_adds_raw_readme_and_searches():
	urls = build_github_repo_direct_urls('https://github.com/browser-use/browser-use', 'openai compatible api base_url')
	assert 'https://raw.githubusercontent.com/browser-use/browser-use/main/README.md' in urls
	assert 'https://github.com/browser-use/browser-use/search?q=openai' in urls
	assert 'https://github.com/browser-use/browser-use/search?q=base_url' in urls


def test_extract_bing_rss_results_reads_items():
	xml_text = """
	<rss><channel>
		<item>
			<title>OpenAI-compatible endpoint support</title>
			<link>https://docs.browser-use.com/customize/agent/supported-models</link>
			<description>Browser Use supports OpenAI-compatible providers through ChatOpenAI.</description>
		</item>
		<item>
			<title>GitHub README</title>
			<link>https://github.com/browser-use/browser-use</link>
			<description>Examples and configuration guidance.</description>
		</item>
	</channel></rss>
	"""
	results = extract_bing_rss_results(xml_text, limit=4)
	assert results[0][0] == 'OpenAI-compatible endpoint support'
	assert results[0][1] == 'https://docs.browser-use.com/customize/agent/supported-models'
	assert 'ChatOpenAI' in results[0][2]


def test_extract_bing_rss_results_filters_unrelated_results_for_source_domain():
	xml_text = """
	<rss><channel>
		<item>
			<title>Credit Card Login | Discover Card</title>
			<link>https://portal.discover.com/customersvcs/universalLogin/ac_main</link>
			<description>Secure account center.</description>
		</item>
		<item>
			<title>Browser Use provider models</title>
			<link>https://docs.browser-use.com/customize/agent/supported-models</link>
			<description>Use ChatOpenAI with OpenAI-compatible providers via base_url.</description>
		</item>
	</channel></rss>
	"""
	results = extract_bing_rss_results(
		xml_text,
		limit=4,
		query='browser-use openai compatible provider base_url',
		source='docs.browser-use.com',
	)
	assert results == [
		(
			'Browser Use provider models',
			'https://docs.browser-use.com/customize/agent/supported-models',
			'Use ChatOpenAI with OpenAI-compatible providers via base_url.',
		)
	]


def test_extract_bing_rss_results_accepts_github_and_raw_github_hosts():
	xml_text = """
	<rss><channel>
		<item>
			<title>browser-use README</title>
			<link>https://raw.githubusercontent.com/browser-use/browser-use/main/README.md</link>
			<description>Browser Use supports ChatOpenAI and other providers.</description>
		</item>
		<item>
			<title>browser-use repo search openai</title>
			<link>https://github.com/browser-use/browser-use/search?q=openai</link>
			<description>Repository search results for openai.</description>
		</item>
		<item>
			<title>Random Wordle site</title>
			<link>https://example.com/wordle</link>
			<description>Unrelated content.</description>
		</item>
	</channel></rss>
	"""
	results = extract_bing_rss_results(
		xml_text,
		limit=4,
		query='browser-use openai compatible api',
		source='github.com',
	)
	assert any(result[1] == 'https://raw.githubusercontent.com/browser-use/browser-use/main/README.md' for result in results)
	assert any(result[1] == 'https://github.com/browser-use/browser-use/search?q=openai' for result in results)
	assert all('example.com' not in result[1] for result in results)


def test_plain_text_excerpt_normalizes_whitespace():
	assert plain_text_excerpt('line 1\n\nline 2\t tabbed') == 'line 1 line 2 tabbed'


def test_adapt_query_for_english_source_from_chinese_request():
	query = '1000元以下 头戴式耳机 京东 自营 注重均衡声音和佩戴舒适度'
	adapted = adapt_query_for_source(query, 'walmart.com')
	assert '京东' not in adapted
	assert '自营' not in adapted
	assert 'over-ear headphones' in adapted
	assert 'balanced sound' in adapted
	assert 'under 142 dollars' in adapted


def test_extract_site_candidate_urls_for_review_sites():
	rtings_html = """
	<html><body>
	<script>
	window.__DATA__ = [{&quot;title&quot;:&quot;Best wireless&quot;,&quot;url&quot;:&quot;/headphones/reviews/best/wireless-bluetooth-headphones&quot;}]
	</script>
	</body></html>
	"""
	soundguys_html = """
	<html><body>
	<a href="https://www.soundguys.com/best-wireless-headphones-12345/">Roundup</a>
	<a href="/static/fonts/bold.woff2">Font</a>
	<a href="https://www.soundguys.com/category/headphones/">Category</a>
	</body></html>
	"""
	assert extract_site_candidate_urls('rtings.com', rtings_html) == ['https://www.rtings.com/headphones/reviews/best/wireless-bluetooth-headphones']
	assert extract_site_candidate_urls('soundguys.com', soundguys_html) == ['https://www.soundguys.com/best-wireless-headphones-12345/']


def test_extract_site_candidate_urls_for_soundguys_filters_news_and_deals():
	soundguys_html = """
	<html><body>
	<a href="https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/">Best budget ANC headphones</a>
	<a href="https://www.soundguys.com/sony-wh-ch720n-deal-158486/">Deal post</a>
	<a href="https://www.soundguys.com/headphones-spotted-lamine-yamal-158501/">News post</a>
	<a href="https://www.soundguys.com/sony-ult-wear-review-113412/">Review post</a>
	</body></html>
	"""
	assert extract_site_candidate_urls('soundguys.com', soundguys_html) == [
		'https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/',
		'https://www.soundguys.com/sony-ult-wear-review-113412/',
	]


def test_extract_site_candidate_urls_for_soundguys_respects_over_ear_query():
	soundguys_html = """
	<html><body>
	<a href="https://www.soundguys.com/best-wireless-earbuds-2-14313/">Earbuds</a>
	<a href="https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/">Headphones</a>
	<a href="https://www.soundguys.com/sony-ult-wear-review-113412/">Review</a>
	</body></html>
	"""
	assert extract_site_candidate_urls('soundguys.com', soundguys_html, query='best over-ear headphones balanced sound comfort review') == [
		'https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/',
		'https://www.soundguys.com/sony-ult-wear-review-113412/',
	]


def test_extract_site_candidate_urls_for_tomsguide_review_pages():
	tomsguide_html = """
	<html><body>
	<a href="https://www.tomsguide.com/audio/headphones/dyson-ontrac-headphones-review">Review</a>
	<a href="https://www.tomsguide.com/audio/headphones/airpods">Category</a>
	<a href="https://www.tomsguide.com/best-picks/best-over-ear-headphones">Best pick</a>
	</body></html>
	"""
	assert extract_site_candidate_urls('tomsguide.com', tomsguide_html, query='best over-ear headphones balanced sound comfort review') == [
		'https://www.tomsguide.com/best-picks/best-over-ear-headphones',
		'https://www.tomsguide.com/audio/headphones/dyson-ontrac-headphones-review',
	]


def test_extract_site_candidate_urls_for_sspai_posts():
	sspai_html = """
	<html><body>
	<a href="https://sspai.com/post/110806">Moondrop Pudding</a>
	<a href="/post/109163">Sony WF-1000XM6</a>
	<a href="https://sspai.com/tag/%E8%80%B3%E6%9C%BA">Tag</a>
	</body></html>
	"""
	assert extract_site_candidate_urls('sspai.com', sspai_html, query='1000元以下 头戴式耳机 均衡 舒适 评测') == [
		'https://sspai.com/post/110806',
		'https://sspai.com/post/109163',
	]


def test_build_ifanr_direct_urls():
	assert build_ifanr_direct_urls('1000元以下 头戴式耳机 评测') == [
		'https://www.ifanr.com/category/review',
		'https://www.ifanr.com/category/evaluation',
	]


def test_extract_ifanr_api_candidate_urls_prefers_headphone_reviews():
	payload = {
		'objects': [
			{
				'post_title': '索尼 WH-1000XM6 首发评测：一款迟到三年的索尼旗舰降噪耳机',
				'post_url': 'https://www.ifanr.com/1623940',
				'post_excerpt': '三年之期已到，索尼终于把可折叠收纳设计带回来了。',
			},
			{
				'post_title': 'Sonos Arc Ultra 体验：一个音响就是一整套 9.1.4 杜比全景声？',
				'post_url': 'https://www.ifanr.com/1635653',
				'post_excerpt': 'Sonos 竟然将一个低音炮塞入了一个条形音响之内。',
			},
			{
				'post_title': '荣耀 Magic V6 体验：iPhone Ultra 的第一个挑战者',
				'post_url': 'https://www.ifanr.com/1657451',
				'post_excerpt': '手机涨价潮之下，是全能大折叠的新机会？',
			},
			{
				'post_title': '423观察',
				'post_url': 'https://www.ifanr.com/news/1252289',
				'post_excerpt': '',
			},
		]
	}
	assert extract_ifanr_api_candidate_urls(payload, query='1000元以下 头戴式耳机 均衡 舒适 评测', limit=3) == [
		'https://www.ifanr.com/1623940',
	]


def test_extract_shopping_candidates_for_walmart():
	walmart_html = """
	<html><body>
	<script id="__NEXT_DATA__" type="application/json">
	{"props":{"pageProps":{"initialData":{"searchResult":{"itemStacks":[{"itemsV2":[
		{"name":"OneOdio Wired over-Ear Headphones","canonicalUrl":"/ip/OneOdio/950096760?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$31.99"}},"averageRating":4.6,"numberOfReviews":2850},
		{"name":"Kids Earbuds","canonicalUrl":"/ip/Kids-Earbuds/123?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$9.99"}},"averageRating":4.9,"numberOfReviews":12}
	]}]}}}}}
	</script>
	</body></html>
	"""
	candidates = extract_shopping_candidates('walmart.com', walmart_html, query='over-ear headphones under 150')
	assert candidates[0].title == 'OneOdio Wired over-Ear Headphones'
	assert candidates[0].url == 'https://www.walmart.com/ip/OneOdio/950096760?classType=VARIANT'
	assert candidates[0].price_text == '$31.99'


def test_extract_shopping_candidates_penalizes_generic_marketing_titles():
	walmart_html = """
	<html><body>
	<script id="__NEXT_DATA__" type="application/json">
	{"props":{"pageProps":{"initialData":{"searchResult":{"itemStacks":[{"itemsV2":[
		{"name":"Bluetooth Headphones Over Ear, 120H Playtime, HiFi Stereo, Low Latency","canonicalUrl":"/ip/Generic/111?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$29.99"}},"averageRating":4.8,"numberOfReviews":200},
		{"name":"Sony MDR-7506 Closed-Back Over-Ear Professional Monitor Headphones","canonicalUrl":"/ip/Sony/222?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$99.99"}},"averageRating":4.7,"numberOfReviews":300}
	]}]}}}}}
	</script>
	</body></html>
	"""
	candidates = extract_shopping_candidates('walmart.com', walmart_html, query='over-ear headphones under 150')
	assert candidates[0].title == 'Sony MDR-7506 Closed-Back Over-Ear Professional Monitor Headphones'


def test_extract_shopping_candidates_filters_generic_noise_when_viable_models_exist():
	walmart_html = """
	<html><body>
	<script id="__NEXT_DATA__" type="application/json">
	{"props":{"pageProps":{"initialData":{"searchResult":{"itemStacks":[{"itemsV2":[
		{"name":"Wireless Over Ear Headphones, Active Noise Cancelling, Transparency Mode, Spatial Audio, Comfortable Protein Earpads, 24 Hours Playtime","canonicalUrl":"/ip/Generic/111?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$29.99"}},"averageRating":4.8,"numberOfReviews":200},
		{"name":"FIFINE Studio Wired Headphones for DJ Music Monitor Recording Podcast Streaming with 9.8ft Cable for 3.5mm/6.35mm Over Ear Noise Cancelling H8","canonicalUrl":"/ip/FIFINE/222?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$39.99"}},"averageRating":4.7,"numberOfReviews":300},
		{"name":"Sony MDR-7506 Closed-Back Over-Ear Professional Monitor Headphones","canonicalUrl":"/ip/Sony/333?classType=VARIANT","priceInfo":{"currentPrice":{"priceString":"$99.99"}},"averageRating":4.7,"numberOfReviews":300}
	]}]}}}}}
	</script>
	</body></html>
	"""
	candidates = extract_shopping_candidates('walmart.com', walmart_html, query='over-ear headphones under 150')
	assert all('Wireless Over Ear Headphones, Active Noise Cancelling' not in candidate.title for candidate in candidates)
	assert candidates[0].title == 'Sony MDR-7506 Closed-Back Over-Ear Professional Monitor Headphones'


def test_extract_shopping_candidates_for_adorama():
	adorama_html = """
	<html><body>
	<script id="__NEXT_DATA__" type="application/json">
	{"props":{"pageProps":{"products":[
		{"productTitle":"Sony MDR-7506 Closed-Back Over-Ear Professional Monitor Headphones","productUrl":"/sony-mdr-7506/p/somdr7506","prices":{"price":113},"ratings":{"count":76,"averageRatingStars":5}},
		{"productTitle":"Bose QuietComfort Ultra Wireless Noise Cancelling Over-Ear Headphones","productUrl":"/bose-quietcomfort/p/bo8800660300","prices":{"price":429},"ratings":{"count":760,"averageRatingStars":4.5}}
	]}}}
	</script>
	</body></html>
	"""
	candidates = extract_shopping_candidates('adorama.com', adorama_html, query='over-ear headphones under 150')
	assert candidates[0].title == 'Sony MDR-7506 Closed-Back Over-Ear Professional Monitor Headphones'
	assert candidates[0].url == 'https://www.adorama.com/sony-mdr-7506/p/somdr7506'
	assert candidates[0].price_text == '$113.00'


def test_build_candidate_catalog_merges_same_model_across_sources():
	stage_results = [
		StageResult(
			stage_name='shopping_collection',
			source_type=SourceType.shopping,
			sources=['adorama.com'],
			prompt='x',
			candidate_evidence=[
				CandidateEvidence(
					title='Sony WH-CH720N Wireless Noise Cancelling Over-Ear Headphone, Black',
					source_type=SourceType.shopping,
					source='adorama.com',
					url='https://www.adorama.com/used-sony-wh-ch720n',
					price_text='$44.00',
					evidence='Shopping listing on adorama.com at $44.00.',
				)
			],
		),
		StageResult(
			stage_name='review_collection',
			source_type=SourceType.review,
			sources=['soundguys.com'],
			prompt='x',
			candidate_evidence=[
				CandidateEvidence(
					title='Sony WH-CH720N',
					source_type=SourceType.review,
					source='soundguys.com',
					url='https://www.soundguys.com/best-sony-headphones-31948/',
					price_text='$148.00',
					sound_notes='Budget ANC pick; balanced tuning not confirmed.',
					evidence='Listed as Best ANC on a budget.',
				)
			],
		),
	]
	catalog = build_candidate_catalog(stage_results)
	assert len(catalog) == 1
	assert catalog[0].title.startswith('Sony WH-CH720N')
	assert SourceType.shopping in catalog[0].source_types
	assert SourceType.review in catalog[0].source_types
	assert '$44.00' in catalog[0].price_texts
	assert '$148.00' in catalog[0].price_texts


def test_build_rtings_direct_urls_from_budget_query():
	urls = build_rtings_direct_urls('over-ear headphones review neutral sound comfort under 150')
	assert 'https://www.rtings.com/headphones/reviews/best/by-price/under-200' in urls
	assert 'https://www.rtings.com/headphones/reviews/best/by-price/under-100' in urls


def test_build_rtings_direct_urls_from_adapted_chinese_query():
	adapted = adapt_query_for_source('1000元以下 头戴式耳机 注重均衡声音和佩戴舒适度', 'rtings.com')
	urls = build_rtings_direct_urls(adapted)
	assert 'https://www.rtings.com/headphones/reviews/best/by-price/under-200' in urls
	assert 'https://www.rtings.com/headphones/reviews/best/by-price/under-100' in urls


def test_query_budget_limit_supports_cny_phrasing():
	assert _query_budget_limit('帮我推荐一款1000元以下的耳机') == 1000


def test_build_tomsguide_direct_urls_from_budget_query():
	urls = build_tomsguide_direct_urls('best over-ear headphones balanced sound comfort under 150 review')
	assert 'https://www.tomsguide.com/best-picks/best-over-ear-headphones' in urls
	assert 'https://www.tomsguide.com/best-picks/best-headphones' in urls
	assert 'https://www.tomsguide.com/best-picks/best-cheap-headphones' in urls


def test_build_soundguys_direct_urls_from_budget_query():
	urls = build_soundguys_direct_urls('best over-ear headphones balanced sound comfort under 150 review')
	assert urls == ['https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/']


def test_build_sspai_direct_urls_for_headphones_query():
	urls = build_sspai_direct_urls('1000元以下 头戴式耳机 均衡 舒适 评测')
	assert urls == ['https://sspai.com/tag/%E8%80%B3%E6%9C%BA']


def test_extract_review_candidates_for_rtings_roundup():
	rtings_html = """
	<div data-vue="RecommendationVuePage" data-props="{&quot;page_data&quot;:{&quot;page&quot;:{&quot;recommendation&quot;:{&quot;product_recommendations&quot;:[
		{&quot;title&quot;:&quot;Best Headphones Under $200&quot;,&quot;subtitle&quot;:&quot;Flagship level ANC, great app, but plasticky build.&quot;,&quot;description&quot;:&quot;&lt;p&gt;The Anker Soundcore Space Q45 Wireless are the best headphones under $200 that we've tested. They have a somewhat v-shaped sound and are comfortable.&lt;/p&gt;&quot;,&quot;product&quot;:{&quot;fullname&quot;:&quot;Anker Soundcore Space Q45 Wireless&quot;,&quot;review_url&quot;:&quot;/headphones/reviews/anker/soundcore-space-q45-wireless&quot;},&quot;featured_deals&quot;:[]}
	]}}}}" ></div>
	"""
	candidates = extract_review_candidates('rtings.com', rtings_html, 'https://www.rtings.com/headphones/reviews/best/by-price/under-200')
	assert candidates[0].title == 'Anker Soundcore Space Q45 Wireless'
	assert candidates[0].source == 'rtings.com'
	assert candidates[0].url == 'https://www.rtings.com/headphones/reviews/anker/soundcore-space-q45-wireless'
	assert candidates[0].price_text == 'Under $200'
	assert 'comfortable' in (candidates[0].comfort_notes or '').lower()


def test_extract_review_candidates_for_soundguys_best_list():
	soundguys_html = """
	<html><body>
	<script id="__NEXT_DATA__" type="application/json">
	{"props":{"pageProps":{"page":{"resource":"best-list-page","blocks":[
		{"resource":"nc-string","html":"<h3>The best overall:</h3>"},
		{"resource":"nc-deals-detailed","title":"Sony ULT WEAR","score":8.2,"tags":["Comfortable "," ANC "," Sound quality"],"pLink":{"href":"https://dealhunt.co/us-B0CX1TJXKV"},"refLink":{"label":"See review","pLink":{"href":"https://www.soundguys.com/sony-ult-wear-review-113412/"}},"buttons":[{"link":{"label":"$149.99 at Amazon","pLink":{"href":"https://dealhunt.co/us-B0CX1TJXKV"}},"price":{"currency":"$","current":149.99}}]}
	]}}}}
	</script>
	</body></html>
	"""
	candidates = extract_review_candidates('soundguys.com', soundguys_html, 'https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/')
	assert candidates[0].title == 'Sony ULT WEAR'
	assert candidates[0].source == 'soundguys.com'
	assert candidates[0].url == 'https://www.soundguys.com/sony-ult-wear-review-113412/'
	assert candidates[0].price_text == '$149.99'
	assert 'best overall' in candidates[0].evidence.lower()
	assert 'comfortable' in (candidates[0].comfort_notes or '').lower()


def test_extract_review_candidates_for_tomsguide_review_page():
	tomsguide_html = """
	<html><head>
	<title>Dyson OnTrac review: Dyson just got serious about headphones | Tom's Guide</title>
	<meta name="description" content="The Dyson OnTrac headphones impress with a customizable design, great active noise cancellation and an epic 55 hours of battery life.">
	</head><body>
	<p>Price: $499.99</p>
	</body></html>
	"""
	candidates = extract_review_candidates('tomsguide.com', tomsguide_html, 'https://www.tomsguide.com/audio/headphones/dyson-ontrac-headphones-review')
	assert candidates[0].title == 'Dyson OnTrac'
	assert candidates[0].source == 'tomsguide.com'
	assert candidates[0].price_text == '$499.99'
	assert 'great active noise cancellation' in (candidates[0].sound_notes or '').lower()


def test_extract_review_candidates_for_tomsguide_best_picks_page():
	tomsguide_html = """
	<html><body>
	<h3>Best over-ear headphones overall</h3>
	<div class="product prog-buying-guide">
		<div class="title-and-rating">
			<h3 class="product__title"><a href="https://www.tomsguide.com/audio/bowers-and-wilkins-px7-s3-review">1. Bowers &amp; Wilkins PX7 S3</a></h3>
		</div>
		<div class="_hawk subtitle">With spectacular versatility and performance these are best for most people</div>
		<div class="product-summary spec">
			<div class="spec__entry"><span class="spec__name">ANC:</span><span class="spec_value">Yes</span></div>
			<div class="spec__entry"><span class="spec__name">Weight:</span><span class="spec_value">10.6 ounces</span></div>
		</div>
		<p>Today's Best Deals $399.00</p>
	</div>
	<h3>Best value over-ear headphones</h3>
	<div class="product prog-buying-guide">
		<div class="title-and-rating">
			<h3 class="product__title"><a href="https://www.tomsguide.com/audio/headphones/cmf-by-nothing-headphone-pro-review">2. CMF Headphone Pro</a></h3>
		</div>
		<div class="_hawk subtitle">Comfortable design with surprising sound quality for the money</div>
	</div>
	</body></html>
	"""
	candidates = extract_review_candidates('tomsguide.com', tomsguide_html, 'https://www.tomsguide.com/best-picks/best-over-ear-headphones')
	assert [candidate.title for candidate in candidates[:2]] == ['Bowers & Wilkins PX7 S3', 'CMF Headphone Pro']
	assert candidates[0].url == 'https://www.tomsguide.com/audio/bowers-and-wilkins-px7-s3-review'
	assert candidates[0].price_text == '$399.00'
	assert 'best over-ear headphones overall' in candidates[0].evidence.lower()
	assert 'comfortable' in (candidates[1].comfort_notes or '').lower()


def test_extract_review_candidates_for_sspai_article():
	sspai_html = """
	<html><head>
	<title>TDS REVIEW｜1More SonoFlow Pro 体验：降噪、佩戴和声音都很能打 - 少数派</title>
	<meta name="description" content="这款头戴式耳机在调音、降噪和佩戴舒适度上都很均衡，长时间使用也不夹头，价格大约 $90。">
	</head><body>
	<article><p>正文略。</p></article>
	</body></html>
	"""
	candidates = extract_review_candidates('sspai.com', sspai_html, 'https://sspai.com/post/110806')
	assert candidates[0].title == '1More SonoFlow Pro'
	assert candidates[0].source == 'sspai.com'
	assert candidates[0].price_text == '$90'
	assert '舒适' in (candidates[0].comfort_notes or '')


def test_extract_review_candidates_for_sspai_tag_page_returns_empty():
	sspai_html = """
	<html><head>
	<title>#耳机 - 少数派</title>
	<meta name="description" content="少数派耳机标签页。">
	</head><body></body></html>
	"""
	assert extract_review_candidates('sspai.com', sspai_html, 'https://sspai.com/tag/%E8%80%B3%E6%9C%BA') == []


def test_extract_review_candidates_for_ifanr_article():
	ifanr_html = """
	<html><head>
	<title>索尼 WH-1000XM6 首发评测：一款迟到三年的索尼旗舰降噪耳机 | 爱范儿</title>
	<meta name="description" content="三年之期已到，索尼终于把可折叠收纳设计带回来了，佩戴更舒适。">
	</head><body>
	<article><p>这是一款头戴式降噪耳机，主打佩戴舒适和更成熟的声音表现。</p></article>
	</body></html>
	"""
	candidates = extract_review_candidates('ifanr.com', ifanr_html, 'https://www.ifanr.com/1623940')
	assert candidates[0].title == '索尼 WH-1000XM6'
	assert candidates[0].source == 'ifanr.com'
	assert '舒适' in (candidates[0].comfort_notes or '')


def test_ifanr_review_candidate_matches_query_rejects_phone_articles_for_headphones_task():
	candidate = CandidateEvidence(
		title='荣耀 Magic V6',
		source_type=SourceType.review,
		source='ifanr.com',
		url='https://www.ifanr.com/1657451',
		evidence='荣耀 Magic V6 体验：iPhone Ultra 的第一个挑战者 | 手机涨价潮之下，是全能大折叠的新机会？',
	)
	assert _ifanr_review_candidate_matches_query(candidate, '1000元以下 头戴式耳机 均衡 舒适 评测') is False


def test_review_candidate_matches_query_filters_chinese_true_wireless_for_over_ear_task():
	candidate = CandidateEvidence(
		title='索尼 WF-1000XM6 降噪真无线耳机',
		source_type=SourceType.review,
		source='sspai.com',
		url='https://sspai.com/post/109163',
		evidence='真无线、入耳、降噪体验出色。',
	)
	assert _review_candidate_matches_query(candidate, '1000元以下 头戴式耳机 均衡 舒适 评测') is False


def test_review_candidate_matches_query_filters_ambiguous_chinese_earphone_without_over_ear_signal():
	candidate = CandidateEvidence(
		title='水月雨布丁',
		source_type=SourceType.review,
		source='sspai.com',
		url='https://sspai.com/post/110806',
		evidence='这副用了三年的耳机，后来主力换新。',
	)
	assert _review_candidate_matches_query(candidate, '1000元以下 头戴式耳机 均衡 舒适 评测') is False


def test_rank_candidate_catalog_prefers_review_backed_balanced_option():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 150 dollars with balanced sound and good comfort'))
	catalog = [
		build_candidate_catalog(
			[
				StageResult(
					stage_name='review_collection',
					source_type=SourceType.review,
					sources=['rtings.com'],
					prompt='x',
					candidate_evidence=[
						CandidateEvidence(
							title='Sennheiser HD 560S',
							source_type=SourceType.review,
							source='rtings.com',
							url='https://www.rtings.com/headphones/reviews/sennheiser/hd-560s',
							price_text='$149.00',
							sound_notes='Balanced sound profile with neutral mids.',
							comfort_notes='Comfortable lightweight fit for long sessions.',
							evidence='RTINGS notes balanced tuning and comfort.',
						),
						CandidateEvidence(
							title='BassBlaster Game Pro X',
							source_type=SourceType.review,
							source='rtings.com',
							url='https://www.rtings.com/headphones/reviews/bassblaster/game-pro-x',
							price_text='$139.00',
							sound_notes='V-shaped sound with elevated bass for gaming.',
							comfort_notes='Clamp force is noticeable over time.',
							evidence='Gaming-focused tuning.',
						),
					],
				),
				StageResult(
					stage_name='shopping_collection',
					source_type=SourceType.shopping,
					sources=['adorama.com'],
					prompt='x',
					candidate_evidence=[
						CandidateEvidence(
							title='Sennheiser HD 560S',
							source_type=SourceType.shopping,
							source='adorama.com',
							url='https://www.adorama.com/sehd560s.html',
							price_text='$149.00',
							evidence='Retail listing at $149.00.',
						)
					],
				),
			]
		)[0],
		build_candidate_catalog(
			[
				StageResult(
					stage_name='review_collection',
					source_type=SourceType.review,
					sources=['rtings.com'],
					prompt='x',
					candidate_evidence=[
						CandidateEvidence(
							title='BassBlaster Game Pro X',
							source_type=SourceType.review,
							source='rtings.com',
							url='https://www.rtings.com/headphones/reviews/bassblaster/game-pro-x',
							price_text='$139.00',
							sound_notes='V-shaped sound with elevated bass for gaming.',
							comfort_notes='Clamp force is noticeable over time.',
							evidence='Gaming-focused tuning.',
						)
					],
				)
			]
		)[0],
	]
	ranked = rank_candidate_catalog(plan, catalog)
	assert ranked[0].candidate.title == 'Sennheiser HD 560S'
	assert ranked[0].score > ranked[1].score


def test_rank_candidate_catalog_uses_rough_cny_budget_comparison():
	plan = fallback_task_plan(ResearchAssistantConfig(task='帮我推荐一款1000元以下的头戴式耳机，注重均衡声音和佩戴舒适度'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='shopping_collection',
				source_type=SourceType.shopping,
				sources=['adorama.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Sony WH-1000XM6',
						source_type=SourceType.shopping,
						source='adorama.com',
						url='https://www.adorama.com/sony-wh-1000xm6-wireless-noise-canceling-headphones/p/sowh1000xm6b',
						price_text='$398.00',
						evidence='Retail listing at $398.00.',
					),
					CandidateEvidence(
						title='Sony MDR-7506',
						source_type=SourceType.shopping,
						source='adorama.com',
						url='https://www.adorama.com/sony-mdr-7506/p/somdr7506',
						price_text='$113.00',
						evidence='Retail listing at $113.00.',
					),
				],
			)
		]
	)
	ranked = rank_candidate_catalog(plan, catalog)
	assert ranked[0].candidate.title == 'Sony MDR-7506'
	assert ranked[0].score > ranked[1].score


def test_normalize_recommendations_to_shortlist_filters_and_backfills():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 150 dollars with balanced sound and good comfort'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='review_collection',
				source_type=SourceType.review,
				sources=['rtings.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Philips SHP9500',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/philips/shp9500',
						price_text='Under $100',
						sound_notes='Well-balanced sound profile.',
						comfort_notes='Very comfortable over-ears.',
						evidence='Balanced and comfortable.',
					),
					CandidateEvidence(
						title='Sennheiser HD 560S',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/sennheiser/hd-560s',
						price_text='Under $200',
						sound_notes='Balanced sound profile.',
						comfort_notes='Lightweight and comfortable.',
						evidence='Neutral and spacious.',
					),
					CandidateEvidence(
						title='TOZO HT3',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/tozo-ht3',
						price_text='$39.99',
						evidence='Cheap shopping-only fallback.',
					),
				],
			)
		]
	)
	shortlist = rank_candidate_catalog(plan, catalog)
	recommendations = _normalize_recommendations_to_shortlist(
		[
			SuggestedOption(title='Random Off-List Model', why_it_matches='Should be dropped.'),
			SuggestedOption(title='TOZO HT3', why_it_matches='Lower ranked but model picked it.'),
			SuggestedOption(title='Philips SHP9500', why_it_matches='Great match.'),
		],
		shortlist,
		3,
	)
	assert recommendations[0].title == 'Philips SHP9500'
	assert recommendations[0].url == 'https://www.rtings.com/headphones/reviews/philips/shp9500'
	assert recommendations[1].title == 'Sennheiser HD 560S'
	assert recommendations[2].title == 'TOZO HT3'


def test_normalize_recommendations_to_shortlist_prefers_shopping_url_and_price_when_merged():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 150 dollars with balanced sound and good comfort'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='review_collection',
				source_type=SourceType.review,
				sources=['tomsguide.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='1More SonoFlow Pro',
						source_type=SourceType.review,
						source='tomsguide.com',
						url='https://www.tomsguide.com/audio/1more-sonoflow-pro-review',
						price_text='$90',
						evidence='Review evidence.',
					)
				],
			),
			StageResult(
				stage_name='shopping_collection',
				source_type=SourceType.shopping,
				sources=['walmart.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='1More SonoFlow Pro',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/1more-sonoflow-pro',
						price_text='$87.99',
						evidence='Shopping listing.',
					)
				],
			),
		]
	)
	shortlist = rank_candidate_catalog(plan, catalog)
	recommendations = _normalize_recommendations_to_shortlist(
		[SuggestedOption(title='1More SonoFlow Pro', why_it_matches='Good all-rounder.')],
		shortlist,
		3,
	)
	assert recommendations[0].url == 'https://www.walmart.com/ip/1more-sonoflow-pro'
	assert recommendations[0].price_text == '$87.99'


def test_normalize_recommendations_to_shortlist_excludes_over_budget_candidates_when_enough_alternatives_exist():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 150 dollars with balanced sound and good comfort'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='review_collection',
				source_type=SourceType.review,
				sources=['rtings.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Philips SHP9500',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/philips/shp9500',
						sound_notes='Well-balanced sound profile.',
						comfort_notes='Very comfortable over-ears.',
						evidence='Balanced and comfortable.',
					),
					CandidateEvidence(
						title='Sennheiser HD 560S',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/sennheiser/hd-560s',
						sound_notes='Balanced sound profile.',
						comfort_notes='Lightweight and comfortable.',
						evidence='Neutral and spacious.',
					),
					CandidateEvidence(
						title='AKG K371',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/akg/k371',
						sound_notes='Balanced and accurate sound.',
						comfort_notes='Comfortable for longer sessions.',
						evidence='Balanced and comfortable closed-back option.',
					),
					CandidateEvidence(
						title='Sony WH-1000XM6',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/sony/wh-1000xm6',
						sound_notes='Comfortable flagship ANC headphone.',
						comfort_notes='Comfortable and feature-rich.',
						evidence='Good headphone, but premium priced.',
					),
				],
			),
			StageResult(
				stage_name='shopping_collection',
				source_type=SourceType.shopping,
				sources=['walmart.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Philips SHP9500',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/philips-shp9500',
						price_text='$89.99',
						evidence='Shopping listing.',
					),
					CandidateEvidence(
						title='Sennheiser HD 560S',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/sennheiser-hd-560s',
						price_text='$149.99',
						evidence='Shopping listing.',
					),
					CandidateEvidence(
						title='AKG K371',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/akg-k371',
						price_text='$109.99',
						evidence='Shopping listing.',
					),
					CandidateEvidence(
						title='Sony WH-1000XM6',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/sony-wh-1000xm6',
						price_text='$398.00',
						evidence='Shopping listing.',
					),
				],
			),
		]
	)
	shortlist = rank_candidate_catalog(plan, catalog)
	recommendations = _normalize_recommendations_to_shortlist(
		[
			SuggestedOption(title='Sony WH-1000XM6', why_it_matches='Model picked a premium option first.'),
			SuggestedOption(title='Philips SHP9500', why_it_matches='Balanced and comfortable.'),
		],
		shortlist,
		3,
	)
	assert [item.title for item in recommendations] == ['Philips SHP9500', 'Sennheiser HD 560S', 'AKG K371']
	assert all(item.title != 'Sony WH-1000XM6' for item in recommendations)


def test_normalize_recommendations_to_shortlist_inherits_shopping_offer_from_nearby_title_match():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 200 dollars with balanced sound and good comfort'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='review_collection',
				source_type=SourceType.review,
				sources=['rtings.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Sennheiser HD 560S',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/sennheiser/hd-560s',
						sound_notes='Balanced sound profile.',
						comfort_notes='Lightweight and comfortable.',
						evidence='Neutral and spacious.',
					)
				],
			),
			StageResult(
				stage_name='shopping_collection',
				source_type=SourceType.shopping,
				sources=['walmart.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Sennheiser HD560S Open Back Headphones',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/sennheiser-hd560s-open-back',
						price_text='$179.99',
						evidence='Shopping listing under a variant title.',
					)
				],
			),
		]
	)
	ranked = rank_candidate_catalog(plan, catalog)
	shortlist = [item for item in ranked if item.candidate.title == 'Sennheiser HD 560S']
	recommendations = _normalize_recommendations_to_shortlist(
		[SuggestedOption(title='Sennheiser HD 560S', why_it_matches='Balanced and spacious.')],
		shortlist,
		3,
		ranked_candidates_pool=ranked,
	)
	assert recommendations[0].url == 'https://www.walmart.com/ip/sennheiser-hd560s-open-back'
	assert recommendations[0].price_text == '$179.99'


def test_normalize_recommendations_to_shortlist_rejects_mismatched_shopping_model():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 150 dollars'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='review_collection',
				source_type=SourceType.review,
				sources=['rtings.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Anker Soundcore Life Q30 Wireless',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/anker/soundcore-life-q30-wireless',
						price_text='Under $100',
						sound_notes='V-shaped sound with app EQ.',
						comfort_notes='Comfortable fit.',
						evidence='Review-backed candidate.',
					)
				],
			),
			StageResult(
				stage_name='shopping_collection',
				source_type=SourceType.shopping,
				sources=['walmart.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='TALIX H30 Adaptive ANC Wireless Headphones',
						source_type=SourceType.shopping,
						source='walmart.com',
						url='https://www.walmart.com/ip/talix-h30',
						price_text='$44.99',
						evidence='Different model shopping listing.',
					)
				],
			),
		]
	)
	ranked = rank_candidate_catalog(plan, catalog)
	shortlist = [item for item in ranked if item.candidate.title == 'Anker Soundcore Life Q30 Wireless']
	recommendations = _normalize_recommendations_to_shortlist(
		[SuggestedOption(title='Anker Soundcore Life Q30 Wireless', why_it_matches='Review-backed budget ANC.')],
		shortlist,
		1,
		ranked_candidates_pool=ranked,
	)
	assert recommendations[0].url == 'https://www.rtings.com/headphones/reviews/anker/soundcore-life-q30-wireless'
	assert recommendations[0].price_text == 'Under $100'


def test_apply_report_confidence_marks_recommendation_report_high_when_review_and_shopping_evidence_exist():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Recommend over-ear headphones under 150 dollars with balanced sound and good comfort'))
	catalog = build_candidate_catalog(
		[
			StageResult(
				stage_name='review_collection',
				source_type=SourceType.review,
				sources=['rtings.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Philips SHP9500',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/philips/shp9500',
						price_text='Under $100',
						sound_notes='Well-balanced sound profile.',
						comfort_notes='Very comfortable over-ears.',
						evidence='Balanced and comfortable.',
					),
					CandidateEvidence(
						title='Sennheiser HD 560S',
						source_type=SourceType.review,
						source='rtings.com',
						url='https://www.rtings.com/headphones/reviews/sennheiser/hd-560s',
						price_text='Under $200',
						sound_notes='Balanced sound profile.',
						comfort_notes='Lightweight and comfortable.',
						evidence='Neutral and spacious.',
					),
				],
			),
			StageResult(
				stage_name='shopping_collection',
				source_type=SourceType.shopping,
				sources=['adorama.com'],
				prompt='x',
				candidate_evidence=[
					CandidateEvidence(
						title='Philips SHP9500',
						source_type=SourceType.shopping,
						source='adorama.com',
						url='https://www.adorama.com/phsph9500.html',
						price_text='$74.99',
						evidence='Retail listing.',
					)
				],
			),
		]
	)
	report = AssistantReport(
		user_task=plan.user_task,
		mode=plan.mode,
		summary='Summary',
		recommendations=[SuggestedOption(title='Philips SHP9500', why_it_matches='Strong match.')],
		sources=[
			EvidenceSource(
				title='RTINGS roundup',
				url='https://www.rtings.com/headphones/reviews/best/by-price/under-100',
				source_type='review',
				key_takeaway='Balanced and comfortable.',
			),
			EvidenceSource(
				title='Adorama listing',
				url='https://www.adorama.com/phsph9500.html',
				source_type='shopping',
				key_takeaway='Retail price captured.',
			),
		],
	)
	report = _apply_report_confidence(plan, report, catalog)
	assert report.confidence_level == 'high'
	assert report.sources[0].credibility == 'medium'
	assert report.sources[1].credibility == 'medium'


def test_synthesize_report_falls_back_when_model_schema_is_invalid():
	class FailingLLM:
		async def ainvoke(self, messages, output_format=None):
			raise ValueError('invalid structured output')

	plan = fallback_task_plan(ResearchAssistantConfig(task='recommend over-ear headphones under $150'))
	catalog = [
		CandidateCatalogEntry(
			title='Philips SHP9500',
			source_types=[SourceType.review, SourceType.shopping],
			sources=['rtings.com', 'walmart.com'],
			urls=['https://www.rtings.com/headphones/reviews/philips/shp9500', 'https://www.walmart.com/ip/shp9500'],
			price_texts=['$74.99'],
			sound_notes=['Balanced sound from review evidence.'],
			comfort_notes=['Comfortable open-back fit.'],
			evidence_points=['Strong review evidence plus captured retailer price.'],
			evidence_records=[
				CandidateEvidence(
					title='Philips SHP9500',
					source_type=SourceType.review,
					source='RTINGS',
					evidence='Balanced sound and comfort notes.',
					url='https://www.rtings.com/headphones/reviews/philips/shp9500',
				),
				CandidateEvidence(
					title='Philips SHP9500',
					source_type=SourceType.shopping,
					source='Walmart',
					evidence='Retailer price captured.',
					url='https://www.walmart.com/ip/shp9500',
					price_text='$74.99',
				),
			],
		)
	]
	assistant = BrowserResearchAssistant(
		ResearchAssistantConfig(task=plan.user_task, max_recommendations=1),
		llm=FailingLLM(),
	)
	report = asyncio.run(assistant._synthesize_report(plan, 'dossier', catalog))
	assert report.recommendations
	assert report.recommendations[0].title == 'Philips SHP9500'
	assert report.caveats
	assert report.confidence_level in {'medium', 'high'}


def test_apply_recommendation_metadata_adds_confidence_and_coverage():
	ranked = RankedCandidate(
		candidate=build_candidate_catalog(
			[
				StageResult(
					stage_name='review_collection',
					source_type=SourceType.review,
					sources=['rtings.com'],
					prompt='x',
					candidate_evidence=[
						CandidateEvidence(
							title='Philips SHP9500',
							source_type=SourceType.review,
							source='rtings.com',
							url='https://www.rtings.com/headphones/reviews/philips/shp9500',
							price_text='Under $100',
							sound_notes='Well-balanced sound profile.',
							comfort_notes='Very comfortable over-ears.',
							evidence='Balanced and comfortable.',
						)
					],
				),
				StageResult(
					stage_name='shopping_collection',
					source_type=SourceType.shopping,
					sources=['adorama.com'],
					prompt='x',
					candidate_evidence=[
						CandidateEvidence(
							title='Philips SHP9500',
							source_type=SourceType.shopping,
							source='adorama.com',
							url='https://www.adorama.com/phsph9500.html',
							price_text='$74.99',
							evidence='Retail listing.',
						)
					],
				),
			]
		)[0],
		score=9,
		reasons=['Balanced sound evidence', 'Comfort evidence', 'Shopping price captured'],
		review_backed=True,
		shopping_backed=True,
		budget_status='within budget',
	)
	recommendations = _apply_recommendation_metadata(
		[SuggestedOption(title='Philips SHP9500', why_it_matches='Great match.')],
		[ranked],
	)
	assert recommendations[0].confidence_level == 'high'
	assert 'Review, price, and budget evidence all align' in (recommendations[0].confidence_reason or '')
	assert 'Sound-character evidence captured from review sources.' in recommendations[0].evidence_coverage
	assert 'Shopping price or buy-link evidence captured.' in recommendations[0].evidence_coverage


def test_apply_recommendation_metadata_marks_partial_price_support_as_medium():
	ranked = RankedCandidate(
		candidate=build_candidate_catalog(
			[
				StageResult(
					stage_name='review_collection',
					source_type=SourceType.review,
					sources=['rtings.com'],
					prompt='x',
					candidate_evidence=[
						CandidateEvidence(
							title='Sennheiser HD 560S',
							source_type=SourceType.review,
							source='rtings.com',
							url='https://www.rtings.com/headphones/reviews/sennheiser/hd-560s',
							price_text='Under $200',
							sound_notes='Balanced sound profile.',
							comfort_notes='Lightweight and comfortable.',
							evidence='Neutral and spacious.',
						)
					],
				)
			]
		)[0],
		score=7,
		reasons=['Balanced sound evidence', 'Comfort evidence'],
		review_backed=True,
		shopping_backed=False,
		budget_status='budget uncertain',
	)
	recommendations = _apply_recommendation_metadata(
		[SuggestedOption(title='Sennheiser HD 560S', why_it_matches='Good sound-first pick.')],
		[ranked],
	)
	assert recommendations[0].confidence_level == 'medium'
	assert 'Core review evidence is strong' in (recommendations[0].confidence_reason or '')
	assert 'Price evidence captured, but not from a direct shopping listing.' in recommendations[0].evidence_coverage


def test_apply_report_confidence_marks_research_report_high_for_primary_sources():
	plan = fallback_task_plan(ResearchAssistantConfig(task='Investigate whether browser-use supports OpenAI-compatible APIs'))
	report = AssistantReport(
		user_task=plan.user_task,
		mode=plan.mode,
		summary='Summary',
		supporting_findings=['Docs describe Browser Use Cloud auth.', 'Docs distinguish Cloud SDK from open-source API.'],
		sources=[
			EvidenceSource(
				title='Browser Use docs llms.txt',
				url='https://docs.browser-use.com/llms.txt',
				source_type='official_docs',
				key_takeaway='Cloud uses its own API.',
			),
			EvidenceSource(
				title='browser-use README',
				url='https://raw.githubusercontent.com/browser-use/browser-use/main/README.md',
				source_type='github_repo',
				key_takeaway='Repo is the open-source library.',
			),
		],
	)
	report = _apply_report_confidence(plan, report, [])
	assert report.confidence_level == 'high'
	assert report.sources[0].credibility == 'high'
	assert report.sources[1].credibility == 'high'


def test_render_report_includes_confidence_and_source_credibility():
	report = AssistantReport(
		user_task='Investigate x',
		mode=AssistantMode.research,
		summary='Summary',
		confidence_level='medium',
		confidence_reason='Evidence is partial but credible.',
		sources=[
			EvidenceSource(
				title='Docs',
				url='https://docs.browser-use.com/llms.txt',
				source_type='official_docs',
				key_takeaway='Cloud uses its own API.',
				credibility='high',
			)
		],
	)
	text = render_report(report)
	assert 'Confidence: medium | Evidence is partial but credible.' in text
	assert '[official_docs, high] Docs | https://docs.browser-use.com/llms.txt' in text


def test_render_report_includes_recommendation_confidence_and_coverage():
	report = AssistantReport(
		user_task='Recommend x',
		mode=AssistantMode.recommendation,
		summary='Summary',
		recommendations=[
			SuggestedOption(
				title='Philips SHP9500',
				why_it_matches='Strong match.',
				confidence_level='high',
				confidence_reason='Review, price, and budget evidence all align for this option.',
				evidence_coverage=['Sound-character evidence captured from review sources.'],
			)
		],
	)
	text = render_report(report)
	assert 'Confidence: high | Review, price, and budget evidence all align for this option.' in text
	assert 'Coverage: Sound-character evidence captured from review sources.' in text


def test_normalize_report_sources_dedupes_exact_urls_and_takeaways():
	report = AssistantReport(
		user_task='Investigate browser-use APIs',
		mode=AssistantMode.research,
		summary='Summary',
		sources=[
			EvidenceSource(
				title='Docs A',
				url='https://docs.browser-use.com/llms.txt',
				source_type='official_docs',
				key_takeaway='Cloud uses its own API.',
				credibility='high',
			),
			EvidenceSource(
				title='Docs A Duplicate',
				url='https://docs.browser-use.com/llms.txt',
				source_type='official_docs',
				key_takeaway='Cloud uses its own API.',
				credibility='high',
			),
			EvidenceSource(
				title='Docs Similar',
				url='https://docs.browser-use.com/llms-full.txt',
				source_type='official_docs',
				key_takeaway='Cloud uses its own API.',
				credibility='high',
			),
		],
	)
	report = _normalize_report_sources(report)
	assert len(report.sources) == 1
	assert report.sources[0].url == 'https://docs.browser-use.com/llms.txt'


def test_normalize_report_sources_limits_single_domain_in_recommendations():
	report = AssistantReport(
		user_task='Recommend headphones under 1000 CNY',
		mode=AssistantMode.recommendation,
		summary='Summary',
		recommendations=[SuggestedOption(title='Philips SHP9500', why_it_matches='Strong match.')],
		sources=[
			EvidenceSource(
				title='RTINGS under 100',
				url='https://www.rtings.com/headphones/reviews/best/by-price/under-100',
				source_type='review',
				key_takeaway='Balanced sound and comfort.',
				credibility='high',
			),
			EvidenceSource(
				title='RTINGS under 200',
				url='https://www.rtings.com/headphones/reviews/best/by-price/under-200',
				source_type='review',
				key_takeaway='Balanced sound, weaker budget proof.',
				credibility='high',
			),
			EvidenceSource(
				title='RTINGS ANC under 200',
				url='https://www.rtings.com/headphones/reviews/best/noise-cancelling-headphones-under-200',
				source_type='review',
				key_takeaway='ANC option but V-shaped.',
				credibility='high',
			),
			EvidenceSource(
				title='Walmart listing',
				url='https://www.walmart.com/ip/1more-sonoflow-pro',
				source_type='shopping',
				key_takeaway='Direct buy link.',
				credibility='medium',
			),
		],
	)
	report = _normalize_report_sources(report)
	rtings_sources = [source for source in report.sources if 'rtings.com' in source.url]
	assert len(rtings_sources) == 2
	assert any('walmart.com' in source.url for source in report.sources)


def test_resolve_llm_prefers_openai_for_raw_model(monkeypatch):
	monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
	monkeypatch.setenv('OPENAI_BASE_URL', 'https://example.com/v1')
	llm = resolve_llm('gpt-5.4')
	assert isinstance(llm, ChatOpenAI)
	assert llm.model == 'gpt-5.4'
	assert str(llm.base_url) == 'https://example.com/v1'


def test_valid_sources_filters_non_domains():
	assert _valid_sources(['Amazon', 'bestbuy.com', 'https://www.rtings.com', 'Manufacturer product pages']) == [
		'bestbuy.com',
		'https://www.rtings.com',
	]


def test_normalize_stage_sources_prefers_supported_review_sites():
	assert _normalize_stage_sources(
		[],
		['zol.com.cn', 'pchome.net', 'soundguys.com', 'rtings.com', 'head-fi.org'],
		['rtings.com', 'tomsguide.com', 'soundguys.com'],
		SourceType.review,
	) == ['rtings.com', 'tomsguide.com', 'soundguys.com', 'zol.com.cn']


def test_normalize_stage_sources_preserves_explicit_custom_site():
	assert _normalize_stage_sources(
		['head-fi.org'],
		['soundguys.com', 'rtings.com'],
		['rtings.com', 'tomsguide.com'],
		SourceType.review,
	) == ['head-fi.org', 'rtings.com', 'tomsguide.com', 'soundguys.com']


def test_source_priority_prefers_hybrid_sources():
	assert _source_priority_key(SourceType.shopping, 'walmart.com') < _source_priority_key(SourceType.shopping, 'bestbuy.com')
	assert _source_priority_key(SourceType.shopping, 'adorama.com') < _source_priority_key(SourceType.shopping, 'amazon.com')
	assert _source_priority_key(SourceType.review, 'rtings.com') < _source_priority_key(SourceType.review, 'tomsguide.com')
	assert _source_priority_key(SourceType.review, 'tomsguide.com') < _source_priority_key(SourceType.review, 'soundguys.com')
	assert _source_priority_key(SourceType.web, 'https://docs.browser-use.com') < _source_priority_key(SourceType.web, 'bing.com')


def test_source_priority_prefers_domestic_shopping_sources_for_chinese_locale():
	sources = ['walmart.com', 'adorama.com', 'jd.com', 'tmall.com', 'taobao.com']
	sorted_sources = sorted(sources, key=lambda item: _source_priority_key(SourceType.shopping, item, 'zh-CN'))
	assert sorted_sources[:3] == ['jd.com', 'tmall.com', 'taobao.com']
