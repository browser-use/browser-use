from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from browser_use.llm.messages import SystemMessage, UserMessage

logger = logging.getLogger('browser_buddy.intent')

URL_RE = re.compile(r'https?://|www\.', re.IGNORECASE)

BROWSER_HINTS = (
	'打开',
	'访问',
	'搜索',
	'搜一下',
	'查询',
	'查一下',
	'查查',
	'登录',
	'点击',
	'下载',
	'上传',
	'提取',
	'抓取',
	'爬取',
	'比价',
	'下单',
	'购买',
	'加入购物车',
	'看评论',
	'商品',
	'淘宝',
	'天猫',
	'京东',
	'小红书',
	'抖音',
	'rednote',
	'xiaohongshu',
	'douyin',
	'拼多多',
	'百度',
	'搜狗',
	'谷歌',
	'google',
	'bing',
	'github',
	'youtube',
	'bilibili',
	'微博',
	'知乎',
	'amazon',
	'open ',
	'go to ',
	'visit ',
	'search ',
	'click ',
	'download ',
	'upload ',
	'extract ',
	'scrape ',
	'compare ',
	'buy ',
	'order ',
	'login ',
	'shop ',
	'find ',
)

CONTINUATION_PATTERNS = (
	r'^(继续|继续吧|接着|下一步|然后呢|go on|continue)[!.?。！？ ]*$',
)

CHAT_PATTERNS = (
	r'^(hi|hello|hey|yo)[!.?。！？ ]*$',
	r'^(你好|您好|嗨|哈喽|在吗|早上好|晚上好|晚安|再见|拜拜|谢谢|多谢|感谢)[!.?。！？ ]*$',
	r'^(你是谁|你能做什么|你会什么|怎么用|帮助|help)[!.?。！？ ]*$',
)


class IntentDecision(BaseModel):
	needs_browser: bool
	reason: str = ''


def _quick_classify(text: str, previous_context: str | None = None) -> bool | None:
	stripped = text.strip()
	lower = stripped.lower()

	if URL_RE.search(stripped):
		return True
	if any(hint.lower() in lower for hint in BROWSER_HINTS):
		return True
	if any(re.fullmatch(pattern, lower.strip()) for pattern in CHAT_PATTERNS):
		return False
	if previous_context and any(re.fullmatch(pattern, lower.strip()) for pattern in CONTINUATION_PATTERNS):
		return True
	if len(stripped) <= 6:
		return False
	return None


async def needs_browser(task: str, llm, previous_context: str | None = None) -> bool:
	quick = _quick_classify(task, previous_context)
	if quick is not None:
		return quick

	prompt = (
		'Decide whether the user request requires controlling a real web browser.\n'
		'Return needs_browser=true only when the user asks to open/visit a site, search the web, '
		'click/type/login on a website, download/upload files, extract data from a webpage, compare product prices, '
		'shop, or otherwise interact with a live browser.\n'
		'Return needs_browser=false for greetings, small talk, general knowledge, coding help, explanations, '
		'writing, translation, math, or other questions that can be answered without a browser.\n'
		'If previous context exists, use it only to interpret short follow-ups.\n\n'
		f'User message:\n{task}'
	)
	if previous_context:
		prompt += f'\n\nPrevious context (truncated):\n{previous_context[:2000]}'

	try:
		response = await llm.ainvoke(
			[
				SystemMessage(content='You classify user intent for a desktop browser agent.'),
				UserMessage(content=prompt),
			],
			output_format=IntentDecision,
		)
		decision = response.completion
		logger.info(f'Intent: needs_browser={decision.needs_browser} reason={decision.reason[:120]}')
		return bool(decision.needs_browser)
	except Exception as e:
		logger.warning(f'Intent classification failed: {type(e).__name__}: {e}')
		return False


async def chat_reply(llm, task: str, previous_context: str | None = None) -> str:
	system = (
		'You are BrowserBuddy, a friendly macOS assistant for browser automation. '
		'The user is chatting and does not need a browser for this message. '
		'Reply naturally, concisely, and in the same language as the user. '
		'Do not claim that you browsed a website or executed a browser task.'
	)
	content = task
	if previous_context:
		content = f'Earlier conversation context:\n{previous_context[:4000]}\n\nCurrent message:\n{task}'

	try:
		response = await llm.ainvoke([SystemMessage(content=system), UserMessage(content=content)])
		return str(response.completion or '').strip() or '我在。你可以告诉我需要浏览器完成什么任务。'
	except Exception as e:
		logger.warning(f'Chat reply failed: {type(e).__name__}: {e}')
		return '你好，我是 BrowserBuddy。你可以告诉我需要浏览器完成什么任务，比如搜索、比价、提取网页信息或下载文件。'
