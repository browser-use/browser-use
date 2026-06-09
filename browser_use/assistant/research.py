from __future__ import annotations

import html
import json
import os
import re
from datetime import date
from enum import Enum
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from pydantic import BaseModel, Field

from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI
from browser_use.agent.views import AgentHistoryList
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage
from browser_use.llm.models import get_llm_by_name


class AssistantMode(str, Enum):
	recommendation = 'recommendation'
	comparison = 'comparison'
	research = 'research'
	generic = 'generic'


class SourceType(str, Enum):
	shopping = 'shopping'
	review = 'review'
	official = 'official'
	web = 'web'


class SuggestedOption(BaseModel):
	title: str
	why_it_matches: str
	url: str | None = None
	price_text: str | None = None
	best_for: str | None = None
	confidence_level: str | None = None
	confidence_reason: str | None = None
	evidence_coverage: list[str] = Field(default_factory=list)
	tradeoffs: list[str] = Field(default_factory=list)


class ShoppingCandidate(BaseModel):
	title: str
	url: str
	price_text: str | None = None
	rating_text: str | None = None
	source: str | None = None


class CandidateEvidence(BaseModel):
	title: str
	source_type: SourceType = SourceType.shopping
	source: str = ''
	evidence: str = ''
	url: str | None = None
	price_text: str | None = None
	rating_text: str | None = None
	sound_notes: str | None = None
	comfort_notes: str | None = None


class CandidateCatalogEntry(BaseModel):
	title: str
	aliases: list[str] = Field(default_factory=list)
	source_types: list[SourceType] = Field(default_factory=list)
	sources: list[str] = Field(default_factory=list)
	urls: list[str] = Field(default_factory=list)
	price_texts: list[str] = Field(default_factory=list)
	rating_texts: list[str] = Field(default_factory=list)
	sound_notes: list[str] = Field(default_factory=list)
	comfort_notes: list[str] = Field(default_factory=list)
	evidence_points: list[str] = Field(default_factory=list)
	evidence_records: list[CandidateEvidence] = Field(default_factory=list)


class RankedCandidate(BaseModel):
	candidate: CandidateCatalogEntry
	score: int
	reasons: list[str] = Field(default_factory=list)
	review_backed: bool = False
	shopping_backed: bool = False
	budget_status: str | None = None


class StageCandidateExtraction(BaseModel):
	candidates: list[CandidateEvidence] = Field(default_factory=list)


class EvidenceSource(BaseModel):
	title: str
	url: str
	source_type: str
	key_takeaway: str
	credibility: str | None = None


class AssistantReport(BaseModel):
	user_task: str
	mode: AssistantMode
	summary: str
	confidence_level: str | None = None
	confidence_reason: str | None = None
	decision_criteria: list[str] = Field(default_factory=list)
	recommendations: list[SuggestedOption] = Field(default_factory=list)
	supporting_findings: list[str] = Field(default_factory=list)
	sources: list[EvidenceSource] = Field(default_factory=list)
	caveats: list[str] = Field(default_factory=list)
	next_steps: list[str] = Field(default_factory=list)


class ResearchAssistantConfig(BaseModel):
	task: str
	model: str | None = None
	locale: str | None = None
	max_steps: int = 18
	llm_timeout: int = 120
	max_actions_per_step: int = 2
	max_recommendations: int = 3
	use_vision: bool = False
	shopping_sites: list[str] = Field(default_factory=list)
	review_sites: list[str] = Field(default_factory=list)
	official_sites: list[str] = Field(default_factory=list)
	web_sites: list[str] = Field(default_factory=list)


class GeneratedStageSpec(BaseModel):
	source_type: SourceType
	source: str
	queries: list[str] = Field(default_factory=list)
	purpose: str | None = None


class TaskPlan(BaseModel):
	user_task: str
	mode: AssistantMode
	locale: str
	topic: str
	budget: str | None = None
	shopping_sources: list[str] = Field(default_factory=list)
	review_sources: list[str] = Field(default_factory=list)
	official_sources: list[str] = Field(default_factory=list)
	web_sources: list[str] = Field(default_factory=list)
	shopping_queries: list[str] = Field(default_factory=list)
	review_queries: list[str] = Field(default_factory=list)
	official_queries: list[str] = Field(default_factory=list)
	web_queries: list[str] = Field(default_factory=list)
	generated_stages: list[GeneratedStageSpec] = Field(default_factory=list)
	decision_criteria: list[str] = Field(default_factory=list)
	required_deliverables: list[str] = Field(default_factory=list)


class StageResult(BaseModel):
	stage_name: str
	source_type: SourceType
	sources: list[str] = Field(default_factory=list)
	initial_urls: list[str] = Field(default_factory=list)
	resolved_urls: list[str] = Field(default_factory=list)
	fetch_mode_used: str = 'browser'
	blocked_reason: str | None = None
	prompt: str
	final_result: str | None = None
	candidate_evidence: list[CandidateEvidence] = Field(default_factory=list)
	visited_urls: list[str] = Field(default_factory=list)
	errors: list[str] = Field(default_factory=list)
	run_error: str | None = None


class AssistantRunArtifacts(BaseModel):
	task_plan: TaskPlan
	stage_results: list[StageResult]
	candidate_catalog: list[CandidateCatalogEntry]
	research_dossier: str
	report: AssistantReport


class SiteAdapter(BaseModel):
	domain: str
	source_type: SourceType
	search_url_template: str | None = None
	query_prefix: str | None = None
	note: str | None = None
	preferred_fetch_mode: str = 'browser'
	result_limit: int = 3
	blocked_markers: list[str] = Field(default_factory=list)
	requires_browser_observation: bool = False
	allowed_domains: list[str] = Field(default_factory=list)


class ResolvedStageTargets(BaseModel):
	initial_urls: list[str] = Field(default_factory=list)
	resolved_urls: list[str] = Field(default_factory=list)
	fetch_mode_used: str = 'browser'
	blocked_reason: str | None = None


def _contains_cjk(text: str) -> bool:
	return bool(re.search(r'[\u3400-\u9fff]', text))


def _normalize_site(site: str) -> str:
	value = site.strip()
	value = re.sub(r'^https?://', '', value, flags=re.IGNORECASE)
	value = value.rstrip('/')
	value = value.split('/', 1)[0]
	return value.lower()


def _unique(values: list[str]) -> list[str]:
	seen: set[str] = set()
	result: list[str] = []
	for value in values:
		text = value.strip()
		if re.match(r'^https?://', text, flags=re.IGNORECASE):
			normalized = text.rstrip('/')
		else:
			normalized = _normalize_site(text) if '.' in text else text
		if normalized and normalized not in seen:
			seen.add(normalized)
			result.append(normalized)
	return result


def _unique_text(values: list[str]) -> list[str]:
	seen: set[str] = set()
	result: list[str] = []
	for value in values:
		text = value.strip()
		if text and text not in seen:
			seen.add(text)
			result.append(text)
	return result


def _is_probable_source(value: str) -> bool:
	text = value.strip()
	if not text:
		return False
	if re.match(r'^https?://', text, flags=re.IGNORECASE):
		return True
	return '.' in text and ' ' not in text


def _valid_sources(values: list[str]) -> list[str]:
	return _unique([value for value in values if _is_probable_source(value)])


def _extract_explicit_urls(text: str) -> list[str]:
	return _unique_text(re.findall(r'https?://[^\s<>"\')]+', text, flags=re.IGNORECASE))


def _extract_explicit_domains(text: str) -> list[str]:
	domains: list[str] = []
	for site_filter in re.findall(r'\bsite:([a-z0-9.-]+\.[a-z]{2,})\b', text, flags=re.IGNORECASE):
		domains.append(_normalize_site(site_filter))
	for domain in re.findall(r'\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b', text, flags=re.IGNORECASE):
		normalized = _normalize_site(domain)
		if normalized.startswith('www.'):
			normalized = normalized[4:]
		domains.append(normalized)
	if re.search(r'\bgithub\b', text, flags=re.IGNORECASE):
		domains.append('github.com')
	return _unique(domains)


def _infer_repo_urls_from_task(text: str, explicit_urls: list[str], explicit_domains: list[str]) -> list[str]:
	repo_urls: list[str] = []
	task_lower = text.lower()
	if 'github repo' not in task_lower:
		return []

	candidate_domains = explicit_domains + [_normalize_site(urlparse(url).netloc) for url in explicit_urls]
	for domain in candidate_domains:
		match = re.fullmatch(r'docs\.([a-z0-9._-]+)\.com', domain)
		if not match:
			continue
		slug = match.group(1)
		repo_urls.append(f'https://github.com/{slug}/{slug}')

	for slug in re.findall(r'\b([a-z0-9][a-z0-9._-]{2,})\s+github repo\b', text, flags=re.IGNORECASE):
		if '.' in slug:
			continue
		repo_urls.append(f'https://github.com/{slug}/{slug}')

	return _unique_text(repo_urls)


def _filter_web_sources_for_explicit_seeds(sources: list[str], seed_sources: list[str]) -> list[str]:
	seed_sites = {_normalize_site(source) for source in seed_sources if _normalize_site(source) != 'bing.com'}
	if not seed_sites:
		return _unique(sources)
	filtered: list[str] = []
	for source in sources:
		normalized = _normalize_site(source)
		if normalized == 'bing.com' or normalized in seed_sites:
			filtered.append(source)
	return _unique(filtered)


def _dedupe_web_sources_preserve_explicit_urls(sources: list[str]) -> list[str]:
	url_domains = {_normalize_site(urlparse(source).netloc) for source in sources if re.match(r'^https?://', source, flags=re.IGNORECASE)}
	deduped: list[str] = []
	for source in sources:
		if not re.match(r'^https?://', source, flags=re.IGNORECASE):
			normalized = _normalize_site(source)
			if normalized in url_domains and normalized != 'bing.com':
				continue
		deduped.append(source)
	return _unique(deduped)


def _supported_source_domains(source_type: SourceType) -> set[str]:
	return {adapter.domain for adapter in SITE_ADAPTERS.values() if adapter.source_type == source_type}


def _normalize_stage_sources(
	user_sources: list[str],
	llm_sources: list[str],
	fallback_sources: list[str],
	source_type: SourceType,
) -> list[str]:
	explicit = _valid_sources(user_sources)
	inferred = _valid_sources(llm_sources)
	fallback = _valid_sources(fallback_sources)
	explicit_domains = {_normalize_site(value) for value in explicit}

	if source_type in {SourceType.official, SourceType.web}:
		return _unique(explicit + inferred + fallback)

	supported = _supported_source_domains(source_type)
	result: list[str] = []

	def add(values: list[str], supported_only: bool) -> None:
		for value in values:
			normalized = _normalize_site(value)
			if supported_only and normalized not in supported:
				continue
			if normalized and normalized not in result:
				result.append(normalized)

	add(explicit, supported_only=False)
	add(inferred, supported_only=True)
	add(fallback, supported_only=True)

	if explicit:
		add(inferred, supported_only=False)

	if result:
		explicit_first = [value for value in result if value in explicit_domains]
		remaining = [value for value in result if value not in explicit_domains]
		remaining.sort(key=lambda item: _source_priority_key(source_type, item))
		return explicit_first + remaining
	return _unique(explicit + inferred + fallback)


def _normalize_generated_stages(
	generated_stages: list[GeneratedStageSpec],
	fallback: TaskPlan,
) -> list[GeneratedStageSpec]:
	normalized: list[GeneratedStageSpec] = []
	seen: set[tuple[str, str, tuple[str, ...]]] = set()
	for stage in generated_stages:
		source_candidates = _valid_sources([stage.source])
		if not source_candidates:
			continue
		source = source_candidates[0]
		queries = _unique_text([clean_query(query) for query in stage.queries if clean_query(query)])
		if not queries:
			default_queries = {
				SourceType.shopping: fallback.shopping_queries,
				SourceType.review: fallback.review_queries,
				SourceType.official: fallback.official_queries,
				SourceType.web: fallback.web_queries,
			}[stage.source_type]
			queries = default_queries[:2]
		key = (stage.source_type.value, _normalize_site(source), tuple(queries[:3]))
		if key in seen:
			continue
		seen.add(key)
		normalized.append(
			GeneratedStageSpec(
				source_type=stage.source_type,
				source=source,
				queries=queries[:3],
				purpose=stage.purpose,
			)
		)
	return normalized[:6]


SITE_ADAPTERS: dict[str, SiteAdapter] = {
	'amazon.com': SiteAdapter(
		domain='amazon.com',
		source_type=SourceType.shopping,
		search_url_template='https://www.amazon.com/s?k={query}',
		note='Amazon search results page',
		preferred_fetch_mode='browser',
		blocked_markers=['sorry! something went wrong', 'automated access to amazon data', 'captcha'],
	),
	'bestbuy.com': SiteAdapter(
		domain='bestbuy.com',
		source_type=SourceType.shopping,
		search_url_template='https://www.bestbuy.com/site/searchpage.jsp?st={query}',
		note='Best Buy on-site search results',
		blocked_markers=['choose a country', 'country selector'],
	),
	'walmart.com': SiteAdapter(
		domain='walmart.com',
		source_type=SourceType.shopping,
		search_url_template='https://www.walmart.com/search?q={query}',
		note='Walmart on-site search results',
		preferred_fetch_mode='hybrid',
		result_limit=5,
		blocked_markers=['human verification', 'verify you are human', 'press & hold'],
	),
	'adorama.com': SiteAdapter(
		domain='adorama.com',
		source_type=SourceType.shopping,
		search_url_template='https://www.adorama.com/l/?searchinfo={query}',
		note='Adorama search results',
		preferred_fetch_mode='hybrid',
		result_limit=5,
	),
	'jd.com': SiteAdapter(
		domain='jd.com',
		source_type=SourceType.shopping,
		search_url_template='https://search.jd.com/Search?keyword={query}',
		note='JD search results',
		blocked_markers=['京东验证', '风险', '验证'],
		requires_browser_observation=True,
		allowed_domains=[
			'jd.com',
			'search.jd.com',
			'passport.jd.com',
			'plogin.m.jd.com',
			'qr.m.jd.com',
			'authcode.jd.com',
			'safe.jd.com',
			'cfe.m.jd.com',
			'storage.360buyimg.com',
			'gias.jd.com',
		],
	),
	'tmall.com': SiteAdapter(
		domain='tmall.com',
		source_type=SourceType.shopping,
		search_url_template='https://list.tmall.com/search_product.htm?q={query}',
		note='Tmall search results',
		requires_browser_observation=True,
		allowed_domains=['tmall.com', 'list.tmall.com', 'taobao.com', 's.taobao.com', 'g.alicdn.com', 'assets.alicdn.com'],
	),
	'taobao.com': SiteAdapter(
		domain='taobao.com',
		source_type=SourceType.shopping,
		search_url_template='https://s.taobao.com/search?q={query}',
		note='Taobao search results',
		requires_browser_observation=True,
		allowed_domains=['taobao.com', 's.taobao.com', 'g.alicdn.com', 'assets.alicdn.com'],
	),
	'rtings.com': SiteAdapter(
		domain='rtings.com',
		source_type=SourceType.review,
		search_url_template='https://www.rtings.com/search?q={query}',
		note='RTINGS site search',
		preferred_fetch_mode='hybrid',
	),
	'soundguys.com': SiteAdapter(
		domain='soundguys.com',
		source_type=SourceType.review,
		search_url_template='https://www.soundguys.com/?s={query}',
		note='SoundGuys site search',
		preferred_fetch_mode='hybrid',
	),
	'thewirecutter.com': SiteAdapter(
		domain='thewirecutter.com',
		source_type=SourceType.review,
		search_url_template='https://www.nytimes.com/wirecutter/search/?s={query}',
		note='Wirecutter search',
	),
	'tomsguide.com': SiteAdapter(
		domain='tomsguide.com',
		source_type=SourceType.review,
		search_url_template='https://www.tomsguide.com/search?searchTerm={query}',
		note='Tom\'s Guide search',
		preferred_fetch_mode='hybrid',
	),
	'sspai.com': SiteAdapter(
		domain='sspai.com',
		source_type=SourceType.review,
		search_url_template='https://sspai.com/search/post/{query}',
		note='SSPAI post search',
		preferred_fetch_mode='hybrid',
	),
	'ifanr.com': SiteAdapter(
		domain='ifanr.com',
		source_type=SourceType.review,
		search_url_template='https://www.ifanr.com/category/review',
		note='ifanr review categories',
		preferred_fetch_mode='hybrid',
		result_limit=5,
	),
	'zol.com.cn': SiteAdapter(
		domain='zol.com.cn',
		source_type=SourceType.review,
		search_url_template='https://sou.zol.com.cn/s/all-{query}.html',
		note='ZOL search',
	),
	'bilibili.com': SiteAdapter(
		domain='bilibili.com',
		source_type=SourceType.review,
		search_url_template='https://search.bilibili.com/all?keyword={query}',
		note='Bilibili search',
	),
	'zhihu.com': SiteAdapter(
		domain='zhihu.com',
		source_type=SourceType.review,
		search_url_template='https://www.zhihu.com/search?type=content&q={query}',
		note='Zhihu search',
	),
	'bing.com': SiteAdapter(
		domain='bing.com',
		source_type=SourceType.web,
		search_url_template='https://www.bing.com/search?q={query}',
		note='Bing general web search',
		preferred_fetch_mode='hybrid',
		result_limit=4,
	),
}


def infer_locale(task: str, locale: str | None = None) -> str:
	if locale:
		return locale
	if _contains_cjk(task):
		return 'zh-CN'
	return 'en-US'


def infer_mode(task: str) -> AssistantMode:
	text = task.lower()
	if re.search(r'\b(compare|comparison|vs|versus)\b', text):
		return AssistantMode.comparison
	if re.search(r'\b(recommend|best|buy|purchase|choose)\b', text):
		return AssistantMode.recommendation
	if re.search(r'\b(research|investigate|analyze|analysis|survey)\b', text):
		return AssistantMode.research
	if _contains_cjk(task) and re.search(r'\d', task):
		return AssistantMode.recommendation
	return AssistantMode.generic


