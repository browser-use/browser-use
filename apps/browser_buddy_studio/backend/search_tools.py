from urllib.parse import quote_plus

from browser_use.agent.views import ActionResult
from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.session import BrowserSession
from browser_use.tools.service import Tools

SEARCH_ENGINES = {
	'bing_cn': ('Bing 中国', 'https://cn.bing.com/search?q={query}'),
	'bing': ('Bing', 'https://www.bing.com/search?q={query}'),
	'baidu': ('百度', 'https://www.baidu.com/s?wd={query}'),
	'sogou': ('搜狗', 'https://www.sogou.com/web?query={query}'),
	'so': ('360 搜索', 'https://www.so.com/s?q={query}'),
	'google': ('Google', 'https://www.google.com/search?q={query}&udm=14'),
	'duckduckgo': ('DuckDuckGo', 'https://duckduckgo.com/?q={query}'),
}

AUTO_ORDER = ['bing_cn', 'sogou', 'baidu', 'so', 'bing', 'google', 'duckduckgo']
BLOCKED_URL_MARKERS = ('captcha', 'verify', 'wappass', 'antispider', 'challenge', 'security')


def _engine_order(selected: str) -> list[str]:
	if selected == 'auto':
		return AUTO_ORDER
	return [selected] + [engine for engine in AUTO_ORDER if engine != selected]


def build_tools(search_engine: str = 'auto') -> Tools:
	if search_engine not in ('auto', *SEARCH_ENGINES):
		search_engine = 'auto'
	tools = Tools(exclude_actions=['search'])
	order = _engine_order(search_engine)

	@tools.action(
		'Search the web with the app-configured search engine. '
		'Provide only the query; the app automatically falls back to another engine if the first one is unavailable.',
		terminates_sequence=True,
	)
	async def web_search(query: str, browser_session: BrowserSession) -> ActionResult:
		encoded = quote_plus(query)
		failures: list[str] = []

		for engine in order:
			label, template = SEARCH_ENGINES[engine]
			url = template.format(query=encoded)
			try:
				event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=False))
				await event
				await event.event_result(raise_if_any=True, raise_if_none=False)
				current_url = (await browser_session.get_current_page_url()).lower()
				if any(marker in current_url for marker in BLOCKED_URL_MARKERS):
					failures.append(f'{label}: redirected to verification page')
					continue
				memory = f"Searched {label} for '{query}'"
				return ActionResult(extracted_content=memory, long_term_memory=memory)
			except Exception as e:
				failures.append(f'{label}: {type(e).__name__}: {e}')

		return ActionResult(error='所有搜索引擎都不可用：' + '; '.join(failures))

	return tools