def default_sources(mode: AssistantMode, locale: str) -> dict[SourceType, list[str]]:
	if locale == 'zh-CN':
		shopping = ['jd.com', 'tmall.com', 'taobao.com', 'walmart.com', 'adorama.com']
		reviews = ['sspai.com', 'ifanr.com', 'zol.com.cn', 'zhihu.com', 'bilibili.com', 'rtings.com', 'tomsguide.com', 'soundguys.com']
		official = ['mi.com', 'huawei.com', 'sony.com']
	else:
		shopping = ['amazon.com', 'walmart.com', 'adorama.com', 'bestbuy.com']
		reviews = ['rtings.com', 'tomsguide.com', 'soundguys.com', 'thewirecutter.com']
		official = ['sony.com', 'bose.com', 'sennheiser-hearing.com']

	web = ['bing.com']

	if mode == AssistantMode.research:
		return {SourceType.shopping: [], SourceType.review: [], SourceType.official: [], SourceType.web: web}
	if mode in {AssistantMode.recommendation, AssistantMode.comparison}:
		return {SourceType.shopping: shopping, SourceType.review: reviews, SourceType.official: [], SourceType.web: []}
	return {SourceType.shopping: [], SourceType.review: [], SourceType.official: [], SourceType.web: web}


def source_to_url(site: str) -> str:
	if site.startswith('http://') or site.startswith('https://'):
		return site
	return f'https://{site}'


def get_site_adapter(site: str, source_type: SourceType) -> SiteAdapter:
	normalized = _normalize_site(site)
	adapter = SITE_ADAPTERS.get(normalized)
	if adapter is not None:
		return adapter
	return SiteAdapter(domain=normalized, source_type=source_type, search_url_template=None, note='Homepage fallback')


def _requires_browser_observation(source_type: SourceType, sources: list[str]) -> bool:
	if source_type != SourceType.shopping:
		return False
	return any(get_site_adapter(source, source_type).requires_browser_observation for source in sources)


def _stage_use_vision(config: ResearchAssistantConfig, source_type: SourceType, sources: list[str]) -> bool | str:
	if config.use_vision:
		return True
	if _requires_browser_observation(source_type, sources):
		return 'auto'
	return False


def clean_query(query: str) -> str:
	cleaned = query.replace('[model name]', '').replace('(model name)', '').strip()
	cleaned = re.sub(r'\s+', ' ', cleaned)
	return cleaned


def _legacy_adapt_query_for_source(query: str, source: str) -> str:
	cleaned = clean_query(query)
	normalized_source = _normalize_site(source)
	english_shopping_sites = {'amazon.com', 'walmart.com', 'adorama.com', 'bestbuy.com'}
	english_review_sites = {'rtings.com', 'soundguys.com', 'thewirecutter.com', 'tomsguide.com'}

	if _contains_cjk(cleaned) and normalized_source in english_shopping_sites | english_review_sites:
		replacements = {
			'头戴式耳机': 'over-ear headphones',
			'头戴耳机': 'over-ear headphones',
			'头戴式': 'over-ear',
			'头戴': 'over-ear',
			'耳机': 'headphones',
			'降噪': 'noise cancelling',
			'均衡声音': 'balanced sound',
			'均衡': 'balanced',
			'中性': 'neutral',
			'舒适度': 'comfort',
			'舒适': 'comfortable',
			'佩戴': 'wear',
			'测评': 'review',
			'评测': 'review',
			'推荐': 'best',
			'自营': '',
			'旗舰店': '',
			'官方旗舰店': '',
			'京东': '',
			'天猫': '',
			'淘宝': '',
			'苏宁': '',
		}
		adapted = cleaned
		for old, new in replacements.items():
			adapted = adapted.replace(old, f' {new} ')
		budget_limit = _query_budget_limit(cleaned)
		if budget_limit is not None and _currency_code(cleaned) == 'cny':
			usd_budget = int(_convert_currency_for_budget(budget_limit, 'cny', 'usd') or 0)
			if usd_budget > 0:
				adapted += f' under {usd_budget} dollars'
		cleaned = re.sub(r'\d+(?:\.\d+)?\s*元(?:以内|以下|左右)?', ' ', adapted)
		cleaned = re.sub(r'\b(?:jd|tmall|taobao|suning)\b', ' ', cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r'\s+', ' ', cleaned).strip()
	return cleaned


def adapt_query_for_source(query: str, source: str) -> str:
	cleaned = clean_query(query)
	normalized_source = _normalize_site(source)
	english_shopping_sites = {'amazon.com', 'walmart.com', 'adorama.com', 'bestbuy.com'}
	english_review_sites = {'rtings.com', 'soundguys.com', 'thewirecutter.com', 'tomsguide.com'}

	if _contains_cjk(cleaned) and normalized_source in english_shopping_sites | english_review_sites:
		hints = _query_hints(cleaned)
		replacements = {
			'头戴式耳机': 'over-ear headphones',
			'头戴耳机': 'over-ear headphones',
			'头戴式': 'over-ear',
			'头戴': 'over-ear',
			'耳机': 'headphones',
			'降噪': 'noise cancelling',
			'均衡声音': 'balanced sound',
			'均衡': 'balanced',
			'中性': 'neutral',
			'舒适度': 'comfort',
			'舒适': 'comfortable',
			'佩戴': 'wear',
			'测评': 'review',
			'评测': 'review',
			'推荐': 'best',
			'自营': '',
			'旗舰店': '',
			'官方旗舰店': '',
			'京东': '',
			'天猫': '',
			'淘宝': '',
			'苏宁': '',
		}
		adapted = cleaned
		for old, new in replacements.items():
			adapted = adapted.replace(old, f' {new} ')
		budget_limit = _query_budget_limit(cleaned)
		if budget_limit is not None and _currency_code(cleaned) == 'cny':
			usd_budget = int(_convert_currency_for_budget(budget_limit, 'cny', 'usd') or 0)
			if usd_budget > 0:
				adapted += f' under {usd_budget} dollars'
		cleaned = re.sub(r'\d+(?:\.\d+)?\s*元(?:以内|以下|左右)?', ' ', adapted)
		cleaned = re.sub(r'\b(?:jd|tmall|taobao|suning)\b', ' ', cleaned, flags=re.IGNORECASE)
		cleaned = re.sub(r'\s+', ' ', cleaned).strip()
		if normalized_source in english_review_sites:
			parts: list[str] = ['best']
			parts.append('over-ear headphones' if hints['over_ear'] else 'headphones')
			if hints['balanced']:
				parts.append('balanced sound')
			if hints['comfort']:
				parts.append('comfort')
			if hints['anc']:
				parts.append('noise cancelling')
			if budget_limit is not None and _currency_code(query) == 'cny':
				usd_budget = int(_convert_currency_for_budget(budget_limit, 'cny', 'usd') or 0)
				if usd_budget > 0:
					parts.append(f'under {usd_budget} dollars')
			parts.append('review')
			cleaned = ' '.join(_unique_text(parts))
	return cleaned


def build_source_entry_urls(source_type: SourceType, sources: list[str], queries: list[str]) -> list[str]:
	entry_urls: list[str] = []

	for source in sources:
		candidate_queries = [adapt_query_for_source(query, source) for query in queries if adapt_query_for_source(query, source)]
		default_query = candidate_queries[0] if candidate_queries else ''
		adapter = get_site_adapter(source, source_type)
		if adapter.search_url_template and default_query:
			entry_urls.append(adapter.search_url_template.format(query=quote_plus(default_query)))
		else:
			entry_urls.append(source_to_url(source))

	return entry_urls


def normalize_stage_queries(queries: list[str], sources: list[str]) -> list[str]:
	normalized_queries: list[str] = []
	for query in queries:
		cleaned = query
		for source in sources:
			cleaned = re.sub(rf'site:{re.escape(source)}\s*', '', cleaned, flags=re.IGNORECASE)
		cleaned = cleaned.strip()
		if cleaned and cleaned not in normalized_queries:
			normalized_queries.append(cleaned)
	return normalized_queries


def _extract_hrefs(html_text: str) -> list[str]:
	return re.findall(r'href=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE)


def _strip_tracking(url: str) -> str:
	if '#' in url:
		url = url.split('#', 1)[0]
	return html.unescape(url)


def _absolute_site_url(site: str, href: str) -> str | None:
	href = _strip_tracking(href.strip())
	if not href or href.startswith(('javascript:', 'mailto:', 'tel:')):
		return None
	if href.startswith('//'):
		href = f'https:{href}'
	elif href.startswith('/'):
		href = urljoin(f'https://{site}', href)
	parsed = urlparse(href)
	if parsed.scheme not in {'http', 'https'}:
		return None
	netloc = parsed.netloc.lower()
	if site not in netloc:
		return None
	return href


def detect_blocked_page(site: str, html_text: str) -> str | None:
	lowered = html_text.lower()
	markers = get_site_adapter(site, SourceType.shopping).blocked_markers
	if not markers and site == 'walmart.com':
		markers = ['human verification', 'verify you are human', 'press & hold']
	if not markers and site == 'bestbuy.com':
		markers = ['choose a country', 'country selector']
	for marker in markers:
		if marker in lowered:
			return marker
	return None


def _keyword_tokens(query: str | None) -> list[str]:
	if not query:
		return []
	return [
		token
		for token in re.findall(r'[a-z0-9]+', query.lower())
		if len(token) >= 3 and token not in {'with', 'under', 'good', 'review', 'sound', 'comfort'}
	]


IFANR_REVIEW_API_URLS = [
	'https://sso.ifanr.com/api/v5/wp/article/?post_category=%E8%AF%84%E6%B5%8B',
	'https://sso.ifanr.com/api/v5/wp/article/?post_category=%E6%A8%A1%E8%8C%83%E8%AF%84%E6%B5%8B',
]


def _candidate_score(url: str, query: str | None) -> tuple[int, int]:
	tokens = _keyword_tokens(query)
	text = url.lower()
	matches = sum(1 for token in tokens if token in text)
	if query:
		lowered_query = query.lower()
		if 'headphone' in lowered_query and 'earbud' in text:
			matches -= 2
		if 'over-ear' in lowered_query and 'earbud' in text:
			matches -= 2
	return (matches, -len(url))


def _review_candidate_matches_query(candidate: CandidateEvidence, query: str | None) -> bool:
	if not query:
		return True
	hints = _query_hints(query)
	text = ' '.join(
		part
		for part in [
			candidate.title,
			candidate.evidence,
			candidate.sound_notes or '',
			candidate.comfort_notes or '',
			candidate.url or '',
		]
		if part
	).lower()
	if hints['over_ear'] and any(
		token in text for token in ('earbud', 'earbuds', 'in-ear', 'in ear', 'open ear', 'clip-on', '真无线', '入耳', '半入耳', '耳夹', '开放真无线', '耳塞', '挂耳')
	):
		return False
	if hints['headphones'] and not hints['earbuds'] and any(
		token in text for token in ('earbud', 'earbuds', 'speaker', 'speakers', 'microphone', 'mic pro', '真无线', '入耳', '半入耳', '耳夹', '耳塞')
	):
		return False
	if hints['over_ear'] and _contains_cjk(query):
		has_positive_over_ear_signal = any(
			token in text for token in ('over-ear', 'over ear', 'around-ear', 'headphones', '头戴', '包耳', '罩耳', '头梁')
		)
		has_generic_earphone_signal = any(token in text for token in ('耳机', 'headphone', 'audio'))
		if has_generic_earphone_signal and not has_positive_over_ear_signal:
			return False
	if not hints['gaming'] and 'gaming' in text and any(token in text for token in ('headset', 'gaming headset')):
		return False
	return True


def _shopping_has_model_signal(text: str) -> bool:
	tokens = re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', text.lower())
	return any(any(char.isdigit() for char in token) or '-' in token for token in tokens)


def _shopping_signal_score(candidate: ShoppingCandidate, query: str | None) -> int:
	text = f'{candidate.title} {candidate.url}'.lower()
	trusted_brands = (
		'sony', 'audio-technica', 'sennheiser', 'bose', 'anker', 'soundcore', '1more', 'koss', 'panasonic', 'jlab',
		'oneodio', 'jbl', 'edifier', 'philips', 'beyerdynamic', 'akg', 'skullcandy', 'nothing', 'rode', 'meze',
	)
	signal = 0
	has_trusted_brand = any(brand in text for brand in trusted_brands)
	has_model_signal = _shopping_has_model_signal(candidate.title)
	if has_trusted_brand:
		signal += 2
	if has_model_signal:
		signal += 2
	if any(token in text for token in ('monitor', 'professional', 'reference', 'studio', 'open-back', 'closed-back')):
		signal += 1
	if text.startswith(('over ear headphones', 'bluetooth headphones', 'wireless headphones', 'headphones over ear')):
		signal -= 3
	marketing_phrase_hits = sum(
		1
		for phrase in (
			'120h playtime', '100h playtime', '72 h playtime', 'low latency', 'rgb', 'led', 'deep bass',
			'knob control', 'card insertion', 'shareports', 'dual plugs', 'sports wireless', 'hifi stereo',
			'transparency mode', 'spatial audio', 'protein earpads',
		)
		if phrase in text
	)
	signal -= marketing_phrase_hits
	if not has_trusted_brand and not has_model_signal:
		signal -= 4
	if candidate.title.count(',') >= 3 and len(candidate.title.split()) >= 10:
		signal -= 2
	if query:
		lowered_query = query.lower()
		if 'over-ear' in lowered_query and ('over ear' in text or 'over-ear' in text):
			signal += 1
	return signal


def _shopping_candidate_score(candidate: ShoppingCandidate, query: str | None) -> tuple[int, float, int]:
	text = f'{candidate.title} {candidate.url}'.lower()
	tokens = _keyword_tokens(query)
	matches = sum(1 for token in tokens if token in text)
	trusted_brands = (
		'sony', 'audio-technica', 'sennheiser', 'bose', 'anker', 'soundcore', '1more', 'koss', 'panasonic', 'jlab',
		'oneodio', 'jbl', 'edifier', 'philips', 'beyerdynamic', 'akg', 'skullcandy', 'nothing',
	)
	for negative in ('earbud', 'earbuds', 'kid', 'kids', 'controller'):
		if negative in text:
			matches -= 3
	for penalty in ('5-pack', '5 pack', '10-pack', 'bundle', 'case'):
		if penalty in text:
			matches -= 2
	for brand in trusted_brands:
		if brand in text:
			matches += 2
	for penalty in (
		'120h playtime', '100h playtime', '72 h playtime', 'low latency', 'rgb', 'led', 'deep bass',
		'knob control', 'card insertion', 'shareports', 'dual plugs', 'sports wireless', 'hifi stereo',
	):
		if penalty in text:
			matches -= 2
	if not any(brand in text for brand in trusted_brands):
		if text.startswith(('over ear headphones', 'bluetooth headphones', 'wireless headphones', 'headphones over ear')):
			matches -= 3
	if 'monitor' in text or 'professional' in text:
		matches += 2
	matches += _shopping_signal_score(candidate, query)
	if query:
		lowered_query = query.lower()
		if 'headphone' in lowered_query and 'headphone' in text:
			matches += 1
		if 'over-ear' in lowered_query and ('over ear' in text or 'over-ear' in text):
			matches += 2
	rating_value = 0.0
	review_count = 0
	if candidate.rating_text:
		match = re.search(r'(\d+(?:\.\d+)?)', candidate.rating_text)
		if match:
			rating_value = float(match.group(1))
		review_match = re.search(r'\((\d+)\s+reviews\)', candidate.rating_text)
		if review_match:
			review_count = int(review_match.group(1))
	if review_count >= 10:
		matches += 1
	elif 0 < review_count <= 2:
		matches -= 1
	return (matches, rating_value, review_count, -len(candidate.title))


def _candidate_identity_tokens(title: str) -> list[str]:
	tokens = re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', title.lower())
	stopwords = {
		'headphone', 'headphones', 'wireless', 'wired', 'bluetooth', 'noise', 'cancelling', 'canceling', 'over', 'ear',
		'over-ear', 'on-ear', 'in-ear',
		'closed', 'back', 'open', 'studio', 'professional', 'monitor', 'with', 'and', 'the', 'for', 'black', 'white',
		'silver', 'blue', 'pink', 'red', 'gray', 'grey', 'green', 'brown', 'pro', 'anc', 'audio', 'sound', 'stereo',
		'lightweight', 'foldable', 'home', 'office', 'microphone', 'mic', 'battery', 'hour', 'playtime',
	}
	filtered = [token for token in tokens if token not in stopwords]
	model_tokens = [token for token in filtered if any(char.isdigit() for char in token) or '-' in token]
	if model_tokens:
		brand_token = filtered[0] if filtered else None
		identity = ([brand_token] if brand_token else []) + model_tokens[:3]
		return _unique_text(identity)
	return filtered[:4]


def _candidate_identity_key(title: str) -> str:
	tokens = _candidate_identity_tokens(title)
	return ' '.join(tokens) if tokens else re.sub(r'\s+', ' ', title.lower()).strip()


def _budget_status_kind(status: str | None) -> str | None:
	if not status:
		return None
	lowered = status.lower()
	if lowered.startswith('within budget'):
		return 'within'
	if lowered.startswith('over budget'):
		return 'over'
	return 'other'


def _candidate_model_fragments(title: str) -> set[str]:
	fragments: set[str] = set()
	for token in re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', title.lower()):
		if not any(char.isdigit() for char in token):
			continue
		compact = token.replace('-', '')
		if compact:
			fragments.add(compact)
		suffix_match = re.search(r'(\d+[a-z]*)$', compact)
		if suffix_match and len(suffix_match.group(1)) >= 3:
			fragments.add(suffix_match.group(1))
	return fragments


def _candidate_cross_entry_match_score(target_title: str, candidate_title: str) -> int:
	if _candidate_identity_key(target_title) == _candidate_identity_key(candidate_title):
		return 100

	target_token_list = _candidate_identity_tokens(target_title)
	candidate_token_list = _candidate_identity_tokens(candidate_title)
	target_tokens = set(target_token_list)
	candidate_tokens = set(candidate_token_list)
	score = 0
	if target_token_list and candidate_token_list and target_token_list[0] == candidate_token_list[0]:
		score += 2
	score += 2 * len(target_tokens & candidate_tokens)

	target_models = _candidate_model_fragments(target_title)
	candidate_models = _candidate_model_fragments(candidate_title)
	has_model_match = False
	for target_model in target_models:
		for candidate_model in candidate_models:
			if target_model == candidate_model:
				has_model_match = True
				score = max(score, 6)
			elif len(target_model) >= 4 and len(candidate_model) >= 4 and (
				target_model in candidate_model or candidate_model in target_model
			):
				has_model_match = True
				score = max(score, 5)

	if target_models or candidate_models:
		if not has_model_match:
			return 0
	elif not (target_token_list and candidate_token_list and target_token_list[0] == candidate_token_list[0] and len(target_tokens & candidate_tokens) >= 2):
		return 0

	return score


def _query_budget_limit(query: str | None) -> float | None:
	if not query:
		return None
	text = query.lower().replace(',', '')
	for pattern in (
		r'[$€£¥]\s*(\d+(?:\.\d+)?)',
		r'\b(?:under|below|within|up to|less than|under about)\s+(\d+(?:\.\d+)?)\b',
		r'\b(\d+(?:\.\d+)?)\s*(?:usd|dollars?|eur|gbp|rmb|cny|yuan)\b',
		r'(\d+(?:\.\d+)?)\s*元\s*(?:以内|以下|左右)?',
	):
		match = re.search(pattern, text, flags=re.IGNORECASE)
		if match:
			return float(match.group(1))
	return None


def _extract_budget_text(query: str | None) -> str | None:
	if not query:
		return None
	for pattern in (
		r'[$€£¥]\s*\d[\d,]*(?:\.\d+)?',
		r'\b(?:under|below|within|up to|less than|under about)\s+\$?\d[\d,]*(?:\.\d+)?(?:\s*(?:usd|dollars?|eur|gbp|rmb|cny|yuan))?',
		r'\d[\d,]*(?:\.\d+)?\s*(?:usd|dollars?|eur|gbp|rmb|cny|yuan)',
		r'\d[\d,]*(?:\.\d+)?\s*元(?:以内|以下|左右)?',
	):
		match = re.search(pattern, query, flags=re.IGNORECASE)
		if match:
			return re.sub(r'\s+', ' ', match.group(0)).strip()
	return None


def _price_value(price_text: str | None) -> float | None:
	if not price_text:
		return None
	match = re.search(r'(\d+(?:\.\d+)?)', price_text.replace(',', ''))
	if not match:
		return None
	return float(match.group(1))


def _currency_code(text: str | None) -> str | None:
	if not text:
		return None
	lowered = text.lower()
	if '$' in text or 'usd' in lowered or 'dollar' in lowered:
		return 'usd'
	if '€' in text or 'eur' in lowered:
		return 'eur'
	if '£' in text or 'gbp' in lowered or 'pound' in lowered:
		return 'gbp'
	if '¥' in text or 'cny' in lowered or 'rmb' in lowered or '人民币' in text or '元' in text:
		return 'cny'
	return None


def _convert_currency_for_budget(value: float, from_currency: str | None, to_currency: str | None) -> float | None:
	if from_currency is None or to_currency is None or from_currency == to_currency:
		return value
	rough_rates = {
		('usd', 'cny'): 7.0,
		('cny', 'usd'): 1 / 7.0,
	}
	rate = rough_rates.get((from_currency, to_currency))
	if rate is None:
		return None
	return value * rate


def _extract_price_hint(text: str | None) -> str | None:
	if not text:
		return None
	match = re.search(r'(under\s+\$\s*\d+(?:\.\d+)?)', text, flags=re.IGNORECASE)
	if match:
		return re.sub(r'\s+', ' ', match.group(1)).strip().replace('$ ', '$').title()
	match = re.search(r'(\$\s*\d+(?:\.\d+)?)', text)
	if match:
		return match.group(1).replace('$ ', '$')
	match = re.search(r'(\d+(?:\.\d+)?)\s*元\s*(?:以内|以下|左右)?', text)
	if match:
		return f'{match.group(1)}元'
	return None


def _ifanr_article_score(title: str, excerpt: str, url: str, query: str | None) -> int:
	text = ' '.join(part for part in [title, excerpt, url] if part).lower()
	score = sum(1 for token in _keyword_tokens(query) if token in text)
	if not query:
		return score

	hints = _query_hints(query)
	if hints['headphones']:
		if any(token in text for token in ('耳机', 'headphone', 'headphones', 'airpods', 'sony', 'bose', 'sonos', 'wh-', 'wf-', 'buds')):
			score += 2
		if any(token in text for token in ('soundbar', 'speaker', 'speakers', '条形音响', '音响')):
			score -= 3
		if any(token in text for token in ('手机', 'phone', 'iphone', '平板', '电脑', 'macbook', '折叠屏', '无人机')):
			score -= 4
	if hints['over_ear']:
		if any(token in text for token in ('头戴', 'over-ear', 'over ear', 'headphones', 'wh-', 'qc ultra', 'airpods max', 'sonos ace', '罩耳', '包耳')):
			score += 4
		if any(token in text for token in ('airpods pro', 'wf-', 'earbud', 'earbuds', '入耳', '真无线', '耳夹', '开放式')):
			score -= 5
	if hints['earbuds']:
		if any(token in text for token in ('airpods pro', 'wf-', 'earbud', 'earbuds', '入耳', '真无线', '耳夹')):
			score += 4
		if any(token in text for token in ('头戴', 'wh-', 'airpods max', 'qc ultra', '罩耳', '包耳')):
			score -= 4
	if hints['anc'] and any(token in text for token in ('降噪', 'noise cancelling', 'noise-cancelling', 'anc')):
		score += 2
	if hints['balanced'] and any(token in text for token in ('均衡', '中性', 'balanced', 'neutral')):
		score += 1
	if hints['comfort'] and any(token in text for token in ('舒适', '佩戴', 'comfortable', 'comfort', 'lightweight')):
		score += 1
	if any(token in text for token in ('评测', '体验', '上手', 'review')):
		score += 1
	return score


def _query_hints(query: str) -> dict[str, bool]:
	lowered = query.lower()
	return {
		'headphones': any(token in lowered for token in ('headphone', 'headphones', '\u8033\u673a')),
		'over_ear': any(token in lowered for token in ('over-ear', 'over ear', '\u5934\u6234')),
		'earbuds': any(token in lowered for token in ('earbud', 'earbuds', 'in-ear', 'in ear', '\u5165\u8033', '\u771f\u65e0\u7ebf', '\u534a\u5165\u8033', '\u8033\u5939')),
		'balanced': any(token in lowered for token in ('balanced', 'neutral', '\u5747\u8861', '\u4e2d\u6027')),
		'comfort': any(token in lowered for token in ('comfort', 'comfortable', '\u8212\u9002')),
		'anc': any(token in lowered for token in ('noise cancelling', 'noise-cancelling', 'anc', '\u964d\u566a')),
		'gaming': any(token in lowered for token in ('gaming', 'gamer', '\u6e38\u620f')),
	}


def _candidate_catalog_text(candidate: CandidateCatalogEntry) -> str:
	return ' '.join(
		[
			candidate.title,
			*candidate.aliases,
			*candidate.price_texts,
			*candidate.rating_texts,
			*candidate.sound_notes,
			*candidate.comfort_notes,
			*candidate.evidence_points,
		]
	).lower()


def _text_has_any(text: str, tokens: tuple[str, ...]) -> bool:
	return any(token in text for token in tokens)


def extract_ifanr_api_candidate_urls(payload: dict, query: str | None = None, limit: int = 3) -> list[str]:
	items = payload.get('objects')
	if not isinstance(items, list):
		return []

	scored: list[tuple[int, str]] = []
	for item in items:
		if not isinstance(item, dict):
			continue
		url = str(item.get('post_url') or '').strip()
		if not url:
			continue
		parsed = urlparse(url)
		if parsed.netloc and 'ifanr.com' not in parsed.netloc:
			continue
		if not re.fullmatch(r'/\d+', parsed.path):
			continue
		title = html.unescape(str(item.get('post_title') or '')).strip()
		excerpt = html.unescape(str(item.get('post_excerpt') or '')).strip()
		text = f'{title} {excerpt}'.lower()
		if query:
			hints = _query_hints(query)
			if hints['headphones']:
				has_headphone_signal = any(
					token in text
					for token in ('耳机', 'headphone', 'headphones', 'airpods', 'sony', 'bose', 'sonos ace', 'wh-', 'wf-', 'buds')
				)
				if not has_headphone_signal:
					continue
			if hints['over_ear']:
				has_over_ear_signal = any(
					token in text
					for token in ('头戴', 'over-ear', 'over ear', 'headphones', 'wh-', 'qc ultra', 'airpods max', 'sonos ace', '罩耳', '包耳')
				)
				if not has_over_ear_signal:
					continue
			if hints['earbuds']:
				has_earbud_signal = any(
					token in text for token in ('airpods pro', 'wf-', 'earbud', 'earbuds', '入耳', '真无线', '耳夹')
				)
				if not has_earbud_signal:
					continue
		score = _ifanr_article_score(title, excerpt, url, query)
		scored.append((score, url))

	if not scored:
		return []

	scored.sort(key=lambda item: (-item[0], len(item[1])))
	positive = [url for score, url in scored if score > 0]
	if positive:
		return _unique_text(positive)[:limit]
	return _unique_text([url for _, url in scored])[:limit]


def _ifanr_review_candidate_matches_query(candidate: CandidateEvidence, query: str | None) -> bool:
	if not query:
		return True
	hints = _query_hints(query)
	text = ' '.join(
		part
		for part in [
			candidate.title,
			candidate.evidence,
			candidate.sound_notes or '',
			candidate.comfort_notes or '',
			candidate.url or '',
		]
		if part
	).lower()
	if hints['headphones']:
		has_headphone_signal = any(
			token in text
			for token in ('耳机', 'headphone', 'headphones', 'airpods', 'wh-', 'wf-', 'bose', 'sony', 'sonos ace', '头戴', '罩耳', '包耳')
		)
		if not has_headphone_signal:
			return False
		if any(token in text for token in ('手机', 'phone', 'iphone', '折叠屏', 'macbook', '电脑', '平板', '无人机', '云台', '相机', '音响', 'soundbar', 'speaker')):
			if not any(token in text for token in ('耳机', 'headphone', 'headphones', 'airpods', 'wh-', 'wf-', '头戴', '罩耳', '包耳')):
				return False
	if hints['over_ear']:
		return any(token in text for token in ('头戴', 'over-ear', 'over ear', 'headphones', 'wh-', 'qc ultra', 'airpods max', 'sonos ace', '罩耳', '包耳'))
	if hints['earbuds']:
		return any(token in text for token in ('airpods pro', 'wf-', 'earbud', 'earbuds', '入耳', '真无线', '耳夹'))
	return True


def rank_candidate_catalog(plan: TaskPlan, candidate_catalog: list[CandidateCatalogEntry]) -> list[RankedCandidate]:
	hints = _query_hints(plan.user_task)
	budget_query = plan.budget or plan.user_task
	budget_limit = _query_budget_limit(budget_query)
	budget_currency = _currency_code(budget_query)
	ranked: list[RankedCandidate] = []

	for candidate in candidate_catalog:
		text = _candidate_catalog_text(candidate)
		score = 0
		reasons: list[str] = []
		review_backed = SourceType.review in candidate.source_types
		shopping_backed = SourceType.shopping in candidate.source_types
		budget_status: str | None = None

		if review_backed:
			score += 8
			reasons.append('Has review-site evidence.')
		if shopping_backed:
			score += 4
			reasons.append('Has shopping-site price or buy-link evidence.')
		if review_backed and shopping_backed:
			score += 5
			reasons.append('Cross-checked across retailer and review sources.')

		score += min(3, max(0, len(candidate.sources) - 1))
		score += min(4, len(candidate.evidence_points) + len(candidate.sound_notes) + len(candidate.comfort_notes))

		if hints['headphones'] and _text_has_any(text, ('headphone', 'headphones', '耳机')):
			score += 2
		if hints['over_ear'] and _text_has_any(text, ('真无线', '半入耳', '耳夹', '耳塞', '挂耳')):
			score -= 8
			reasons.append('Looks like a true-wireless or non-over-ear model, not over-ear.')
		if hints['earbuds'] and _text_has_any(text, ('真无线', '半入耳', '耳夹', '耳塞')):
			score += 5
		if hints['over_ear']:
			if _text_has_any(text, ('over-ear', 'over ear', 'around-ear', '头戴')):
				score += 5
				reasons.append('Matches the over-ear form factor.')
			if _text_has_any(text, ('earbud', 'earbuds', 'in-ear', 'in ear', '入耳')):
				score -= 8
				reasons.append('Looks like an earbud or in-ear model, not over-ear.')
		if hints['earbuds']:
			if _text_has_any(text, ('earbud', 'earbuds', 'in-ear', 'in ear', '入耳')):
				score += 5
			if _text_has_any(text, ('over-ear', 'over ear', 'around-ear', '头戴')):
				score -= 6

		if not hints['gaming'] and _text_has_any(text, ('gaming', 'gamer', '游戏')):
			score -= 5
			reasons.append('Gaming-oriented positioning is a weaker match for this task.')
		if _text_has_any(text, ('kid', 'kids', 'children', '儿童', 'bundle', '5-pack', '10-pack', 'controller', 'replacement')):
			score -= 6
			reasons.append('Looks like a bundle/accessory or the wrong product category.')

		if hints['balanced']:
			if _text_has_any(text, ('balanced sound', 'balanced tuning', 'balanced sound profile', 'well-balanced', 'neutral', 'natural')):
				score += 6
				reasons.append('Evidence points to balanced or neutral sound.')
			if _text_has_any(text, ('v-shaped', 'bass-heavy', 'boomy', 'muddy', 'recessed mids')):
				score -= 6
				reasons.append('Evidence points to a bass-heavy or v-shaped tuning.')
		elif _text_has_any(text, ('balanced sound', 'balanced tuning', 'well-balanced', 'neutral')):
			score += 2

		if hints['comfort']:
			if _text_has_any(text, ('comfortable', 'comfort', 'lightweight', 'well-padded', 'soft pads', 'wear for long')):
				score += 5
				reasons.append('Evidence points to good comfort for longer listening.')
			if _text_has_any(text, ('uncomfortable', 'clamp', 'clamping force', 'fatiguing', 'hot on ears', 'heavy')):
				score -= 4
				reasons.append('Evidence suggests comfort tradeoffs.')
		elif _text_has_any(text, ('comfortable', 'comfort', 'lightweight', 'well-padded')):
			score += 2

		if hints['anc'] and _text_has_any(text, ('noise cancelling', 'noise-cancelling', 'anc', '降噪')):
			score += 3
			reasons.append('Includes ANC or noise-cancelling support.')

		average_rating = 0.0
		max_review_count = 0
		for rating_text in candidate.rating_texts:
			rating_match = re.search(r'(\d+(?:\.\d+)?)', rating_text)
			if rating_match:
				average_rating = max(average_rating, float(rating_match.group(1)))
			review_match = re.search(r'\((\d+)\s+reviews\)', rating_text)
			if review_match:
				max_review_count = max(max_review_count, int(review_match.group(1)))
		if average_rating >= 4.2:
			score += 1
		if max_review_count >= 50:
			score += 1

		if budget_limit is not None:
			comparable_prices = []
			for price_text in candidate.price_texts:
				value = _price_value(price_text)
				if value is None:
					continue
				price_currency = _currency_code(price_text)
				comparable_value = value
				if budget_currency and price_currency and price_currency != budget_currency:
					converted = _convert_currency_for_budget(value, price_currency, budget_currency)
					if converted is None:
						continue
					comparable_value = converted
				comparable_prices.append((comparable_value, price_text))
			if comparable_prices:
				best_price, best_price_text = min(comparable_prices, key=lambda item: item[0])
				if best_price <= budget_limit:
					score += 6
					budget_status = f'within budget via {best_price_text}'
					reasons.append(f'Has a price point within the stated budget ({best_price_text}).')
				else:
					score -= 8
					budget_status = f'over budget via {best_price_text}'
					reasons.append(f'Known price appears over budget ({best_price_text}).')
			elif candidate.price_texts and shopping_backed:
				score -= 2
				budget_status = 'price not comparable to stated budget'
				reasons.append('Has a price, but it is not directly comparable to the stated budget.')
		elif candidate.price_texts:
			score += 1

		ranked.append(
			RankedCandidate(
				candidate=candidate,
				score=score,
				reasons=_unique_text(reasons)[:6],
				review_backed=review_backed,
				shopping_backed=shopping_backed,
				budget_status=budget_status,
			)
		)

	return sorted(
		ranked,
		key=lambda item: (
			-item.score,
			0 if item.review_backed else 1,
			0 if item.shopping_backed else 1,
			-len(item.candidate.sources),
			item.candidate.title.lower(),
		),
	)


def shopping_candidates_to_evidence(candidates: list[ShoppingCandidate], source: str) -> list[CandidateEvidence]:
	result: list[CandidateEvidence] = []
	for candidate in candidates:
		price = candidate.price_text or 'unknown price'
		rating = f'; rating {candidate.rating_text}' if candidate.rating_text else ''
		result.append(
			CandidateEvidence(
				title=candidate.title,
				source_type=SourceType.shopping,
				source=source,
				url=candidate.url,
				price_text=candidate.price_text,
				rating_text=candidate.rating_text,
				evidence=f'Shopping listing on {source} at {price}{rating}.',
			)
		)
	return result


def _load_next_data_json(html_text: str) -> dict | None:
	match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, flags=re.IGNORECASE | re.DOTALL)
	if not match:
		return None
	try:
		return json.loads(match.group(1))
	except json.JSONDecodeError:
		return None


def _load_rtings_recommendation_props(html_text: str) -> dict | None:
	match = re.search(r'data-vue="RecommendationVuePage" data-props="([^"]+)"', html_text)
	if not match:
		return None
	try:
		return json.loads(html.unescape(match.group(1)))
	except json.JSONDecodeError:
		return None


def _load_soundguys_page_data(html_text: str) -> dict | None:
	data = _load_next_data_json(html_text)
	if not data:
		return None
	try:
		return data['props']['pageProps']['page']
	except (KeyError, TypeError):
		return None


def _strip_html_text(text: str | None) -> str | None:
	if not text:
		return None
	value = re.sub(r'<[^>]+>', ' ', text)
	value = html.unescape(value)
	value = re.sub(r'\s+', ' ', value).strip()
	return value or None


def _extract_heading_label(html_text: str | None) -> str | None:
	if not html_text:
		return None
	match = re.search(r'<h[23][^>]*>(.*?)</h[23]>', html_text, flags=re.IGNORECASE | re.DOTALL)
	if not match:
		return None
	return _strip_html_text(match.group(1))


def _soundguys_price_text(block: dict) -> str | None:
	for button in block.get('buttons') or []:
		price = button.get('price') or {}
		current = price.get('current')
		currency = price.get('currency') or '$'
		if isinstance(current, (int, float)):
			return f'{currency}{current:.2f}'
		label = ((button.get('link') or {}).get('label') or '').strip()
		label_hint = _extract_price_hint(label)
		if label_hint:
			return label_hint
	msrp = block.get('msrp') or {}
	current = msrp.get('price')
	currency = msrp.get('currency') or '$'
	if isinstance(current, (int, float)):
		return f'{currency}{current:.2f}'
	return None


def _tomsguide_price_text(html_text: str) -> str | None:
	for pattern in (
		r'\$\s*\d+(?:\.\d+)?',
		r'USD\s*\d+(?:\.\d+)?',
		r'under\s+\$\s*\d+(?:\.\d+)?',
	):
		match = re.search(pattern, html_text, flags=re.IGNORECASE)
		if match:
			return re.sub(r'\s+', ' ', match.group(0)).replace('$ ', '$').strip()
	return None


def _tomsguide_product_title(page_title: str | None, page_url: str) -> str | None:
	if page_title:
		title = page_title.split('|', 1)[0].strip()
		title = re.sub(r'\s*:\s*.*$', '', title)
		match = re.match(r'^(.*?)\s+review\b', title, flags=re.IGNORECASE)
		if match:
			title = match.group(1)
		title = re.sub(r'\s+(headphones?|earbuds?)\b.*$', '', title, flags=re.IGNORECASE)
		title = re.sub(r'\s+', ' ', title).strip(' :-')
		if title:
			return title
	slug = urlparse(page_url).path.split('/')[-1]
	slug = re.sub(r'[-_]\d+$', '', slug)
	slug = slug.replace('-review', '').replace('review-', '')
	slug = slug.replace('-headphones', '').replace('-headphone', '')
	slug = slug.replace('-', ' ').replace('_', ' ')
	slug = re.sub(r'\b(review|headphones?|tom\'s guide)\b', ' ', slug, flags=re.IGNORECASE)
	slug = re.sub(r'\s+', ' ', slug).strip()
	return slug.title() if slug else None


def _sspai_product_title(page_title: str | None, page_url: str) -> str | None:
	if page_title:
		title = page_title.split('- 少数派', 1)[0].strip()
		title = re.sub(r'^(?:TDS REVIEW｜|TDS REVIEW\|)', '', title, flags=re.IGNORECASE).strip()
		title = re.sub(r'^「新玩意」', '', title).strip()
		title = re.sub(r'(首发)?体验.*$', '', title).strip()
		title = re.sub(r'上手.*$', '', title).strip()
		title = re.sub(r'全面.*$', '', title).strip()
		title = re.sub(r'\s+', ' ', title).strip(' ：:|')
		if title:
			return title
	slug = urlparse(page_url).path.split('/')[-1]
	return slug if slug else None


def _ifanr_product_title(page_title: str | None, page_url: str) -> str | None:
	if page_title:
		title = page_title.split('|', 1)[0].strip()
		prefix = re.split(r'[：:|｜丨]', title, maxsplit=1)[0].strip()
		if prefix and re.search(r'[A-Za-z0-9]|耳机|头戴|降噪|AirPods|索尼|Bose|Sonos', prefix, flags=re.IGNORECASE):
			title = prefix
		title = re.sub(r'(首发)?评测.*$', '', title).strip()
		title = re.sub(r'体验.*$', '', title).strip()
		title = re.sub(r'上手.*$', '', title).strip()
		title = re.sub(r'\s+', ' ', title).strip(' ：:|-')
		if title:
			return title
	slug = urlparse(page_url).path.split('/')[-1]
	return slug if slug else None


def _extract_tomsguide_roundup_candidates(html_text: str, page_url: str) -> list[CandidateEvidence]:
	matches = list(
		re.finditer(
			r'<h3[^>]*class="product__title"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>',
			html_text,
			flags=re.IGNORECASE | re.DOTALL,
		)
	)
	if not matches:
		return []

	candidates: list[CandidateEvidence] = []
	for index, match in enumerate(matches):
		next_start = matches[index + 1].start() if index + 1 < len(matches) else min(len(html_text), match.end() + 8000)
		segment = html_text[match.start() : next_start]
		prefix = html_text[max(0, match.start() - 1500) : match.start()]

		title = _strip_html_text(match.group(2))
		if not title:
			continue
		title = re.sub(r'^\d+\.\s*', '', title).strip()
		if not title:
			continue

		url = urljoin(page_url, html.unescape(match.group(1)))
		subtitle_match = re.search(r'<div class="_hawk subtitle">(.*?)</div>', segment, flags=re.IGNORECASE | re.DOTALL)
		subtitle = _strip_html_text(subtitle_match.group(1)) if subtitle_match else None
		heading_matches = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', prefix, flags=re.IGNORECASE | re.DOTALL)
		section_label = None
		for heading_html in reversed(heading_matches):
			heading = _strip_html_text(heading_html)
			if heading and heading != title and ('best ' in heading.lower() or 'also tested' in heading.lower()):
				section_label = heading
				break

		spec_pairs = re.findall(
			r'<span class="spec__name">(.*?)</span>\s*<span class="spec_value">(.*?)</span>',
			segment,
			flags=re.IGNORECASE | re.DOTALL,
		)
		spec_texts = []
		for name_html, value_html in spec_pairs[:4]:
			name = _strip_html_text(name_html)
			value = _strip_html_text(value_html)
			if name and value:
				spec_texts.append(f'{name} {value}')

		evidence_parts = [part for part in [section_label, subtitle] if part]
		if spec_texts:
			evidence_parts.append(f'Specs: {"; ".join(spec_texts[:3])}')
		evidence_text = ' | '.join(evidence_parts) or f'Tom\'s Guide best-picks entry on {page_url}.'
		price_text = _tomsguide_price_text(segment)

		signal_text = ' '.join([section_label or '', subtitle or '', ' '.join(spec_texts)]).lower()
		sound_notes = evidence_text if re.search(
			r'sound|audio|balanced|neutral|bass|detailed|clarity|immersive|anc|noise cancellation|noise cancelling',
			signal_text,
			flags=re.IGNORECASE,
		) else None
		comfort_notes = evidence_text if re.search(
			r'comfort|comfortable|fit|lightweight|wear|padded|clamp',
			signal_text,
			flags=re.IGNORECASE,
		) else None

		candidates.append(
			CandidateEvidence(
				title=title,
				source_type=SourceType.review,
				source='tomsguide.com',
				url=url,
				price_text=price_text,
				sound_notes=sound_notes,
				comfort_notes=comfort_notes,
				evidence=evidence_text,
			)
		)

	return candidates


def extract_shopping_candidates(site: str, html_text: str, limit: int = 5, query: str | None = None) -> list[ShoppingCandidate]:
	candidates: list[ShoppingCandidate] = []
	seen_urls: set[str] = set()
	data = _load_next_data_json(html_text)

	if site == 'walmart.com' and data:
		try:
			stacks = data['props']['pageProps']['initialData']['searchResult']['itemStacks']
		except (KeyError, TypeError):
			stacks = []

		for stack in stacks:
			items = stack.get('itemsV2') or stack.get('items') or []
			for item in items:
				name = (item.get('name') or '').strip()
				canonical_url = item.get('canonicalUrl') or ''
				if not name or not canonical_url.startswith('/ip/'):
					continue
				absolute_url = urljoin('https://www.walmart.com', canonical_url.replace('\\u0026', '&'))
				if absolute_url in seen_urls:
					continue
				price_info = item.get('priceInfo') or {}
				current_price = price_info.get('currentPrice') or {}
				price_text = current_price.get('priceString') or price_info.get('linePrice') or price_info.get('itemPrice')
				rating = item.get('averageRating') or (item.get('rating') or {}).get('averageRating')
				reviews = item.get('numberOfReviews') or (item.get('rating') or {}).get('numberOfReviews')
				rating_text = None
				if rating or reviews:
					review_suffix = f' ({reviews} reviews)' if reviews else ''
					rating_text = f'{rating}/5{review_suffix}' if rating else review_suffix.lstrip()
				candidates.append(
					ShoppingCandidate(
						title=name,
						url=absolute_url,
						price_text=price_text,
						rating_text=rating_text,
						source='walmart.com',
					)
				)
				seen_urls.add(absolute_url)

	if site == 'adorama.com' and data:
		try:
			products = data['props']['pageProps']['products']
		except (KeyError, TypeError):
			products = []

		for product in products:
			title = (product.get('productTitle') or product.get('shortTitle') or '').strip()
			product_url = product.get('productUrl') or ''
			if not title or not product_url:
				continue
			absolute_url = urljoin('https://www.adorama.com', product_url)
			if absolute_url in seen_urls:
				continue
			prices = product.get('prices') or {}
			price_value = prices.get('price')
			price_text = f'${price_value:.2f}' if isinstance(price_value, (int, float)) else None
			ratings = product.get('ratings') or {}
			avg_rating = ratings.get('averageRatingStars')
			review_count = ratings.get('count')
			rating_text = None
			if avg_rating or review_count:
				review_suffix = f' ({review_count} reviews)' if review_count else ''
				rating_text = f'{avg_rating}/5{review_suffix}' if avg_rating else review_suffix.lstrip()
			candidates.append(
				ShoppingCandidate(
					title=title,
					url=absolute_url,
					price_text=price_text,
					rating_text=rating_text,
					source='adorama.com',
				)
			)
			seen_urls.add(absolute_url)

	budget_limit = _query_budget_limit(query)
	if budget_limit is not None:
		under_budget = [candidate for candidate in candidates if (_price_value(candidate.price_text) or budget_limit + 1) <= budget_limit]
		if under_budget:
			candidates = under_budget

	viable_candidates = [candidate for candidate in candidates if _shopping_signal_score(candidate, query) >= 0]
	if viable_candidates:
		candidates = viable_candidates

	candidates.sort(key=lambda item: _shopping_candidate_score(item, query), reverse=True)
	return candidates[:limit]


def build_rtings_direct_urls(query: str | None) -> list[str]:
	if not query:
		return []
	text = query.lower()
	urls: list[str] = []
	if 'under' in text or '$' in text:
		urls.append('https://www.rtings.com/headphones/reviews/best/by-price/under-200')
		if 'over-ear' in text or 'over ear' in text:
			urls.append('https://www.rtings.com/headphones/reviews/best/by-price/under-100')
	if 'noise cancelling' in text or 'anc' in text:
		urls.append('https://www.rtings.com/headphones/reviews/best/noise-cancelling-headphones-under-200')
	return _unique_text(urls)


def build_tomsguide_direct_urls(query: str | None) -> list[str]:
	if not query:
		return []
	hints = _query_hints(query)
	budget_limit = _query_budget_limit(query)
	urls: list[str] = []
	if hints['headphones'] or hints['over_ear']:
		urls.append('https://www.tomsguide.com/best-picks/best-over-ear-headphones')
		urls.append('https://www.tomsguide.com/best-picks/best-headphones')
		if budget_limit is not None:
			urls.append('https://www.tomsguide.com/best-picks/best-cheap-headphones')
	return _unique_text(urls)


def build_soundguys_direct_urls(query: str | None) -> list[str]:
	if not query:
		return []
	hints = _query_hints(query)
	budget_limit = _query_budget_limit(query)
	urls: list[str] = []
	if hints['headphones'] or hints['over_ear']:
		if hints['anc'] or budget_limit is not None:
			urls.append('https://www.soundguys.com/best-budget-noise-cancelling-headphones-7142/')
	return _unique_text(urls)


def build_sspai_direct_urls(query: str | None) -> list[str]:
	if not query:
		return []
	hints = _query_hints(query)
	urls: list[str] = []
	if hints['headphones'] or hints['over_ear']:
		urls.append('https://sspai.com/tag/%E8%80%B3%E6%9C%BA')
	return _unique_text(urls)


def build_ifanr_direct_urls(query: str | None) -> list[str]:
	if not query:
		return []
	return _unique_text(['https://www.ifanr.com/category/review', 'https://www.ifanr.com/category/evaluation'])


def build_docs_direct_urls(query: str | None = None) -> list[str]:
	urls = ['https://docs.browser-use.com']
	text = (query or '').lower()
	if re.search(r'openai|llm|model|provider|base[_ -]?url|compatible|api', text):
		urls.extend(
			[
				'https://docs.browser-use.com/llms.txt',
				'https://docs.browser-use.com/llms-full.txt',
			]
		)
	return _unique_text(urls)


def build_github_repo_direct_urls(source_url: str, query: str | None = None) -> list[str]:
	parsed = urlparse(source_url)
	if _normalize_site(parsed.netloc) != 'github.com':
		return []
	parts = [part for part in parsed.path.split('/') if part]
	if len(parts) < 2:
		return []
	owner, repo = parts[0], parts[1]
	base_repo_url = f'https://github.com/{owner}/{repo}'
	urls = [
		base_repo_url,
		f'https://raw.githubusercontent.com/{owner}/{repo}/main/README.md',
		f'https://raw.githubusercontent.com/{owner}/{repo}/master/README.md',
	]
	text = (query or '').lower()
	if re.search(r'openai|base[_ -]?url|compatible|provider|api', text):
		urls.extend(
			[
				f'{base_repo_url}/search?q=openai',
				f'{base_repo_url}/search?q=base_url',
			]
		)
	return _unique_text(urls)


def extract_review_candidates(site: str, html_text: str, page_url: str) -> list[CandidateEvidence]:
	if site == 'rtings.com':
		props = _load_rtings_recommendation_props(html_text)
		if not props:
			return []

		try:
			product_recommendations = props['page_data']['page']['recommendation']['product_recommendations']
		except (KeyError, TypeError):
			return []

		candidates: list[CandidateEvidence] = []
		for item in product_recommendations:
			product = item.get('product') or {}
			title = (product.get('fullname') or product.get('name') or '').strip()
			if not title:
				continue
			subtitle = _strip_html_text(item.get('subtitle'))
			description = _strip_html_text(item.get('description'))
			sound_notes = None
			comfort_notes = None
			if description and re.search(r'balanced|neutral|v-shaped|bass|sound|treble', description, flags=re.IGNORECASE):
				sound_notes = description
			if description and re.search(r'comfort|comfortable|fit|clamp|wear', description, flags=re.IGNORECASE):
				comfort_notes = description
			price_text = None
			deals = item.get('featured_deals') or []
			for deal in deals:
				price = deal.get('price') or {}
				if price.get('formatted'):
					price_text = price['formatted']
					break
			if price_text is None:
				price_text = _extract_price_hint(subtitle) or _extract_price_hint(description)
			url = page_url
			if product.get('review_url'):
				url = urljoin('https://www.rtings.com', product['review_url'])
			evidence_parts = [part for part in [subtitle, description] if part]
			candidates.append(
				CandidateEvidence(
					title=title,
					source_type=SourceType.review,
					source='rtings.com',
					url=url,
					price_text=price_text,
					sound_notes=sound_notes,
					comfort_notes=comfort_notes,
					evidence=' | '.join(evidence_parts) or f'RTINGS recommendation on {page_url}.',
				)
			)

		return candidates

	if site == 'soundguys.com':
		page = _load_soundguys_page_data(html_text)
		if not page or page.get('resource') != 'best-list-page':
			return []

		blocks = page.get('blocks') or []
		candidates: list[CandidateEvidence] = []
		current_label: str | None = None
		for block in blocks:
			if not isinstance(block, dict):
				continue
			resource = block.get('resource')
			if resource == 'nc-string':
				label = _extract_heading_label(block.get('html'))
				if label:
					current_label = label
				continue
			if resource != 'nc-deals-detailed':
				continue
			title = (block.get('title') or '').strip()
			if not title:
				continue
			tags = [_strip_html_text(str(tag)) for tag in (block.get('tags') or [])]
			tags = [tag for tag in tags if tag]
			score = block.get('score')
			score_text = f'SoundGuys score {score}.' if isinstance(score, (int, float)) else None
			price_text = _soundguys_price_text(block)
			review_link = (((block.get('refLink') or {}).get('pLink') or {}).get('href') or '').strip()
			buy_link = ((block.get('pLink') or {}).get('href') or '').strip()
			url = review_link or buy_link or page_url
			evidence_parts = []
			if current_label:
				evidence_parts.append(current_label)
			if tags:
				evidence_parts.append(f'Tags: {", ".join(tags[:4])}')
			if score_text:
				evidence_parts.append(score_text)
			evidence = ' | '.join(evidence_parts) or f'SoundGuys recommendation on {page_url}.'
			tag_text = ' '.join(tags).lower()
			label_text = (current_label or '').lower()
			sound_notes = None
			comfort_notes = None
			if re.search(r'sound|balanced|neutral|bass|immersive', tag_text, flags=re.IGNORECASE) or re.search(
				r'sound|music', label_text, flags=re.IGNORECASE
			):
				sound_notes = evidence
			if re.search(r'comfort|comfortable|fit', tag_text, flags=re.IGNORECASE):
				comfort_notes = evidence
			candidates.append(
				CandidateEvidence(
					title=title,
					source_type=SourceType.review,
					source='soundguys.com',
					url=url,
					price_text=price_text,
					sound_notes=sound_notes,
					comfort_notes=comfort_notes,
					evidence=evidence,
				)
			)
		return candidates

	if site == 'tomsguide.com':
		if '/best-picks/' in urlparse(page_url).path:
			roundup_candidates = _extract_tomsguide_roundup_candidates(html_text, page_url)
			if roundup_candidates:
				return roundup_candidates
		page_title = extract_page_title(html_text)
		product_title = _tomsguide_product_title(page_title, page_url)
		if not product_title:
			return []
		description_match = re.search(r'<meta name="description" content="([^"]+)"', html_text, flags=re.IGNORECASE)
		description = html.unescape(description_match.group(1)) if description_match else None
		text_excerpt = html_to_text_excerpt(html_text, max_chars=2500)
		evidence_parts = [part for part in [page_title, description] if part]
		sound_notes = None
		comfort_notes = None
		if description and re.search(r'sound|audio|bass|balanced|neutral|immersion|detailed|noise cancellation|noise cancelling|anc', description, flags=re.IGNORECASE):
			sound_notes = description
		if description and re.search(r'comfort|comfortable|fit|lightweight|wear', description, flags=re.IGNORECASE):
			comfort_notes = description
		price_text = _tomsguide_price_text(text_excerpt)
		return [
			CandidateEvidence(
				title=product_title,
				source_type=SourceType.review,
				source='tomsguide.com',
				url=page_url,
				price_text=price_text,
				sound_notes=sound_notes,
				comfort_notes=comfort_notes,
				evidence=' | '.join(evidence_parts) or f'Tom\'s Guide review on {page_url}.',
			)
		]

	if site == 'sspai.com':
		if '/post/' not in urlparse(page_url).path:
			return []
		page_title = extract_page_title(html_text)
		product_title = _sspai_product_title(page_title, page_url)
		if not product_title:
			return []
		description_match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html_text, flags=re.IGNORECASE)
		description = html.unescape(description_match.group(1)) if description_match else None
		if description and len(description) < 20:
			description = None
		text_excerpt = html_to_text_excerpt(html_text, max_chars=2500)
		price_text = _extract_price_hint(text_excerpt) or _extract_price_hint(description)
		evidence_parts = [part for part in [page_title, description] if part]
		signal_text = ' '.join(part for part in [product_title, page_title or '', description or '']).lower()
		sound_notes = description if re.search(
			r'sound|audio|balanced|neutral|bass|anc|noise cancellation|noise cancelling|调音|声音|音质|降噪',
			signal_text,
			flags=re.IGNORECASE,
		) else None
		comfort_notes = description if re.search(
			r'comfort|comfortable|fit|lightweight|wear|佩戴|舒适|头梁|耳罩',
			signal_text,
			flags=re.IGNORECASE,
		) else None
		return [
			CandidateEvidence(
				title=product_title,
				source_type=SourceType.review,
				source='sspai.com',
				url=page_url,
				price_text=price_text,
				sound_notes=sound_notes,
				comfort_notes=comfort_notes,
				evidence=' | '.join(evidence_parts) or f'SSPAI article on {page_url}.',
			)
		]

	if site == 'ifanr.com':
		if not re.fullmatch(r'/\d+', urlparse(page_url).path):
			return []
		page_title = extract_page_title(html_text)
		product_title = _ifanr_product_title(page_title, page_url)
		if not product_title:
			return []
		description_match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html_text, flags=re.IGNORECASE)
		description = html.unescape(description_match.group(1)) if description_match else None
		if description and len(description) < 12:
			description = None
		text_excerpt = html_to_text_excerpt(html_text, max_chars=3000)
		price_text = _extract_price_hint(text_excerpt) or _extract_price_hint(description)
		evidence_parts = [part for part in [page_title, description] if part]
		signal_text = ' '.join(part for part in [product_title, page_title or '', description or '', text_excerpt]).lower()
		sound_notes = description if re.search(
			r'sound|audio|balanced|neutral|bass|anc|noise cancellation|noise cancelling|音质|声音|调音|三频|低频|中频|高频|降噪',
			signal_text,
			flags=re.IGNORECASE,
		) else None
		comfort_notes = description if re.search(
			r'comfort|comfortable|fit|lightweight|wear|佩戴|舒适|头梁|耳罩|夹头|闷热|重量',
			signal_text,
			flags=re.IGNORECASE,
		) else None
		return [
			CandidateEvidence(
				title=product_title,
				source_type=SourceType.review,
				source='ifanr.com',
				url=page_url,
				price_text=price_text,
				sound_notes=sound_notes,
				comfort_notes=comfort_notes,
				evidence=' | '.join(evidence_parts) or f'ifanr article on {page_url}.',
			)
		]

	return []


def extract_site_candidate_urls(site: str, html_text: str, limit: int = 3, query: str | None = None) -> list[str]:
	decoded_text = html.unescape(html_text)
	candidates: list[str] = []
	for href in _extract_hrefs(decoded_text):
		absolute = _absolute_site_url(site, href)
		if not absolute:
			continue
		parsed = urlparse(absolute)
		path = parsed.path.lower()
		if site == 'rtings.com':
			if '/headphones/reviews/' not in path or '/search' in path:
				continue
		elif site == 'soundguys.com':
			if parsed.path in {'', '/'}:
				continue
			if parsed.query.startswith('s=') or any(
				path.startswith(prefix)
				for prefix in ('/category/', '/tag/', '/author/', '/page/', '/static/', '/_next/', '/search/', '/feed')
			):
				continue
			if re.search(r'\.(?:woff2?|css|js|svg|png|jpe?g|webp|xml|ico)$', path):
				continue
			if not re.search(r'-\d{4,}/?$', parsed.path):
				continue
			if re.search(r'(deal|launch|spotted|buy-instead)', path):
				continue
			if not re.search(r'(best|review)', path):
				continue
			if query:
				hints = _query_hints(query)
				if hints['over_ear'] and re.search(r'(earbuds|clip-on|speaker|mic|microphone)', path):
					continue
				if hints['headphones'] and not hints['earbuds'] and re.search(r'(earbuds|speaker)', path):
					continue
		elif site == 'amazon.com':
			if '/dp/' not in path and '/gp/product/' not in path:
				continue
		elif site == 'tomsguide.com':
			if '/audio/' not in path and '/best-picks/' not in path:
				continue
			if 'review' not in path and '/best-picks/' not in path:
				continue
			if re.search(r'\.(?:css|js|png|jpe?g|webp|xml|ico)$', path):
				continue
		elif site == 'sspai.com':
			if not re.fullmatch(r'/post/\d+', parsed.path):
				continue
		elif site == 'ifanr.com':
			if not re.fullmatch(r'/\d+', parsed.path):
				continue
			if parsed.path.startswith('/news/'):
				continue
		else:
			continue
		cleaned = _strip_tracking(absolute)
		if cleaned not in candidates:
			candidates.append(cleaned)
	if site == 'rtings.com' and not candidates:
		for path in re.findall(r'(/headphones/reviews/[a-z0-9\-/]+)', decoded_text, flags=re.IGNORECASE):
			absolute = urljoin('https://www.rtings.com', path)
			if absolute not in candidates:
				candidates.append(absolute)
	if query:
		candidates.sort(key=lambda item: _candidate_score(item, query), reverse=True)
	return candidates[:limit]


def build_bing_rss_search_url(query: str, source: str | None = None) -> str:
	search_query = clean_query(query)
	normalized_source = _normalize_site(source) if source else ''
	if source and normalized_source and normalized_source != 'bing.com' and not re.match(r'^https?://', source, flags=re.IGNORECASE):
		search_query = f'site:{normalized_source} {search_query}'
	return f'https://www.bing.com/search?format=rss&q={quote_plus(search_query)}'


def _query_relevance_terms(query: str | None) -> list[str]:
	if not query:
		return []
	cleaned = clean_query(re.sub(r'\bsite:[^\s]+\b', ' ', query, flags=re.IGNORECASE)).lower()
	terms = re.findall(r'[a-z0-9][a-z0-9._-]{2,}', cleaned)
	stop_terms = {
		'the',
		'and',
		'for',
		'with',
		'from',
		'that',
		'this',
		'what',
		'when',
		'where',
		'how',
		'docs',
		'doc',
		'api',
		'apis',
	}
	filtered = [term for term in terms if term not in stop_terms]
	if 'browser-use' in cleaned and 'browser-use' not in filtered:
		filtered.append('browser-use')
	return _unique_text(filtered[:10])


def _source_match_score(result_url: str, source: str | None) -> int:
	if not source:
		return 0
	normalized_source = _normalize_site(source)
	if normalized_source in {'', 'bing.com'}:
		return 0
	host = _normalize_site(urlparse(result_url).netloc)
	if not host:
		return -5
	allowed_hosts = {normalized_source}
	if normalized_source == 'github.com':
		allowed_hosts.add('raw.githubusercontent.com')
	if host in allowed_hosts or any(host.endswith(f'.{allowed}') for allowed in allowed_hosts):
		return 6
	return -8


def _bing_result_score(title: str, link: str, description: str, query: str | None, source: str | None) -> int:
	text = ' '.join([title, description, link]).lower()
	score = _source_match_score(link, source)
	terms = _query_relevance_terms(query)
	for term in terms:
		if term in title.lower():
			score += 4
		elif term in link.lower():
			score += 3
		elif term in description.lower():
			score += 2
	if 'browser-use' in text:
		score += 4
	if re.search(r'openai|compatible|base_url|provider|model', text):
		score += 1
	return score


def extract_bing_rss_results(
	xml_text: str,
	limit: int = 4,
	query: str | None = None,
	source: str | None = None,
) -> list[tuple[str, str, str]]:
	scored_results: list[tuple[int, tuple[str, str, str]]] = []
	for title, link, description in re.findall(
		r'<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<description>(.*?)</description>.*?</item>',
		xml_text,
		flags=re.IGNORECASE | re.DOTALL,
	):
		clean_title = re.sub(r'\s+', ' ', html.unescape(title)).strip()
		clean_link = html.unescape(link).strip()
		clean_description = re.sub(r'\s+', ' ', html.unescape(description)).strip()
		if not clean_title or not clean_link.startswith(('http://', 'https://')):
			continue
		score = _bing_result_score(clean_title, clean_link, clean_description, query=query, source=source)
		min_score = 2 if source and _normalize_site(source) != 'bing.com' else 1
		if score < min_score:
			continue
		scored_results.append((score, (clean_title, clean_link, clean_description)))
	scored_results.sort(key=lambda item: (item[0], len(item[1][2])), reverse=True)
	return [result for _, result in scored_results[:limit]]


async def fetch_bing_rss_results(query: str, source: str | None = None, limit: int = 4) -> list[tuple[str, str, str]]:
	search_url = build_bing_rss_search_url(query, source=source)
	headers = {
		'User-Agent': 'Mozilla/5.0',
		'Accept-Language': 'en-US,en;q=0.9',
	}
	try:
		async with httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True) as client:
			response = await client.get(search_url, headers=headers)
			response.raise_for_status()
			content_type = response.headers.get('content-type', '')
			if 'xml' not in content_type and '<rss' not in response.text[:200].lower():
				return []
			return extract_bing_rss_results(response.text, limit=limit, query=query, source=source)
	except httpx.HTTPError:
		return []


async def fetch_search_page_html(url: str) -> str | None:
	headers = {
		'User-Agent': 'Mozilla/5.0',
		'Accept-Language': 'en-US,en;q=0.9',
	}
	try:
		async with httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True) as client:
			response = await client.get(url, headers=headers)
			response.raise_for_status()
			content_type = response.headers.get('content-type', '')
			if 'text/html' not in content_type:
				return None
			return response.text
	except httpx.HTTPError:
		return None


async def fetch_document_text(url: str) -> tuple[str | None, str | None]:
	headers = {
		'User-Agent': 'Mozilla/5.0',
		'Accept-Language': 'en-US,en;q=0.9',
	}
	try:
		async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
			response = await client.get(url, headers=headers)
			response.raise_for_status()
			content_type = response.headers.get('content-type', '').lower()
			if not any(token in content_type for token in ['text/html', 'text/plain', 'text/markdown']):
				return None, content_type
			return response.text, content_type
	except httpx.HTTPError:
		return None, None


async def fetch_ifanr_api_payload(url: str) -> dict | None:
	headers = {
		'User-Agent': 'Mozilla/5.0',
		'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
	}
	try:
		async with httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True) as client:
			response = await client.get(url, headers=headers)
			response.raise_for_status()
			return response.json()
	except (httpx.HTTPError, json.JSONDecodeError):
		return None


def extract_page_title(html_text: str) -> str | None:
	match = re.search(r'<title[^>]*>(.*?)</title>', html_text, flags=re.IGNORECASE | re.DOTALL)
	if not match:
		return None
	title = re.sub(r'\s+', ' ', html.unescape(match.group(1))).strip()
	return title or None


def html_to_text_excerpt(html_text: str, max_chars: int = 6000) -> str:
	text = re.sub(r'<script\b[^>]*>.*?</script>', ' ', html_text, flags=re.IGNORECASE | re.DOTALL)
	text = re.sub(r'<style\b[^>]*>.*?</style>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
	text = re.sub(r'<noscript\b[^>]*>.*?</noscript>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
	text = re.sub(r'<[^>]+>', ' ', text)
	text = html.unescape(text)
	text = re.sub(r'\s+', ' ', text).strip()
	return text[:max_chars]


def plain_text_excerpt(text: str, max_chars: int = 6000) -> str:
	return re.sub(r'\s+', ' ', text).strip()[:max_chars]


async def resolve_stage_targets(source_type: SourceType, sources: list[str], queries: list[str]) -> ResolvedStageTargets:
	base_urls = build_source_entry_urls(source_type, sources, queries)
	resolved_urls: list[str] = []
	blocked_reason: str | None = None
	fetch_mode_used = 'browser'

	for source, base_url in zip(sources, base_urls, strict=False):
		adapter = get_site_adapter(source, source_type)
		site_queries = [adapt_query_for_source(query, source) for query in queries if adapt_query_for_source(query, source)]
		site_query = site_queries[0] if site_queries else (queries[0] if queries else None)
		normalized_source = _normalize_site(source)

		if source_type == SourceType.web:
			if re.match(r'^https?://', source, flags=re.IGNORECASE):
				direct_urls = [source]
				if normalized_source == 'docs.browser-use.com':
					direct_urls = build_docs_direct_urls(site_query)
				elif normalized_source == 'github.com':
					direct_urls = build_github_repo_direct_urls(source, site_query)
				for direct_url in direct_urls:
					if direct_url not in resolved_urls:
						resolved_urls.append(direct_url)
				fetch_mode_used = 'http'
				continue

			if normalized_source == 'docs.browser-use.com':
				for direct_url in build_docs_direct_urls(site_query):
					if direct_url not in resolved_urls:
						resolved_urls.append(direct_url)
				if resolved_urls:
					fetch_mode_used = 'http'
					continue

			search_source = None if normalized_source == 'bing.com' else source
			for query in site_queries or queries:
				for _, candidate_url, _ in await fetch_bing_rss_results(query, source=search_source, limit=adapter.result_limit):
					if candidate_url not in resolved_urls:
						resolved_urls.append(candidate_url)
			if resolved_urls:
				fetch_mode_used = 'http'
			continue

		if source_type == SourceType.official and site_query and not adapter.search_url_template:
			for _, candidate_url, _ in await fetch_bing_rss_results(site_query, source=source, limit=3):
				if candidate_url not in resolved_urls:
					resolved_urls.append(candidate_url)
			if resolved_urls:
				fetch_mode_used = 'http'
		if adapter.preferred_fetch_mode != 'hybrid':
			continue
		if adapter.domain == 'rtings.com':
			for direct_url in build_rtings_direct_urls(site_query):
				if direct_url not in resolved_urls:
					resolved_urls.append(direct_url)
			if resolved_urls:
				fetch_mode_used = 'hybrid'
		elif adapter.domain == 'tomsguide.com':
			for direct_url in build_tomsguide_direct_urls(site_query):
				if direct_url not in resolved_urls:
					resolved_urls.append(direct_url)
			if resolved_urls:
				fetch_mode_used = 'hybrid'
		elif adapter.domain == 'soundguys.com':
			for direct_url in build_soundguys_direct_urls(site_query):
				if direct_url not in resolved_urls:
					resolved_urls.append(direct_url)
			if resolved_urls:
				fetch_mode_used = 'hybrid'
		elif adapter.domain == 'sspai.com':
			for direct_url in build_sspai_direct_urls(site_query):
				if direct_url not in resolved_urls:
					resolved_urls.append(direct_url)
			if resolved_urls:
				fetch_mode_used = 'hybrid'
		elif adapter.domain == 'ifanr.com':
			for api_url in IFANR_REVIEW_API_URLS:
				payload = await fetch_ifanr_api_payload(api_url)
				if not payload:
					continue
				for candidate_url in extract_ifanr_api_candidate_urls(payload, query=site_query, limit=adapter.result_limit):
					if candidate_url not in resolved_urls:
						resolved_urls.append(candidate_url)
			for direct_url in build_ifanr_direct_urls(site_query):
				if direct_url not in resolved_urls:
					resolved_urls.append(direct_url)
			if resolved_urls:
				fetch_mode_used = 'hybrid'
		html_text = await fetch_search_page_html(base_url)
		if not html_text:
			continue
		if blocked_reason is None:
			blocked_reason = detect_blocked_page(adapter.domain, html_text)
		candidates = extract_site_candidate_urls(adapter.domain, html_text, limit=adapter.result_limit, query=site_query)
		if candidates:
			fetch_mode_used = 'hybrid'
			for url in candidates:
				if url not in resolved_urls:
					resolved_urls.append(url)
			continue
		shopping_candidates = extract_shopping_candidates(adapter.domain, html_text, limit=adapter.result_limit, query=site_query)
		if shopping_candidates:
			fetch_mode_used = 'hybrid'
			for candidate in shopping_candidates:
				if candidate.url not in resolved_urls:
					resolved_urls.append(candidate.url)

	initial_urls = _unique_text(resolved_urls + base_urls)[:4] if resolved_urls else base_urls
	return ResolvedStageTargets(
		initial_urls=initial_urls,
		resolved_urls=resolved_urls,
		fetch_mode_used=fetch_mode_used,
		blocked_reason=blocked_reason,
	)


def fallback_task_plan(config: ResearchAssistantConfig) -> TaskPlan:
	mode = infer_mode(config.task)
	locale = infer_locale(config.task, config.locale)
	default_map = default_sources(mode, locale)
	budget = _extract_budget_text(config.task)
	explicit_urls = _extract_explicit_urls(config.task)
	explicit_domains = [
		domain
		for domain in _extract_explicit_domains(config.task)
		if domain not in {_normalize_site(urlparse(url).netloc) for url in explicit_urls}
	]
	inferred_repo_urls = _infer_repo_urls_from_task(config.task, explicit_urls, explicit_domains)
	web_seed_sources = explicit_urls + inferred_repo_urls + explicit_domains
	shopping_sources = _unique(config.shopping_sites or default_map[SourceType.shopping])
	review_sources = _unique(config.review_sites or default_map[SourceType.review])
	official_sources = _unique(config.official_sites or default_map[SourceType.official])
	default_web_sources = [] if web_seed_sources else default_map[SourceType.web]
	web_sources = _unique(config.web_sites or (web_seed_sources + default_web_sources))
	web_sources = _dedupe_web_sources_preserve_explicit_urls(web_sources)
	base_query = config.task.strip()
	research_queries = _unique_text(
		[
			base_query,
			f'{base_query} documentation',
			f'{base_query} official docs',
		]
	)

	if mode in {AssistantMode.recommendation, AssistantMode.comparison}:
		decision_criteria = [
			'Respect explicit budget and product constraints',
			'Prefer exact product names, prices, and links',
			'Use both retailer and review evidence before recommending',
		]
		required_deliverables = [
			'Concrete recommendations',
			'Supporting evidence from multiple sources',
			'Links for the shortlisted options',
		]
	else:
		decision_criteria = [
			'Prioritize the domains or URLs explicitly named in the task',
			'Use grounded evidence from the fetched pages before making claims',
			'Separate confirmed findings from uncertainty or open questions',
		]
		required_deliverables = [
			'Clear summary of findings',
			'Source-backed evidence with links',
			'Practical next steps or caveats',
		]

	return TaskPlan(
		user_task=config.task,
		mode=mode,
		locale=locale,
		topic=base_query,
		budget=budget,
		shopping_sources=shopping_sources,
		review_sources=review_sources,
		official_sources=official_sources,
		web_sources=web_sources,
		shopping_queries=[base_query, f'{base_query} buy'],
		review_queries=[f'{base_query} review', f'{base_query} comparison'],
		official_queries=[f'{base_query} official specs'],
		web_queries=research_queries,
		generated_stages=[],
		decision_criteria=decision_criteria,
		required_deliverables=required_deliverables,
	)


def resolve_llm(model_name: str | None = None) -> BaseChatModel:
	explicit = model_name or os.getenv('DEFAULT_LLM') or ''
	raw_model = os.getenv('BROWSER_USE_LLM_MODEL') or ''

	if explicit:
		if '_' in explicit:
			return get_llm_by_name(explicit)
		if os.getenv('OPENAI_API_KEY') or os.getenv('OPENAI_BASE_URL'):
			return ChatOpenAI(model=explicit, api_key=os.getenv('OPENAI_API_KEY'), base_url=os.getenv('OPENAI_BASE_URL') or None)
		if os.getenv('BROWSER_USE_API_KEY'):
			return ChatBrowserUse(model=explicit, api_key=os.getenv('BROWSER_USE_API_KEY'))

	if raw_model and (os.getenv('OPENAI_API_KEY') or os.getenv('OPENAI_BASE_URL')):
		return ChatOpenAI(model=raw_model, api_key=os.getenv('OPENAI_API_KEY'), base_url=os.getenv('OPENAI_BASE_URL') or None)

	if os.getenv('BROWSER_USE_API_KEY'):
		return ChatBrowserUse(model='bu-2-0', api_key=os.getenv('BROWSER_USE_API_KEY'))

	raise ValueError(
		'No supported LLM configuration found. Set DEFAULT_LLM=openai_gpt_5_4, '
		'or set BROWSER_USE_LLM_MODEL plus OPENAI_API_KEY/OPENAI_BASE_URL, '
		'or configure BROWSER_USE_API_KEY for ChatBrowserUse.'
	)


def build_stage_prompt(
	plan: TaskPlan,
	source_type: SourceType,
	sources: list[str],
	queries: list[str],
	max_recommendations: int,
	initial_urls: list[str] | None = None,
) -> str:
	source_urls = '\n'.join(f'- {url}' for url in (initial_urls or build_source_entry_urls(source_type, sources, queries)))
	query_text = '\n'.join(f'- {query}' for query in queries) if queries else '- Use the task wording directly'
	stage_goal = {
		SourceType.shopping: 'Collect concrete products, prices, and buy links from retailer or marketplace sources.',
		SourceType.review: 'Collect verdicts, tradeoffs, and comparisons from review or community sources.',
		SourceType.official: 'Collect official specifications, feature claims, or policy details from manufacturer sources.',
		SourceType.web: 'Collect grounded findings, references, and page-level evidence from general web or documentation sources.',
	}[source_type]
	observation_rule = ''
	if _requires_browser_observation(source_type, sources):
		observation_rule = """

Dynamic-page guidance:
- Use the rendered browser page as the source of truth, including visible cards, text, prices, and links.
- If a verification page, login wall, empty skeleton, or risk-control page is visible, record that under Failed Sources.
- If the page becomes usable after normal rendering or existing user session state, extract from what is visible; do not rely on initial HTML.
""".rstrip()

	return f"""
You are running the {source_type.value} collection stage for a browser research assistant on {date.today().isoformat()}.

Original user task:
{plan.user_task}

Interpreted topic:
- Topic: {plan.topic}
- Budget: {plan.budget or 'not explicitly stated'}
- Mode: {plan.mode.value}

Decision criteria:
{chr(10).join(f'- {item}' for item in plan.decision_criteria)}

Stage objective:
{stage_goal}

Sources to open directly:
{source_urls}

Queries or phrases to use inside those sites:
{query_text}

Execution rules:
1. The initial tabs should already be on site-specific search or result pages. Start extracting from the opened tabs first.
2. If the current tab is broken, blocked, or empty, switch to another already-opened source tab before trying anything else.
3. Stay inside the provided source domains only. Do not use generic web search engines or navigate to unrelated domains unless this is already the dedicated web stage.
4. If the current source domain is unavailable or blocked, record that under Failed Sources and finish the stage instead of searching elsewhere.
5. Extract exact names, URLs, and concrete evidence when available.
6. Do not invent products, prices, ratings, quotes, or claims.
7. Keep at most {max_recommendations + 2} plausible candidates or key findings across this stage.
{observation_rule}

Return markdown with these sections only:
## Stage Summary
## Findings
## Candidate Options
## Failed Sources
""".strip()


def _source_priority_key(source_type: SourceType, site: str, locale: str | None = None) -> tuple:
	adapter = get_site_adapter(site, source_type)
	hybrid_rank = 0 if adapter.preferred_fetch_mode == 'hybrid' else 1
	if source_type == SourceType.shopping:
		if locale == 'zh-CN':
			shopping_priority = {
				'jd.com': 0,
				'tmall.com': 1,
				'taobao.com': 2,
				'walmart.com': 3,
				'adorama.com': 4,
				'amazon.com': 5,
				'bestbuy.com': 6,
			}
		else:
			shopping_priority = {
				'walmart.com': 0,
				'adorama.com': 1,
				'amazon.com': 2,
				'bestbuy.com': 3,
				'jd.com': 4,
				'tmall.com': 5,
				'taobao.com': 6,
			}
		if locale == 'zh-CN':
			return (shopping_priority.get(_normalize_site(site), 50), hybrid_rank, _normalize_site(site))
		return (hybrid_rank, shopping_priority.get(_normalize_site(site), 50), _normalize_site(site))
	if source_type == SourceType.review:
		review_priority = {
			'rtings.com': 0,
			'tomsguide.com': 1,
			'soundguys.com': 2,
			'sspai.com': 3,
			'ifanr.com': 4,
			'thewirecutter.com': 5,
			'zol.com.cn': 6,
			'zhihu.com': 7,
			'bilibili.com': 8,
		}
		return (hybrid_rank, review_priority.get(_normalize_site(site), 50), _normalize_site(site))
	if source_type == SourceType.web:
		normalized = _normalize_site(site)
		if re.match(r'^https?://', site, flags=re.IGNORECASE):
			return (0, 0, site.lower())
		web_priority = {
			'bing.com': 50,
		}
		return (0, web_priority.get(normalized, 10), normalized)
	return (hybrid_rank, _normalize_site(site))


def build_candidate_catalog(stage_results: list[StageResult]) -> list[CandidateCatalogEntry]:
	merged: dict[str, CandidateCatalogEntry] = {}

	for stage in stage_results:
		for candidate in stage.candidate_evidence:
			key = _candidate_identity_key(candidate.title)
			entry = merged.get(key)
			if entry is None:
				entry = CandidateCatalogEntry(title=candidate.title)
				merged[key] = entry
			if candidate.title not in entry.aliases and candidate.title != entry.title:
				entry.aliases.append(candidate.title)
			if candidate.source_type not in entry.source_types:
				entry.source_types.append(candidate.source_type)
			if candidate.source not in entry.sources:
				entry.sources.append(candidate.source)
			if candidate.url and candidate.url not in entry.urls:
				entry.urls.append(candidate.url)
			if candidate.price_text and candidate.price_text not in entry.price_texts:
				entry.price_texts.append(candidate.price_text)
			if candidate.rating_text and candidate.rating_text not in entry.rating_texts:
				entry.rating_texts.append(candidate.rating_text)
			if candidate.sound_notes and candidate.sound_notes not in entry.sound_notes:
				entry.sound_notes.append(candidate.sound_notes)
			if candidate.comfort_notes and candidate.comfort_notes not in entry.comfort_notes:
				entry.comfort_notes.append(candidate.comfort_notes)
			if candidate.evidence and candidate.evidence not in entry.evidence_points:
				entry.evidence_points.append(candidate.evidence)
			record_key = (candidate.source_type.value, candidate.source, candidate.url or '', candidate.title)
			if all((existing.source_type.value, existing.source, existing.url or '', existing.title) != record_key for existing in entry.evidence_records):
				entry.evidence_records.append(candidate.model_copy(deep=True))

	def sort_key(entry: CandidateCatalogEntry) -> tuple[int, int, int, str]:
		return (
			0 if SourceType.review in entry.source_types else 1,
			-len(entry.source_types),
			-len(entry.evidence_points),
			entry.title.lower(),
		)

	return sorted(merged.values(), key=sort_key)


def _url_source_type(url: str) -> SourceType | None:
	host = _normalize_site(urlparse(url).netloc)
	for adapter in SITE_ADAPTERS.values():
		if host == adapter.domain or host.endswith(f'.{adapter.domain}'):
			return adapter.source_type
	return None


def render_report(report: AssistantReport) -> str:
	lines = [
		f'Task: {report.user_task}',
		f'Mode: {report.mode.value}',
		'',
		'Summary:',
		report.summary,
	]

	if report.confidence_level:
		confidence_line = f'Confidence: {report.confidence_level}'
		if report.confidence_reason:
			confidence_line += f' | {report.confidence_reason}'
		lines.extend(['', confidence_line])

	if report.decision_criteria:
		lines.extend(['', 'Decision Criteria:'])
		lines.extend(f'- {item}' for item in report.decision_criteria)

	if report.recommendations:
		lines.extend(['', 'Recommendations:'])
		for idx, item in enumerate(report.recommendations, start=1):
			price = f' | Price: {item.price_text}' if item.price_text else ''
			url = f' | URL: {item.url}' if item.url else ''
			best_for = f' | Best for: {item.best_for}' if item.best_for else ''
			lines.append(f'{idx}. {item.title}{price}{best_for}{url}')
			lines.append(f'   Why: {item.why_it_matches}')
			if item.confidence_level:
				confidence_line = f'   Confidence: {item.confidence_level}'
				if item.confidence_reason:
					confidence_line += f' | {item.confidence_reason}'
				lines.append(confidence_line)
			for coverage_item in item.evidence_coverage:
				lines.append(f'   Coverage: {coverage_item}')
			for tradeoff in item.tradeoffs:
				lines.append(f'   Tradeoff: {tradeoff}')

	if report.supporting_findings:
		lines.extend(['', 'Supporting Findings:'])
		lines.extend(f'- {item}' for item in report.supporting_findings)

	if report.sources:
		lines.extend(['', 'Sources:'])
		for source in report.sources:
			credibility = f', {source.credibility}' if source.credibility else ''
			lines.append(f'- [{source.source_type}{credibility}] {source.title} | {source.url}')
			lines.append(f'  Takeaway: {source.key_takeaway}')

	if report.caveats:
		lines.extend(['', 'Caveats:'])
		lines.extend(f'- {item}' for item in report.caveats)

	if report.next_steps:
		lines.extend(['', 'Next Steps:'])
		lines.extend(f'- {item}' for item in report.next_steps)

	return '\n'.join(lines)


def _candidate_matches_title(candidate: CandidateCatalogEntry, title: str) -> bool:
	target_key = _candidate_identity_key(title)
	if target_key == _candidate_identity_key(candidate.title):
		return True
	return any(target_key == _candidate_identity_key(alias) for alias in candidate.aliases)


def _candidate_best_evidence(candidate: CandidateCatalogEntry, preferred_type: SourceType | None = None) -> CandidateEvidence | None:
	if not candidate.evidence_records:
		return None

	def evidence_score(item: CandidateEvidence) -> tuple[int, int, int, int]:
		type_score = 3 if item.source_type == preferred_type else 0
		if preferred_type == SourceType.shopping and item.source_type == SourceType.shopping and item.url:
			type_score += 3
		if preferred_type == SourceType.review and item.source_type == SourceType.review:
			type_score += 2
		has_url = 1 if item.url else 0
		has_price = 1 if item.price_text else 0
		has_notes = int(bool(item.sound_notes or item.comfort_notes or item.evidence))
		return (type_score, has_url, has_price, has_notes)

	return max(candidate.evidence_records, key=evidence_score)


def _find_related_shopping_evidence(
	ranked: RankedCandidate,
	ranked_candidates_pool: list[RankedCandidate] | None = None,
) -> CandidateEvidence | None:
	direct = _candidate_best_evidence(ranked.candidate, preferred_type=SourceType.shopping)
	if direct and direct.source_type == SourceType.shopping and (direct.url or direct.price_text):
		return direct

	if not ranked_candidates_pool:
		return None

	target_key = _candidate_identity_key(ranked.candidate.title)
	best_match: tuple[int, int, int, CandidateEvidence] | None = None
	for candidate in ranked_candidates_pool:
		if _candidate_identity_key(candidate.candidate.title) == target_key:
			continue
		shopping_evidence = _candidate_best_evidence(candidate.candidate, preferred_type=SourceType.shopping)
		if (
			shopping_evidence is None
			or shopping_evidence.source_type != SourceType.shopping
			or not (shopping_evidence.url or shopping_evidence.price_text)
		):
			continue
		match_score = _candidate_cross_entry_match_score(ranked.candidate.title, candidate.candidate.title)
		if match_score < 5:
			continue
		current = (
			match_score,
			1 if shopping_evidence.url else 0,
			1 if shopping_evidence.price_text else 0,
			shopping_evidence,
		)
		if best_match is None or current[:3] > best_match[:3]:
			best_match = current

	return best_match[3] if best_match else None


def _ranked_candidate_url(
	ranked: RankedCandidate,
	ranked_candidates_pool: list[RankedCandidate] | None = None,
) -> str | None:
	shopping_evidence = _find_related_shopping_evidence(ranked, ranked_candidates_pool=ranked_candidates_pool)
	if shopping_evidence and shopping_evidence.url:
		return shopping_evidence.url
	review_evidence = _candidate_best_evidence(ranked.candidate, preferred_type=SourceType.review)
	if review_evidence and review_evidence.url:
		return review_evidence.url
	return ranked.candidate.urls[0] if ranked.candidate.urls else None


def _ranked_candidate_price(
	ranked: RankedCandidate,
	ranked_candidates_pool: list[RankedCandidate] | None = None,
) -> str | None:
	shopping_evidence = _find_related_shopping_evidence(ranked, ranked_candidates_pool=ranked_candidates_pool)
	if shopping_evidence and shopping_evidence.price_text:
		return shopping_evidence.price_text
	if ranked.candidate.price_texts:
		numeric_prices = [price for price in ranked.candidate.price_texts if _price_value(price) is not None]
		if numeric_prices:
			return min(numeric_prices, key=lambda value: _price_value(value) or float('inf'))
		return ranked.candidate.price_texts[0]
	return None


def _filtered_recommendation_candidates(
	shortlisted_candidates: list[RankedCandidate],
	max_recommendations: int,
) -> list[RankedCandidate]:
	within_or_uncertain = [item for item in shortlisted_candidates if _budget_status_kind(item.budget_status) != 'over']
	if len(within_or_uncertain) >= max_recommendations:
		return within_or_uncertain
	return shortlisted_candidates


def _fallback_recommendation_from_ranked(
	ranked: RankedCandidate,
	ranked_candidates_pool: list[RankedCandidate] | None = None,
) -> SuggestedOption:
	candidate = ranked.candidate
	reason_parts = ranked.reasons[:2] or ['Backfilled from the strongest remaining ranked candidate.']
	tradeoffs: list[str] = []
	if _budget_status_kind(ranked.budget_status) == 'over':
		tradeoffs.append('Price appears over the stated budget.')
	if SourceType.review not in candidate.source_types:
		tradeoffs.append('Review evidence is limited.')
	if not candidate.price_texts:
		tradeoffs.append('Reliable current price was not captured.')
	return SuggestedOption(
		title=candidate.title,
		why_it_matches=' '.join(reason_parts),
		url=_ranked_candidate_url(ranked, ranked_candidates_pool=ranked_candidates_pool),
		price_text=_ranked_candidate_price(ranked, ranked_candidates_pool=ranked_candidates_pool),
		tradeoffs=_unique_text(tradeoffs),
	)


def _normalize_recommendations_to_shortlist(
	recommendations: list[SuggestedOption],
	shortlisted_candidates: list[RankedCandidate],
	max_recommendations: int,
	ranked_candidates_pool: list[RankedCandidate] | None = None,
) -> list[SuggestedOption]:
	normalized: list[SuggestedOption] = []
	used_keys: set[str] = set()
	recommendation_map: dict[str, SuggestedOption] = {}
	candidate_pool = ranked_candidates_pool or shortlisted_candidates
	filtered_shortlist = _filtered_recommendation_candidates(shortlisted_candidates, max_recommendations)

	for recommendation in recommendations:
		matched = next((ranked for ranked in filtered_shortlist if _candidate_matches_title(ranked.candidate, recommendation.title)), None)
		if matched is None:
			continue
		candidate_key = _candidate_identity_key(matched.candidate.title)
		if candidate_key in recommendation_map:
			continue
		recommendation.title = matched.candidate.title
		preferred_url = _ranked_candidate_url(matched, ranked_candidates_pool=candidate_pool)
		preferred_price = _ranked_candidate_price(matched, ranked_candidates_pool=candidate_pool)
		if preferred_url and _url_source_type(preferred_url) == SourceType.shopping:
			recommendation.url = preferred_url
		else:
			recommendation.url = recommendation.url or preferred_url
		if preferred_price:
			recommendation.price_text = preferred_price
		recommendation_map[candidate_key] = recommendation

	for ranked in filtered_shortlist:
		candidate_key = _candidate_identity_key(ranked.candidate.title)
		if candidate_key in used_keys:
			continue
		normalized.append(
			recommendation_map.get(candidate_key)
			or _fallback_recommendation_from_ranked(ranked, ranked_candidates_pool=candidate_pool)
		)
		used_keys.add(candidate_key)
		if len(normalized) >= max_recommendations:
			return normalized

	for ranked in filtered_shortlist:
		candidate_key = _candidate_identity_key(ranked.candidate.title)
		if candidate_key in used_keys:
			continue
		normalized.append(_fallback_recommendation_from_ranked(ranked, ranked_candidates_pool=candidate_pool))
		used_keys.add(candidate_key)
		if len(normalized) >= max_recommendations:
			break

	return normalized


def _recommendation_coverage(ranked: RankedCandidate, has_shopping_listing: bool = False) -> list[str]:
	candidate = ranked.candidate
	coverage: list[str] = []
	if candidate.sound_notes:
		coverage.append('Sound-character evidence captured from review sources.')
	if candidate.comfort_notes:
		coverage.append('Comfort or fit evidence captured from review sources.')
	if has_shopping_listing and (candidate.price_texts or ranked.shopping_backed):
		coverage.append('Shopping price or buy-link evidence captured.')
	elif candidate.price_texts:
		coverage.append('Price evidence captured, but not from a direct shopping listing.')
	if _budget_status_kind(ranked.budget_status) == 'within':
		coverage.append('Budget fit is supported by the captured pricing evidence.')
	elif ranked.budget_status:
		coverage.append(f'Budget status: {ranked.budget_status}.')
	return _unique_text(coverage)


def _recommendation_confidence(ranked: RankedCandidate, has_shopping_listing: bool = False) -> tuple[str, str]:
	candidate = ranked.candidate
	if ranked.review_backed and has_shopping_listing and _budget_status_kind(ranked.budget_status) == 'within':
		return 'high', 'Review, price, and budget evidence all align for this option.'
	if ranked.review_backed and (has_shopping_listing or candidate.price_texts):
		return 'medium', 'Core review evidence is strong, but price or budget verification is incomplete.'
	if ranked.review_backed:
		return 'medium', 'Review evidence supports the fit, but shopping coverage is limited.'
	if has_shopping_listing:
		return 'low', 'Current price or listing evidence exists, but review coverage is limited.'
	return 'low', 'This option is supported by only partial evidence in the dossier.'


def _apply_recommendation_metadata(
	recommendations: list[SuggestedOption],
	shortlisted_candidates: list[RankedCandidate],
) -> list[SuggestedOption]:
	ranked_map = {_candidate_identity_key(item.candidate.title): item for item in shortlisted_candidates}
	for recommendation in recommendations:
		ranked = ranked_map.get(_candidate_identity_key(recommendation.title))
		if ranked is None:
			continue
		has_shopping_listing = ranked.shopping_backed or (
			bool(recommendation.url) and _url_source_type(recommendation.url) == SourceType.shopping
		)
		if not recommendation.evidence_coverage:
			recommendation.evidence_coverage = _recommendation_coverage(ranked, has_shopping_listing=has_shopping_listing)
		if not recommendation.confidence_level or not recommendation.confidence_reason:
			level, reason = _recommendation_confidence(ranked, has_shopping_listing=has_shopping_listing)
			recommendation.confidence_level = recommendation.confidence_level or level
			recommendation.confidence_reason = recommendation.confidence_reason or reason
	return recommendations


def _source_credibility(source: EvidenceSource) -> str:
	source_type = source.source_type.lower()
	host = _normalize_site(urlparse(source.url).netloc)
	if source_type in {'official_docs', 'documentation', 'official'}:
		return 'high'
	if source_type in {'github_repo', 'repository'}:
		return 'high'
	if source_type == 'review':
		return 'medium'
	if source_type == 'shopping':
		return 'medium'
	if host in {'docs.browser-use.com', 'raw.githubusercontent.com', 'github.com'}:
		return 'high'
	return 'low'


def _source_type_priority(source_type: str) -> int:
	normalized = source_type.lower()
	if normalized in {'official_docs', 'documentation', 'official'}:
		return 40
	if normalized in {'github_repo', 'official_repo', 'repository'}:
		return 35
	if normalized == 'review':
		return 30
	if normalized == 'shopping':
		return 20
	return 10


def _report_relevance_terms(report: AssistantReport) -> list[str]:
	terms: list[str] = []
	for recommendation in report.recommendations:
		terms.extend(re.findall(r'[a-z0-9][a-z0-9._-]{2,}', recommendation.title.lower()))
	terms.extend(re.findall(r'[a-z0-9][a-z0-9._-]{3,}', report.user_task.lower()))
	stop_terms = {
		'with',
		'under',
		'good',
		'best',
		'include',
		'links',
		'recommend',
		'investigate',
		'whether',
		'supports',
		'compatible',
		'price',
		'prices',
	}
	return _unique_text([term for term in terms if term not in stop_terms][:20])


def _source_score(source: EvidenceSource, report: AssistantReport) -> int:
	credibility = (source.credibility or _source_credibility(source)).lower()
	credibility_score = {'high': 30, 'medium': 20, 'low': 10}.get(credibility, 0)
	type_score = _source_type_priority(source.source_type)
	text = ' '.join([source.title, source.key_takeaway, source.url]).lower()
	relevance_terms = _report_relevance_terms(report)
	relevance_score = sum(2 for term in relevance_terms if term in text)
	url = urlparse(source.url)
	path_score = 1 if url.path and url.path not in {'', '/'} else 0
	return credibility_score + type_score + relevance_score + path_score


def _normalize_report_sources(report: AssistantReport) -> AssistantReport:
	if not report.sources:
		return report

	unique_sources: list[EvidenceSource] = []
	seen_urls: set[str] = set()
	for source in report.sources:
		url = source.url.strip()
		if not url or url in seen_urls:
			continue
		seen_urls.add(url)
		unique_sources.append(source)

	domain_limit = 2 if report.mode in {AssistantMode.recommendation, AssistantMode.comparison} else 3
	scored_sources = [
		(_source_score(source, report), index, source)
		for index, source in enumerate(unique_sources)
	]
	scored_sources.sort(key=lambda item: (item[0], -item[1]), reverse=True)

	selected: list[EvidenceSource] = []
	domain_counts: dict[str, int] = {}
	seen_domain_takeaway: set[tuple[str, str]] = set()
	max_sources = 6

	for _, _, source in scored_sources:
		domain = _normalize_site(urlparse(source.url).netloc)
		domain_takeaway_key = (domain, source.key_takeaway.strip().lower())
		if domain_counts.get(domain, 0) >= domain_limit:
			continue
		if domain_takeaway_key in seen_domain_takeaway:
			continue
		selected.append(source)
		domain_counts[domain] = domain_counts.get(domain, 0) + 1
		seen_domain_takeaway.add(domain_takeaway_key)
		if len(selected) >= max_sources:
			break

	report.sources = selected
	return report


def _report_confidence(
	plan: TaskPlan,
	report: AssistantReport,
	candidate_catalog: list[CandidateCatalogEntry],
) -> tuple[str, str]:
	high_sources = sum(1 for source in report.sources if (source.credibility or '').lower() == 'high')
	medium_sources = sum(1 for source in report.sources if (source.credibility or '').lower() == 'medium')
	review_backed_candidates = sum(1 for candidate in candidate_catalog if SourceType.review in candidate.source_types)
	shopping_backed_candidates = sum(1 for candidate in candidate_catalog if SourceType.shopping in candidate.source_types)

	if plan.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
		if report.recommendations and review_backed_candidates >= 2 and shopping_backed_candidates >= 1:
			return 'high', 'Multiple review-backed candidates were compared and at least one shopping-price source was captured.'
		if report.recommendations and (review_backed_candidates >= 1 or medium_sources >= 2):
			return 'medium', 'The shortlist is grounded in review or retailer evidence, but some pricing or availability details remain incomplete.'
		return 'low', 'The recommendation relies on limited or incomplete source coverage.'

	if high_sources >= 2 and len(report.supporting_findings) >= 2:
		return 'high', 'The conclusion is supported by multiple primary sources with directly relevant findings.'
	if (high_sources >= 1 or medium_sources >= 2) and report.supporting_findings:
		return 'medium', 'The conclusion is grounded in at least one credible source, but the evidence is partial or uneven.'
	return 'low', 'The conclusion is based on sparse, indirect, or incomplete evidence.'


def _apply_report_confidence(
	plan: TaskPlan,
	report: AssistantReport,
	candidate_catalog: list[CandidateCatalogEntry],
) -> AssistantReport:
	for source in report.sources:
		if not source.credibility:
			source.credibility = _source_credibility(source)
	if not report.confidence_level or not report.confidence_reason:
		level, reason = _report_confidence(plan, report, candidate_catalog)
		report.confidence_level = report.confidence_level or level
		report.confidence_reason = report.confidence_reason or reason
	return _normalize_report_sources(report)


def _fallback_report_from_ranked_candidates(
	plan: TaskPlan,
	candidate_catalog: list[CandidateCatalogEntry],
	shortlisted_candidates: list[RankedCandidate],
	ranked_candidates: list[RankedCandidate],
	max_recommendations: int,
	error: str,
) -> AssistantReport:
	recommendations: list[SuggestedOption] = []
	if plan.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
		recommendations = _normalize_recommendations_to_shortlist(
			[],
			shortlisted_candidates,
			max_recommendations,
			ranked_candidates_pool=ranked_candidates,
		)
		recommendations = _apply_recommendation_metadata(recommendations, shortlisted_candidates)

	supporting_findings: list[str] = []
	sources: list[EvidenceSource] = []
	seen_urls: set[str] = set()
	for candidate in candidate_catalog:
		for record in candidate.evidence_records:
			if record.evidence and record.evidence not in supporting_findings:
				supporting_findings.append(record.evidence)
			elif record.price_text:
				price_finding = f'{record.title} has captured price evidence: {record.price_text}.'
				if price_finding not in supporting_findings:
					supporting_findings.append(price_finding)
			if not record.url or record.url in seen_urls:
				continue
			seen_urls.add(record.url)
			key_takeaway = record.evidence or record.sound_notes or record.comfort_notes or record.price_text or 'Relevant source captured during browser research.'
			sources.append(
				EvidenceSource(
					title=record.source or record.title,
					url=record.url,
					source_type=record.source_type.value,
					key_takeaway=key_takeaway,
					credibility='high' if record.source_type == SourceType.review else 'medium',
				)
			)
			if len(sources) >= 8:
				break
		if len(sources) >= 8:
			break

	if recommendations:
		summary = 'Generated a deterministic recommendation from the collected shopping and review evidence because the model returned an invalid report schema.'
	else:
		summary = 'Collected evidence, but there was not enough structured candidate support to produce confident recommendations.'

	report = AssistantReport(
		user_task=plan.user_task,
		mode=plan.mode,
		summary=summary,
		decision_criteria=plan.decision_criteria,
		recommendations=recommendations,
		supporting_findings=supporting_findings[:8],
		sources=sources,
		caveats=[
			'The final model synthesis returned an invalid structured schema, so this report was generated from deterministic ranking and extracted evidence.',
			f'Synthesis error: {error[:500]}',
		],
		next_steps=['Re-run with more steps or add preferred shopping/review sites if you need stronger price or availability coverage.'],
	)
	return _apply_report_confidence(plan, report, candidate_catalog)


class BrowserResearchAssistant:
	def __init__(self, config: ResearchAssistantConfig, llm: BaseChatModel | None = None):
		self.config = config
		self.llm = llm or resolve_llm(config.model)

	async def run(self, cdp_url: str | None = None) -> AssistantRunArtifacts:
		task_plan = await self._analyze_task()
		stage_results = await self._run_stages(task_plan, cdp_url)
		candidate_catalog = build_candidate_catalog(stage_results)
		research_dossier = self._build_research_dossier(task_plan, stage_results, candidate_catalog)
		report = await self._synthesize_report(task_plan, research_dossier, candidate_catalog)
		return AssistantRunArtifacts(
			task_plan=task_plan,
			stage_results=stage_results,
			candidate_catalog=candidate_catalog,
			research_dossier=research_dossier,
			report=report,
		)

	async def _analyze_task(self) -> TaskPlan:
		fallback = fallback_task_plan(self.config)
		messages = [
			SystemMessage(
				content=(
					'Analyze the user task for a browser research assistant. Infer the task mode, topic, budget, '
					'candidate source domains, and the evidence needed before making a recommendation. '
					'You may add generated_stages for task-specific evidence collection beyond the default shopping/review/web/official arrays. '
					'Each generated stage must have a concrete source_type, source domain or URL, focused queries, and a short purpose. '
					'Use generated_stages when the task asks for community sentiment, forum opinions, social/video reviews, official specs, local marketplaces, or any source strategy not captured by the default arrays. '
					'Do not use generated_stages to remove required retailer or review coverage for recommendation tasks.'
				)
			),
			UserMessage(
				content=(
					f'User task:\n{self.config.task}\n\n'
					f'Locale hint: {fallback.locale}\n'
					f'Preferred shopping sources: {", ".join(self.config.shopping_sites) or "none"}\n'
					f'Preferred review sources: {", ".join(self.config.review_sites) or "none"}\n'
					f'Preferred official sources: {", ".join(self.config.official_sites) or "none"}'
				)
			),
		]

		try:
			response = await self.llm.ainvoke(messages, output_format=TaskPlan)
			plan = response.completion
			plan.user_task = self.config.task
			plan.locale = self.config.locale or fallback.locale if _contains_cjk(self.config.task) else (plan.locale or fallback.locale)
			if fallback.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
				plan.mode = fallback.mode
			else:
				plan.mode = plan.mode or fallback.mode
			fallback_budget_currency = _currency_code(fallback.budget)
			plan_budget_currency = _currency_code(plan.budget)
			if fallback.budget and (plan.budget is None or (fallback_budget_currency and fallback_budget_currency != plan_budget_currency)):
				plan.budget = fallback.budget
			plan.shopping_sources = _normalize_stage_sources(
				self.config.shopping_sites,
				plan.shopping_sources,
				fallback.shopping_sources,
				SourceType.shopping,
			)
			plan.review_sources = _normalize_stage_sources(
				self.config.review_sites,
				plan.review_sources,
				fallback.review_sources,
				SourceType.review,
			)
			if self.config.official_sites:
				plan.official_sources = _normalize_stage_sources(
					self.config.official_sites,
					plan.official_sources,
					fallback.official_sources,
					SourceType.official,
				)
			elif plan.mode in {AssistantMode.research, AssistantMode.generic}:
				plan.official_sources = _normalize_stage_sources([], [], fallback.official_sources, SourceType.official)
			else:
				plan.official_sources = []
			llm_web_sources = plan.web_sources + plan.official_sources if plan.mode in {AssistantMode.research, AssistantMode.generic} else []
			if plan.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
				plan.web_sources = _normalize_stage_sources(self.config.web_sites, [], fallback.web_sources, SourceType.web)
			else:
				plan.web_sources = _normalize_stage_sources(
					self.config.web_sites,
					llm_web_sources,
					fallback.web_sources,
					SourceType.web,
				)
			plan.web_sources = _filter_web_sources_for_explicit_seeds(plan.web_sources, fallback.web_sources)
			plan.web_sources = _dedupe_web_sources_preserve_explicit_urls(plan.web_sources)
			shopping_queries = plan.shopping_queries or fallback.shopping_queries
			review_queries = plan.review_queries or fallback.review_queries
			if plan.locale == 'zh-CN':
				review_queries = [self.config.task, *review_queries]
			plan.shopping_queries = normalize_stage_queries(shopping_queries, plan.shopping_sources)
			plan.review_queries = normalize_stage_queries(review_queries, plan.review_sources)
			plan.official_queries = normalize_stage_queries(plan.official_queries or fallback.official_queries, plan.official_sources)
			plan.web_queries = normalize_stage_queries(plan.web_queries or fallback.web_queries, plan.web_sources)
			plan.generated_stages = _normalize_generated_stages(plan.generated_stages, fallback)
			if plan.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
				plan.decision_criteria = fallback.decision_criteria
				plan.required_deliverables = fallback.required_deliverables
			else:
				plan.decision_criteria = plan.decision_criteria or fallback.decision_criteria
				plan.required_deliverables = plan.required_deliverables or fallback.required_deliverables
			return plan
		except Exception:
			return fallback

	async def _run_stages(self, plan: TaskPlan, cdp_url: str | None) -> list[StageResult]:
		stage_specs: list[tuple[SourceType, str, list[str]]] = []
		seen_stage_specs: set[tuple[str, str]] = set()
		review_stage_limit = 5 if plan.locale == 'zh-CN' else 3
		web_stage_limit = 3 if plan.mode in {AssistantMode.research, AssistantMode.generic} else 1
		shopping_stage_limit = 3 if plan.locale == 'zh-CN' and not self.config.shopping_sites else 2

		def add_stage(source_type: SourceType, source: str, queries: list[str]) -> None:
			key = (source_type.value, _normalize_site(source))
			if key in seen_stage_specs:
				return
			seen_stage_specs.add(key)
			stage_specs.append((source_type, source, queries))

		for source in sorted(plan.web_sources, key=lambda item: _source_priority_key(SourceType.web, item, plan.locale))[:web_stage_limit]:
			add_stage(SourceType.web, source, plan.web_queries)
		for source in sorted(plan.shopping_sources, key=lambda item: _source_priority_key(SourceType.shopping, item, plan.locale))[:shopping_stage_limit]:
			add_stage(SourceType.shopping, source, plan.shopping_queries)
		for source in sorted(plan.review_sources, key=lambda item: _source_priority_key(SourceType.review, item, plan.locale))[:review_stage_limit]:
			add_stage(SourceType.review, source, plan.review_queries)
		for source in sorted(plan.official_sources, key=lambda item: _source_priority_key(SourceType.official, item, plan.locale))[:1]:
			add_stage(SourceType.official, source, plan.official_queries)
		for generated_stage in plan.generated_stages:
			add_stage(generated_stage.source_type, generated_stage.source, generated_stage.queries)

		if not stage_specs:
			return []

		total_budget = max(self.config.max_steps, len(stage_specs) * 2)
		base_steps = max(2, total_budget // len(stage_specs))
		stage_results: list[StageResult] = []

		for index, (source_type, source, queries) in enumerate(stage_specs):
			remaining_stages = len(stage_specs) - index
			stage_steps = max(2, total_budget - base_steps * index)
			if remaining_stages > 1:
				stage_steps = max(2, min(base_steps, stage_steps - 2 * (remaining_stages - 1)))
			stage_result = await self._run_stage(plan, source_type, [source], queries[:2], stage_steps, cdp_url)
			stage_results.append(stage_result)

		return stage_results

	async def _run_stage(
		self,
		plan: TaskPlan,
		source_type: SourceType,
		sources: list[str],
		queries: list[str],
		max_steps: int,
		cdp_url: str | None,
	) -> StageResult:
		stage_result = await self._execute_stage_once(plan, source_type, sources, queries, max_steps, cdp_url)
		if cdp_url and stage_result.run_error and not stage_result.visited_urls:
			fallback_result = await self._execute_stage_once(plan, source_type, sources, queries, max_steps, None)
			fallback_result.errors = [
				*([f'CDP fallback trigger: {stage_result.run_error}'] if stage_result.run_error else []),
				*fallback_result.errors,
			]
			return fallback_result
		return stage_result

	async def _summarize_http_stage(
		self,
		plan: TaskPlan,
		source_type: SourceType,
		sources: list[str],
		queries: list[str],
		targets: ResolvedStageTargets,
	) -> str | None:
		if _requires_browser_observation(source_type, sources):
			return None

		adapter = get_site_adapter(sources[0], source_type) if sources else None
		page_chunks: list[str] = []

		if source_type == SourceType.shopping and sources:
			search_url = build_source_entry_urls(source_type, sources, queries)[0]
			html_text = await fetch_search_page_html(search_url)
			if not html_text:
				return None
			shopping_candidates = extract_shopping_candidates(
				adapter.domain,
				html_text,
				limit=max(self.config.max_recommendations + 2, 4),
				query=queries[0] if queries else None,
			)
			if not shopping_candidates:
				return None
			candidate_lines = []
			for candidate in shopping_candidates:
				price = candidate.price_text or 'unknown price'
				rating = f' | Rating: {candidate.rating_text}' if candidate.rating_text else ''
				candidate_lines.append(f'- {candidate.title} | Price: {price}{rating} | URL: {candidate.url}')
			page_chunks.append(
				f'Shopping source: {sources[0]}\n'
				f'Search URL: {search_url}\n'
				'Extracted product candidates:\n'
				+ '\n'.join(candidate_lines)
			)

		if source_type == SourceType.review:
			if not targets.resolved_urls:
				return None
			for url in targets.resolved_urls[:2]:
				html_text = await fetch_search_page_html(url)
				if not html_text:
					continue
				title = extract_page_title(html_text) or url
				excerpt = html_to_text_excerpt(html_text)
				if not excerpt:
					continue
				page_chunks.append(f'URL: {url}\nTitle: {title}\nExcerpt:\n{excerpt}')

		if source_type in {SourceType.official, SourceType.web}:
			candidate_urls = targets.resolved_urls or targets.initial_urls
			for url in candidate_urls[:4]:
				document_text, content_type = await fetch_document_text(url)
				if not document_text:
					continue
				if 'text/html' in (content_type or ''):
					title = extract_page_title(document_text) or url
					excerpt = html_to_text_excerpt(document_text, max_chars=3500)
				else:
					title = url.rsplit('/', 1)[-1] or url
					excerpt = plain_text_excerpt(document_text, max_chars=3500)
				if not excerpt:
					continue
				page_chunks.append(f'URL: {url}\nTitle: {title}\nExcerpt:\n{excerpt}')

		if not page_chunks:
			return None

		stage_label = {
			SourceType.shopping: 'shopping',
			SourceType.review: 'review',
			SourceType.official: 'official',
			SourceType.web: 'web',
		}[source_type]
		messages = [
			SystemMessage(
				content=(
					f'You are summarizing fetched {stage_label} pages for a browser research assistant. '
					'Use only the provided excerpts or extracted candidates. Stay grounded and explicit about uncertainty. '
					'Return markdown with exactly these sections: '
					'## Stage Summary, ## Findings, ## Candidate Options, ## Failed Sources.'
				)
			),
			UserMessage(
				content=(
					f'Original task: {plan.user_task}\n'
					f'Source type: {source_type.value}\n'
					f'Sources: {", ".join(sources)}\n'
					f'Queries: {", ".join(queries)}\n\n'
					'Fetched evidence:\n\n'
					+ '\n\n---\n\n'.join(page_chunks)
				)
			),
		]

		try:
			response = await self.llm.ainvoke(messages)
			summary = (response.completion or '').strip()
			return summary or None
		except Exception:
			return None

	async def _extract_stage_candidates(
		self,
		source_type: SourceType,
		sources: list[str],
		stage_text: str | None,
		shopping_candidates: list[ShoppingCandidate] | None = None,
		review_candidates: list[CandidateEvidence] | None = None,
	) -> list[CandidateEvidence]:
		if source_type == SourceType.web:
			return []
		if source_type == SourceType.shopping and shopping_candidates is not None:
			return shopping_candidates_to_evidence(shopping_candidates, sources[0] if sources else 'unknown')
		if source_type == SourceType.review and review_candidates is not None:
			return review_candidates
		if not stage_text or not sources:
			return []

		messages = [
			SystemMessage(
				content=(
					'Extract structured product candidates from a stage result for a browser research assistant. '
					'Only keep products explicitly named in the text. Never invent missing URLs, prices, ratings, sound notes, or comfort notes. '
					'Return a structured candidate list.'
				)
			),
			UserMessage(
				content=(
					f'Source type: {source_type.value}\n'
					f'Source domain: {sources[0]}\n\n'
					f'Stage text:\n{stage_text}'
				)
			),
		]

		try:
			response = await self.llm.ainvoke(messages, output_format=StageCandidateExtraction)
			extraction = response.completion
		except Exception:
			return []

		candidates: list[CandidateEvidence] = []
		for candidate in extraction.candidates:
			if not candidate.title.strip():
				continue
			candidate.source_type = source_type
			candidate.source = candidate.source or sources[0]
			candidates.append(candidate)
		return candidates

	async def _collect_review_candidates(
		self,
		sources: list[str],
		targets: ResolvedStageTargets,
		query: str | None = None,
	) -> list[CandidateEvidence]:
		if not sources:
			return []
		site = get_site_adapter(sources[0], SourceType.review).domain
		candidates: list[CandidateEvidence] = []
		for url in targets.resolved_urls[:3]:
			html_text = await fetch_search_page_html(url)
			if not html_text:
				continue
			if site == 'sspai.com' and '/tag/' in urlparse(url).path:
				post_urls = extract_site_candidate_urls(site, html_text, limit=3, query=query)
				for post_url in post_urls:
					post_html = await fetch_search_page_html(post_url)
					if not post_html:
						continue
					page_candidates = extract_review_candidates(site, post_html, post_url)
					for candidate in page_candidates:
						if not _review_candidate_matches_query(candidate, query):
							continue
						if candidate not in candidates:
							candidates.append(candidate)
				continue
			if site == 'ifanr.com' and '/category/' in urlparse(url).path:
				for api_url in IFANR_REVIEW_API_URLS:
					payload = await fetch_ifanr_api_payload(api_url)
					if not payload:
						continue
					post_urls = extract_ifanr_api_candidate_urls(payload, query=query, limit=3)
					for post_url in post_urls:
						post_html = await fetch_search_page_html(post_url)
						if not post_html:
							continue
					page_candidates = extract_review_candidates(site, post_html, post_url)
					for candidate in page_candidates:
						if site == 'ifanr.com':
							if not _ifanr_review_candidate_matches_query(candidate, query):
								continue
						elif not _review_candidate_matches_query(candidate, query):
							continue
						if candidate not in candidates:
							candidates.append(candidate)
				continue
			page_candidates = extract_review_candidates(site, html_text, url)
			for candidate in page_candidates:
				if site == 'ifanr.com':
					if not _ifanr_review_candidate_matches_query(candidate, query):
						continue
				elif not _review_candidate_matches_query(candidate, query):
					continue
				if candidate not in candidates:
					candidates.append(candidate)
		return candidates

	async def _execute_stage_once(
		self,
		plan: TaskPlan,
		source_type: SourceType,
		sources: list[str],
		queries: list[str],
		max_steps: int,
		cdp_url: str | None,
	) -> StageResult:
		targets = await resolve_stage_targets(source_type, sources, queries)
		prompt = build_stage_prompt(
			plan,
			source_type,
			sources,
			queries,
			self.config.max_recommendations,
			initial_urls=targets.initial_urls,
		)
		history: AgentHistoryList | None = None
		run_error: str | None = None
		candidate_evidence: list[CandidateEvidence] = []
		http_summary = await self._summarize_http_stage(plan, source_type, sources, queries, targets)
		if http_summary:
			shopping_candidates: list[ShoppingCandidate] | None = None
			review_candidates: list[CandidateEvidence] | None = None
			if source_type == SourceType.shopping and sources:
				search_url = build_source_entry_urls(source_type, sources, queries)[0]
				html_text = await fetch_search_page_html(search_url)
				if html_text:
					shopping_candidates = extract_shopping_candidates(
						get_site_adapter(sources[0], source_type).domain,
						html_text,
						limit=max(self.config.max_recommendations + 2, 4),
						query=queries[0] if queries else None,
					)
			if source_type == SourceType.review:
				review_candidates = await self._collect_review_candidates(sources, targets, queries[0] if queries else None)
			candidate_evidence = await self._extract_stage_candidates(
				source_type,
				sources,
				http_summary,
				shopping_candidates=shopping_candidates,
				review_candidates=review_candidates,
			)
			return StageResult(
				stage_name=f'{source_type.value}_collection',
				source_type=source_type,
				sources=sources,
				initial_urls=targets.initial_urls,
				resolved_urls=targets.resolved_urls,
				fetch_mode_used='http',
				blocked_reason=targets.blocked_reason,
				prompt=prompt,
				final_result=http_summary,
				candidate_evidence=candidate_evidence,
				visited_urls=targets.resolved_urls,
				errors=[],
				run_error=None,
			)

		try:
			initial_urls = targets.initial_urls
			initial_actions = [{'navigate': {'url': url, 'new_tab': index > 0}} for index, url in enumerate(initial_urls)]
			allowed_domains = {_normalize_site(source) for source in sources}
			for source in sources:
				allowed_domains.update(get_site_adapter(source, source_type).allowed_domains)
			for url in initial_urls + targets.resolved_urls:
				parsed = urlparse(url)
				if parsed.netloc:
					allowed_domains.add(_normalize_site(parsed.netloc))
			browser_kwargs = {
				'cdp_url': cdp_url,
				'allowed_domains': sorted(domain for domain in allowed_domains if domain),
				'enable_default_extensions': False,
			}
			if cdp_url is None:
				browser_kwargs['headless'] = True
			browser = Browser(**browser_kwargs)
			agent = Agent(
				task=prompt,
				llm=self.llm,
				browser=browser,
				initial_actions=initial_actions,
				use_vision=_stage_use_vision(self.config, source_type, sources),
				use_thinking=False,
				llm_timeout=self.config.llm_timeout,
				max_actions_per_step=self.config.max_actions_per_step,
			)
			history = await agent.run(max_steps=max_steps)
			candidate_evidence = await self._extract_stage_candidates(source_type, sources, history.final_result() if history else None)
		except Exception as exc:
			run_error = str(exc)

		return StageResult(
			stage_name=f'{source_type.value}_collection',
			source_type=source_type,
			sources=sources,
			initial_urls=initial_urls if 'initial_urls' in locals() else [],
			resolved_urls=targets.resolved_urls,
			fetch_mode_used='browser',
			blocked_reason=targets.blocked_reason,
			prompt=prompt,
			final_result=history.final_result() if history else None,
			candidate_evidence=candidate_evidence,
			visited_urls=[url for url in history.urls() if url] if history else [],
			errors=[error for error in history.errors() if error] if history else [],
			run_error=run_error,
		)

	def _build_research_dossier(
		self,
		plan: TaskPlan,
		stage_results: list[StageResult],
		candidate_catalog: list[CandidateCatalogEntry],
	) -> str:
		ranked_candidates = rank_candidate_catalog(plan, candidate_catalog)
		chunks = [
			'# Browser Research Dossier',
			f'Original task: {plan.user_task}',
			'',
			'## Task Plan',
			f'- Mode: {plan.mode.value}',
			f'- Locale: {plan.locale}',
			f'- Topic: {plan.topic}',
			f'- Budget: {plan.budget or "not explicitly stated"}',
			'- Decision criteria:',
		]
		chunks.extend(f'  - {item}' for item in plan.decision_criteria)
		if candidate_catalog:
			chunks.extend(['', '## Candidate Catalog'])
			for ranked in ranked_candidates[:10]:
				candidate = ranked.candidate
				chunks.append(f'- Title: {candidate.title}')
				chunks.append(f'  - Ranking score: {ranked.score}')
				if ranked.reasons:
					chunks.append(f'  - Ranking reasons: {" | ".join(ranked.reasons[:4])}')
				if ranked.budget_status:
					chunks.append(f'  - Budget status: {ranked.budget_status}')
				if candidate.aliases:
					chunks.append(f'  - Aliases: {", ".join(candidate.aliases)}')
				if candidate.source_types:
					chunks.append(f'  - Source types: {", ".join(item.value for item in candidate.source_types)}')
				if candidate.sources:
					chunks.append(f'  - Sources: {", ".join(candidate.sources)}')
				if candidate.price_texts:
					chunks.append(f'  - Prices: {", ".join(candidate.price_texts)}')
				if candidate.urls:
					chunks.append(f'  - URLs: {", ".join(candidate.urls[:3])}')
				if candidate.sound_notes:
					chunks.append(f'  - Sound notes: {" | ".join(candidate.sound_notes[:3])}')
				if candidate.comfort_notes:
					chunks.append(f'  - Comfort notes: {" | ".join(candidate.comfort_notes[:3])}')
				if candidate.evidence_points:
					chunks.append(f'  - Evidence: {" | ".join(candidate.evidence_points[:3])}')

		for stage in stage_results:
			chunks.extend(
				[
					'',
					f'## Stage: {stage.stage_name}',
					f'- Source type: {stage.source_type.value}',
					f'- Sources: {", ".join(stage.sources) if stage.sources else "none"}',
					f'- Initial URLs: {", ".join(stage.initial_urls) if stage.initial_urls else "none"}',
					f'- Resolved URLs: {", ".join(stage.resolved_urls) if stage.resolved_urls else "none"}',
					f'- Fetch mode: {stage.fetch_mode_used}',
				]
			)
			if stage.blocked_reason:
				chunks.append(f'- Blocked marker: {stage.blocked_reason}')
			if stage.final_result:
				chunks.extend(['', stage.final_result])
			if stage.candidate_evidence:
				chunks.extend(['', 'Structured candidates:'])
				for candidate in stage.candidate_evidence[:6]:
					price = f' | Price: {candidate.price_text}' if candidate.price_text else ''
					url = f' | URL: {candidate.url}' if candidate.url else ''
					chunks.append(f'- {candidate.title}{price}{url}')
			if stage.visited_urls:
				chunks.extend(['', 'Visited URLs:'])
				chunks.extend(f'- {url}' for url in stage.visited_urls[-10:])
			if stage.errors:
				chunks.extend(['', 'Errors:'])
				chunks.extend(f'- {error}' for error in stage.errors[-8:])
			if stage.run_error:
				chunks.extend(['', 'Runtime failure:', stage.run_error])

		return '\n'.join(chunks)

	async def _synthesize_report(
		self,
		plan: TaskPlan,
		dossier: str,
		candidate_catalog: list[CandidateCatalogEntry],
	) -> AssistantReport:
		ranked_candidates = rank_candidate_catalog(plan, candidate_catalog)
		eligible_candidates = [item for item in ranked_candidates if item.score >= 4]
		if not eligible_candidates:
			eligible_candidates = ranked_candidates
		shortlisted_candidates = eligible_candidates[:6]
		if plan.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
			shortlisted_candidates = _filtered_recommendation_candidates(eligible_candidates, self.config.max_recommendations)[:6]
			if not shortlisted_candidates:
				shortlisted_candidates = eligible_candidates[:6]

		catalog_lines: list[str] = []
		for index, ranked in enumerate(shortlisted_candidates, start=1):
			candidate = ranked.candidate
			catalog_lines.append(f'{index}. {candidate.title}')
			catalog_lines.append(f'  Score: {ranked.score}')
			if ranked.budget_status:
				catalog_lines.append(f'  Budget status: {ranked.budget_status}')
			if ranked.reasons:
				catalog_lines.append(f'  Ranking reasons: {" | ".join(ranked.reasons[:4])}')
			if candidate.price_texts:
				catalog_lines.append(f'  Prices: {", ".join(candidate.price_texts)}')
			if candidate.sources:
				catalog_lines.append(f'  Sources: {", ".join(candidate.sources)}')
			if candidate.urls:
				catalog_lines.append(f'  URLs: {", ".join(candidate.urls[:3])}')
			if candidate.sound_notes:
				catalog_lines.append(f'  Sound notes: {" | ".join(candidate.sound_notes[:3])}')
			if candidate.comfort_notes:
				catalog_lines.append(f'  Comfort notes: {" | ".join(candidate.comfort_notes[:3])}')

		if plan.mode in {AssistantMode.research, AssistantMode.generic}:
			synthesis_policy = (
				'This is a research-style task, not necessarily a product recommendation. '
				'Recommendations are optional and may be an empty list when the task is informational. '
				'Focus on a clear summary, source-backed findings, caveats, and next steps. '
				'Only include recommendations when the dossier actually supports concrete options.'
			)
			shortlist_policy = (
				'If the ranked shortlist is empty or not relevant to the user task, leave recommendations empty. '
				'Do not force product picks for documentation, API, or general research tasks.'
			)
		else:
			synthesis_policy = (
				'Recommendations must be grounded in the dossier. Prefer candidates supported by both shopping and review evidence when available. '
				'Use the ranked shortlist as the default ordering unless the dossier contains a concrete reason to override it. '
				'Do not recommend clearly over-budget items when a within-budget option has stronger or comparable evidence.'
			)
			shortlist_policy = (
				'Final recommendation titles must come from the ranked shortlist only. '
				f'Prefer the first {min(len(shortlisted_candidates), self.config.max_recommendations + 2)} shortlist entries unless there is explicit contradictory evidence. '
				'If you skip a higher-ranked candidate, mention the concrete tradeoff or missing evidence. '
				'Strongly prefer candidates with review-backed sound or comfort evidence. '
				'Prefer candidates that also have shopping-source price/link evidence. '
				'Treat the ranking score as a deterministic prior; only override it when the dossier contains stronger contradictory evidence. '
				'Mention when a candidate is only weakly supported or missing a reliable price.'
			)

		messages = [
			SystemMessage(
				content=(
					'You are a pragmatic synthesis assistant. Convert the research dossier into a structured report. '
					f'{synthesis_policy} '
					'If the evidence is weak or missing, say so clearly. '
					'Populate confidence_level as high, medium, or low, and confidence_reason with one short sentence. '
					'For each source, set credibility to high, medium, or low based on how authoritative and directly relevant it is. '
					'For recommendation items, also populate confidence_level, confidence_reason, and evidence_coverage when the dossier supports them.'
				)
			),
			UserMessage(
				content=(
					f'User task:\n{plan.user_task}\n\n'
					f'Limit final recommendations to at most {self.config.max_recommendations}.\n'
					f'Required deliverables: {", ".join(plan.required_deliverables)}\n\n'
					'Important recommendation policy:\n'
					f'- {shortlist_policy}\n\n'
					'Ranked candidate shortlist (already sorted strongest to weakest):\n'
					+ ('\n'.join(catalog_lines) if catalog_lines else 'none')
					+ '\n\n'
					f'Dossier:\n{dossier}'
				)
			),
		]

		try:
			response = await self.llm.ainvoke(messages, output_format=AssistantReport)
		except Exception as exc:
			return _fallback_report_from_ranked_candidates(
				plan,
				candidate_catalog,
				shortlisted_candidates,
				ranked_candidates,
				self.config.max_recommendations,
				str(exc),
			)
		report = response.completion
		report.user_task = plan.user_task
		report.mode = plan.mode
		if plan.mode in {AssistantMode.recommendation, AssistantMode.comparison}:
			report.recommendations = _normalize_recommendations_to_shortlist(
				report.recommendations,
				shortlisted_candidates,
				self.config.max_recommendations,
				ranked_candidates_pool=ranked_candidates,
			)
			report.recommendations = _apply_recommendation_metadata(report.recommendations, shortlisted_candidates)
		else:
			report.recommendations = report.recommendations[: self.config.max_recommendations]
		return _apply_report_confidence(plan, report, candidate_catalog)
