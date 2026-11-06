# pyright: reportMissingImports=false, reportMissingTypeStubs=false
"""BrowserBuddy: a small Gradio desktop MVP for browser-use.

Run in development:
    python app.py

Build a macOS app:
    ./build_mac.sh
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

APP_NAME = 'BrowserBuddy'
APP_SUPPORT_DIR = Path.home() / 'Library' / 'Application Support' / APP_NAME
LOG_DIR = Path.home() / 'Library' / 'Logs' / APP_NAME
PROFILE_DIR = APP_SUPPORT_DIR / 'browser-profile'
ARTIFACT_DIR = APP_SUPPORT_DIR / 'artifact-previews'

KEYRING_SERVICE = APP_NAME
KEYRING_USERNAME = 'deepseek-api-key'
DEFAULT_MODEL = 'deepseek-v4-flash'
DEFAULT_BASE_URL = 'https://api.deepseek.com'

URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')
TRAILING_URL_CHARS = '.,;:!?，。；：！？'
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')

CUSTOM_CSS = """
:root {
    --bb-radius: 14px;
}
body, .gradio-container {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif !important;
}
.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    padding: 24px !important;
}
.hero h1 {
    font-size: 30px !important;
    letter-spacing: -0.02em;
    margin-bottom: 6px !important;
}
.hero p {
    font-size: 15px !important;
    color: #64748b;
}
.prose h2 {
    font-size: 22px !important;
    margin-top: 20px !important;
}
.prose h3 {
    font-size: 18px !important;
}
.prose p, .prose li {
    font-size: 15px !important;
    line-height: 1.7 !important;
}
textarea, input[type="text"], input[type="password"] {
    font-size: 16px !important;
    line-height: 1.6 !important;
}
label {
    font-size: 15px !important;
    font-weight: 600 !important;
}
.bb-section-title {
    font-size: 18px !important;
    font-weight: 700 !important;
    margin: 18px 0 10px !important;
}
.bb-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 12px;
}
.bb-card {
    display: flex;
    gap: 12px;
    padding: 12px;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    background: #ffffff;
    text-decoration: none !important;
    color: inherit !important;
    transition: border-color 0.15s, box-shadow 0.15s;
}
.bb-card:hover {
    border-color: #93c5fd;
    box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
}
.bb-thumb {
    width: 76px;
    height: 76px;
    flex: 0 0 76px;
    overflow: hidden;
    border-radius: 8px;
    background: #f1f5f9;
}
.bb-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
.bb-thumb-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    color: #64748b;
    background: #f1f5f9;
}
.bb-body {
    min-width: 0;
}
.bb-title {
    font-size: 14px !important;
    font-weight: 600 !important;
    line-height: 1.4;
    margin-bottom: 4px;
}
.bb-desc {
    font-size: 12px !important;
    color: #64748b !important;
    line-height: 1.45;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.bb-domain {
    font-size: 11px !important;
    color: #2563eb !important;
    margin-top: 4px;
}
@media (prefers-color-scheme: dark) {
    .bb-card {
        background: #0f172a;
        border-color: #334155;
    }
    .bb-thumb,
    .bb-thumb-placeholder {
        background: #1e293b;
    }
}
"""

EXAMPLE_TASKS = {
	'中文｜信息检索：搜索并总结': ('打开 Google 搜索 "what is browser automation"，总结前 3 个自然结果，包含标题和完整链接。'),
	'中文｜数据提取：抓取书籍信息': (
		'打开 https://books.toscrape.com，进入 Mystery 分类，提取前 5 本书的标题、价格和评分，保存到 mystery_books.csv。'
	),
	'中文｜比价：找最低价': (
		'打开 https://books.toscrape.com，在 Mystery 分类中按价格从低到高排序，报告最便宜的 3 本书及价格和完整链接。'
	),
	'中文｜表单填写：登录测试': (
		'打开 https://the-internet.herokuapp.com/login，使用用户名 tomsmith 和密码 '
		'SuperSecretPassword! 登录，并报告是否登录成功。'
	),
	'中文｜多标签页：分别总结': (
		"在 Google 搜索 'best things to do in Tokyo'，在前 3 个自然结果的新标签页中打开，并分别总结每个页面推荐的内容。"
	),
	'中文｜页面验证：检查按钮和提示': (
		'打开 https://the-internet.herokuapp.com/dynamic_controls，移除 checkbox，'
		'确认它消失，再添加回来，启用输入框，输入 "hello"，并报告最终状态。'
	),
	'中文｜文件下载：下载公开文件': (
		'打开 https://the-internet.herokuapp.com/download，下载第一个可用的文本文件，并报告文件名和路径。'
	),
	'中文｜研究报告：多来源汇总': (
		'调研 browser automation agents 的最新消息，访问至少 3 个来源，比较它们的主要观点，并用中文输出简洁总结和链接。'
	),
	'English | Research: search and summarize': (
		'Search Google for "what is browser automation" and summarize the top 3 results with titles and full links.'
	),
	'English | Data extraction: scrape books': (
		'Go to https://books.toscrape.com, open the Mystery category, '
		'extract the title, price, and rating of the first 5 books, and save them to mystery_books.csv.'
	),
	'English | Price comparison: find the cheapest': (
		'Go to https://books.toscrape.com, sort the Mystery category by price low to high, '
		'and report the 3 cheapest books with their prices and links.'
	),
	'English | Form filling: login test': (
		'Go to https://the-internet.herokuapp.com/login, log in with username tomsmith '
		'and password SuperSecretPassword!, and report whether the login succeeded.'
	),
	'English | Multi-tab: summarize each result': (
		"Search Google for 'best things to do in Tokyo', open the top 3 organic results in new tabs, "
		'and summarize what each page recommends.'
	),
	'English | Page validation: controls': (
		'Go to https://the-internet.herokuapp.com/dynamic_controls. Remove the checkbox, '
		'verify that it disappears, add it back, enable the input, type "hello", and report the final state.'
	),
	'English | Download: public file': (
		'Go to https://the-internet.herokuapp.com/download, download the first available text file, '
		'and report the file name and path.'
	),
	'English | Research: multi-source summary': (
		'Research the latest news about browser automation agents. Visit at least 3 sources, '
		'compare their main claims, and produce a concise summary with links.'
	),
}

GUIDE_MARKDOWN = """
## 这个 Agent 能做什么

它会在真实浏览器里执行任务，不只是回答问题。常用能力包括：

### 搜索与导航
- 打开网址、Google 搜索、返回上一页
- 在多个标签页之间切换
- 等待页面加载、滚动页面、查找页面文字

### 页面操作
- 点击按钮、链接、菜单
- 填写输入框、发送键盘按键
- 选择下拉框选项
- 上传文件、下载公开文件
- 在页面里执行 JavaScript，处理复杂 DOM 或 Shadow DOM

### 信息提取
- 用 `extract` 让模型从页面中提取结构化信息
- 用 `find_elements` 按 CSS selector 查找元素和属性
- 提取链接、标题、价格、表格、列表等
- 把结果写入 `csv` / `md` / `txt` 文件
- 结果里包含网页链接时，App 会自动抓取目标页面的缩略图和描述，显示为结果卡片
- Agent 生成的图片、PDF、Markdown、CSV 等附件会显示在“附件与图片”区域
- PDF 会自动生成第一页预览图，方便直接查看图表

### 任务能力
- 资料检索和中文总结
- 商品/书籍比价
- 表单填写和登录测试
- 数据抓取并保存到 CSV
- 多标签页分别阅读和汇总
- 页面功能验证（按钮、提示、动态加载）
- 下载公开文件
- 针对同一个目标做多来源交叉验证

## 示例任务 / Example Tasks

可以直接复制下面的任务，或者在上方“示例任务”下拉框里选择后点“填入示例”。
You can copy these tasks or load them from the **示例任务** dropdown.

### 中文示例

#### 1. 搜索并总结
```text
打开 Google 搜索 "what is browser automation"，总结前 3 个自然结果，包含标题和完整链接。
```

#### 2. 抓取书籍信息并保存 CSV
```text
打开 https://books.toscrape.com，进入 Mystery 分类，提取前 5 本书的标题、价格和评分，保存到 mystery_books.csv。
```

#### 3. 比价
```text
打开 https://books.toscrape.com，在 Mystery 分类中按价格从低到高排序，报告最便宜的 3 本书及价格和完整链接。
```

#### 4. 表单填写和登录测试
```text
打开 https://the-internet.herokuapp.com/login，使用用户名 tomsmith 和密码 SuperSecretPassword! 登录，并报告是否登录成功。
```

#### 5. 多标签页分别总结
```text
在 Google 搜索 'best things to do in Tokyo'，在前 3 个自然结果的新标签页中打开，并分别总结每个页面推荐的内容。
```

#### 6. 页面功能验证
```text
打开 https://the-internet.herokuapp.com/dynamic_controls，移除 checkbox，确认它消失，再添加回来，启用输入框，输入 "hello"，并报告最终状态。
```

#### 7. 下载公开文件
```text
打开 https://the-internet.herokuapp.com/download，下载第一个可用的文本文件，并报告文件名和路径。
```

#### 8. 多来源研究汇总
```text
调研 browser automation agents 的最新消息，访问至少 3 个来源，比较它们的主要观点，并用中文输出简洁总结和链接。
```

### English examples

#### 1. Search and summarize
```text
Search Google for "what is browser automation" and summarize the top 3 results with titles and full links.
```

#### 2. Scrape books and save CSV
```text
Go to https://books.toscrape.com, open the Mystery category, extract the title, price,
and rating of the first 5 books, and save them to mystery_books.csv.
```

#### 3. Price comparison
```text
Go to https://books.toscrape.com, sort the Mystery category by price low to high,
and report the 3 cheapest books with their prices and links.
```

#### 4. Login test
```text
Go to https://the-internet.herokuapp.com/login, log in with username tomsmith
and password SuperSecretPassword!, and report whether the login succeeded.
```

#### 5. Multi-tab summaries
```text
Search Google for 'best things to do in Tokyo', open the top 3 organic results in new tabs,
and summarize what each page recommends.
```

#### 6. Page validation
```text
Go to https://the-internet.herokuapp.com/dynamic_controls. Remove the checkbox,
verify that it disappears, add it back, enable the input, type "hello", and report the final state.
```

#### 7. Download a public file
```text
Go to https://the-internet.herokuapp.com/download, download the first available text file,
and report the file name and path.
```

#### 8. Multi-source research
```text
Research the latest news about browser automation agents. Visit at least 3 sources,
compare their main claims, and produce a concise summary with links.
```

## 怎么写好任务 / Prompt tips

- 尽量写清楚目标网站、要做什么、最终要什么格式。
- 需要完整 URL 时明确说“使用完整 URL，不要使用页面上截断的显示链接”。
- 需要保存文件时说明文件名，例如：
  `save the results to books.csv`。
- 复杂任务可以要求分步骤：
  “先搜索，再打开前 3 个结果，最后汇总”。
- 如果结果需要验证，明确说：
  “只有提取到 3 条完整结果后才调用 done”。

## 当前限制

- 遇到 CAPTCHA、短信验证码、2FA 或支付确认时，Agent 可能无法自动完成。
- 部分网站有反自动化保护，可能拒绝访问或要求人工验证。
- 文件类任务的结果目前以文本摘要为主，附件路径会记录在日志里。
- 任务执行中显示 `processing` 是正常的，复杂任务可能需要 1-3 分钟。
- 请只执行你有权访问的网站和任务，不要用于绕过访问控制或进行违规操作。
"""


def _prepare_runtime() -> None:
	"""Create writable directories and configure bundled Chromium before imports."""
	APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
	LOG_DIR.mkdir(parents=True, exist_ok=True)
	PROFILE_DIR.mkdir(parents=True, exist_ok=True)
	ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

	if getattr(sys, 'frozen', False):
		base_dir = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
		bundled_chromium = base_dir / 'ms-playwright'
		if bundled_chromium.exists():
			os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(bundled_chromium))

		# A --windowed .app has no console. Keep browser-use logs diagnosable.
		log_file = (LOG_DIR / 'app.log').open('a', buffering=1)
		sys.stdout = log_file
		sys.stderr = log_file


_prepare_runtime()

import gradio as gr
import httpx
import keyring
from bs4 import BeautifulSoup

from browser_use import Agent, Browser, ChatDeepSeek

logger = logging.getLogger('browser_buddy')
logger.setLevel(logging.INFO)
if not logger.handlers:
	_handler = logging.FileHandler(LOG_DIR / 'app.log', encoding='utf-8')
	_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
	logger.addHandler(_handler)


def get_saved_key() -> str:
	try:
		return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or ''
	except Exception as e:
		logger.warning(f'Could not read API key from Keychain: {type(e).__name__}: {e}')
		return ''


def save_key(api_key: str) -> None:
	try:
		keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)
	except Exception as e:
		logger.warning(f'Could not save API key to Keychain: {type(e).__name__}: {e}')


def missing_browser_message() -> str | None:
	"""Warn packaged apps that have neither bundled Chromium nor a system browser."""
	if not getattr(sys, 'frozen', False):
		return None

	base_dir = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
	if (base_dir / 'ms-playwright').exists():
		return None

	candidates = (
		'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		'/Applications/Chromium.app/Contents/MacOS/Chromium',
		'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
		'/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
	)
	if any(Path(path).exists() for path in candidates):
		return None

	return '未找到可用的 Chrome/Chromium。请安装 Google Chrome，或者用 BUNDLE_CHROMIUM=1 重新打包。'


def open_logs() -> str:
	LOG_DIR.mkdir(parents=True, exist_ok=True)
	subprocess.run(['open', str(LOG_DIR)], check=False)
	return f'日志目录：{LOG_DIR}'


def fill_example(name: str | None) -> str:
	return EXAMPLE_TASKS.get(name or '', '')


def _escape(value: str) -> str:
	return html.escape(value or '', quote=True)


def _extract_urls(text: str, limit: int = 5) -> list[str]:
	urls: list[str] = []
	for raw in URL_RE.findall(text or ''):
		url = raw.rstrip(TRAILING_URL_CHARS)
		if url and url not in urls and urlparse(url).scheme in ('http', 'https'):
			urls.append(url)
		if len(urls) >= limit:
			break
	return urls


async def _fetch_page_card(client: httpx.AsyncClient, url: str) -> dict[str, str]:
	if urlparse(url).path.lower().endswith(IMAGE_SUFFIXES):
		return {
			'url': url,
			'title': urlparse(url).path.rsplit('/', 1)[-1] or url,
			'description': '',
			'image': url,
		}

	try:
		resp = await client.get(url)
		resp.raise_for_status()
		soup = BeautifulSoup(resp.text[:300_000], 'html.parser')

		title = soup.title.string.strip() if soup.title and soup.title.string else ''
		og_title = soup.find('meta', property='og:title')
		if og_title and og_title.get('content'):
			title = og_title['content'].strip()

		description = ''
		for attrs in ({'property': 'og:description'}, {'name': 'description'}):
			tag = soup.find('meta', attrs=attrs)
			if tag and tag.get('content'):
				description = tag['content'].strip()
				break

		image = ''
		for attrs in (
			{'property': 'og:image'},
			{'name': 'twitter:image'},
			{'name': 'twitter:image:src'},
		):
			tag = soup.find('meta', attrs=attrs)
			if tag and tag.get('content'):
				image = urljoin(url, tag['content'].strip())
				break

		if not image:
			icon = soup.find('link', rel=lambda value: value and 'icon' in value)
			if icon and icon.get('href'):
				image = urljoin(url, icon['href'])

		if image and urlparse(image).scheme not in ('http', 'https'):
			image = ''

		return {
			'url': url,
			'title': title or url,
			'description': description,
			'image': image,
		}
	except Exception:
		return {'url': url, 'title': url, 'description': '', 'image': ''}


def _render_page_cards(pages: list[dict[str, str]]) -> str:
	cards: list[str] = []
	for page in pages:
		image = page.get('image', '')
		if image:
			thumb = f'<img src="{_escape(image)}" loading="lazy" referrerpolicy="no-referrer" alt="">'
		else:
			thumb = '<div class="bb-thumb-placeholder">LINK</div>'

		domain = urlparse(page['url']).netloc
		cards.append(
			f'<a class="bb-card" href="{_escape(page["url"])}" '
			f'target="_blank" rel="noopener noreferrer">'
			f'<div class="bb-thumb">{thumb}</div>'
			f'<div class="bb-body">'
			f'<div class="bb-title">{_escape(page["title"])}</div>'
			f'<div class="bb-desc">{_escape(page["description"][:180])}</div>'
			f'<div class="bb-domain">{_escape(domain)}</div>'
			f'</div></a>'
		)

	if not cards:
		return ''

	return '<div class="bb-section-title">相关页面</div><div class="bb-cards">' + ''.join(cards) + '</div>'


async def build_result_cards(text: str, limit: int = 5) -> str:
	urls = _extract_urls(text, limit=limit)
	if not urls:
		return ''

	headers = {
		'User-Agent': (
			'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
		)
	}
	async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
		pages = await asyncio.gather(
			*(_fetch_page_card(client, url) for url in urls),
			return_exceptions=True,
		)

	valid_pages = [page for page in pages if isinstance(page, dict)]
	return _render_page_cards(valid_pages)


def _pdf_preview(pdf_path: Path) -> str | None:
	try:
		preview_path = pdf_path.with_suffix('.png')
		if preview_path.exists():
			return str(preview_path)

		subprocess.run(
			['sips', '-s', 'format', 'png', str(pdf_path), '--out', str(preview_path)],
			check=True,
			capture_output=True,
			timeout=20,
		)
		return str(preview_path) if preview_path.exists() else None
	except Exception as e:
		logger.warning(f'Could not render PDF preview for {pdf_path}: {type(e).__name__}: {e}')
		return None


def collect_artifacts(history) -> tuple[list[str], list[str]]:
	files: list[str] = []
	images: list[str] = []
	seen_files: set[str] = set()
	seen_images: set[str] = set()

	for item in history.history:
		for result in item.result:
			for raw_path in result.attachments or []:
				path = Path(raw_path).expanduser()
				if not path.exists():
					continue

				# Copy into app storage so downloads and previews survive temp cleanup.
				copied_path = ARTIFACT_DIR / f'{path.stem}-{path.stat().st_mtime_ns}{path.suffix}'
				if not copied_path.exists():
					try:
						shutil.copy2(path, copied_path)
					except Exception as e:
						logger.warning(f'Could not copy attachment {path}: {type(e).__name__}: {e}')
						copied_path = path

				path_str = str(copied_path)
				if path_str not in seen_files:
					files.append(path_str)
					seen_files.add(path_str)

				suffix = copied_path.suffix.lower()
				if suffix in IMAGE_SUFFIXES:
					if path_str not in seen_images:
						images.append(path_str)
						seen_images.add(path_str)
				elif suffix == '.pdf':
					preview = _pdf_preview(copied_path)
					if preview and preview not in seen_images:
						images.append(preview)
						seen_images.add(preview)

	return files, images


async def run_task(task: str, api_key: str, headless: bool, max_steps: int) -> tuple[str, str, list[str], list[str]]:
	task = (task or '').strip()
	entered_key = (api_key or '').strip()
	resolved_key = entered_key or get_saved_key()

	if not task:
		return '请先输入要执行的任务。', '', [], []
	if not resolved_key:
		return '请先填写 DeepSeek API Key。', '', [], []
	missing_browser = missing_browser_message()
	if missing_browser:
		return missing_browser, '', [], []
	if entered_key:
		save_key(entered_key)

	logger.info(f'Starting task: {task[:200]}')

	try:
		llm = ChatDeepSeek(
			model=DEFAULT_MODEL,
			api_key=resolved_key,
			base_url=DEFAULT_BASE_URL,
		)
		browser = Browser(
			headless=headless,
			user_data_dir=str(PROFILE_DIR),
		)
		agent = Agent(
			task=task,
			llm=llm,
			browser=browser,
			use_vision=True,
			auto_recovery=True,
			use_judge=False,
		)
		history = await agent.run(max_steps=int(max_steps))
		result = history.final_result() or '任务完成，但模型没有返回文本结果。'

		card_source = result
		if not _extract_urls(card_source):
			visited_urls = history.urls() or []
			card_source = '\n'.join(visited_urls[-5:])

		cards = await build_result_cards(card_source)
		files, images = collect_artifacts(history)
		return result, cards, files, images
	except Exception as e:
		logger.exception('Task failed')
		return f'运行失败：{type(e).__name__}: {e}\n\n详细日志：{LOG_DIR / "app.log"}', '', [], []


def build_ui() -> gr.Blocks:
	with gr.Blocks(title=APP_NAME) as demo:
		gr.Markdown(
			f'# {APP_NAME}\n'
			'输入一个任务，让浏览器替你完成。首次运行填写 DeepSeek API Key；'
			'之后会保存到 macOS Keychain，留空即可复用。',
			elem_classes='hero',
		)

		with gr.Tabs():
			with gr.Tab('执行任务'):
				with gr.Row():
					with gr.Column(scale=2):
						api_key = gr.Textbox(
							label='DeepSeek API Key',
							type='password',
							placeholder='sk-...（已保存时可留空）',
						)
						with gr.Row():
							example_select = gr.Dropdown(
								choices=list(EXAMPLE_TASKS.keys()),
								label='示例任务',
								value=None,
								scale=3,
							)
							load_example_btn = gr.Button('填入示例', scale=1)
						task = gr.Textbox(
							label='任务',
							lines=6,
							max_lines=12,
							placeholder='例如：打开 Google 搜索 browser automation，并总结前 3 个结果',
						)
						with gr.Row():
							headless = gr.Checkbox(label='后台运行浏览器', value=False)
							max_steps = gr.Slider(
								minimum=10,
								maximum=100,
								value=50,
								step=5,
								label='最大步数',
							)
						with gr.Row():
							run_btn = gr.Button('开始执行', variant='primary', scale=2)
							clear_btn = gr.Button('清空任务', scale=1)
							logs_btn = gr.Button('打开日志目录', scale=1)
						gr.Markdown(
							'复杂任务可能需要 1-3 分钟。执行期间显示 `processing` 是正常的，可以打开日志目录查看实时进度。'
						)

					with gr.Column(scale=3):
						output = gr.Textbox(
							label='执行结果',
							lines=26,
							max_lines=40,
							buttons=['copy'],
							interactive=False,
						)
						result_cards = gr.HTML()
						with gr.Accordion('附件与图片', open=True):
							attachments = gr.Files(label='附件下载')
							gallery = gr.Gallery(
								label='图片 / PDF 预览',
								columns=2,
								height='auto',
								object_fit='contain',
							)

			with gr.Tab('功能与示例'):
				gr.Markdown(GUIDE_MARKDOWN, elem_classes='prose')

		load_example_btn.click(fn=fill_example, inputs=example_select, outputs=task)
		clear_btn.click(fn=lambda: '', outputs=task)
		run_btn.click(
			fn=run_task,
			inputs=[task, api_key, headless, max_steps],
			outputs=[output, result_cards, attachments, gallery],
		)
		logs_btn.click(fn=open_logs)

	return demo


if __name__ == '__main__':
	theme = gr.themes.Soft(
		primary_hue='blue',
		secondary_hue='slate',
		neutral_hue='slate',
		text_size=gr.themes.sizes.text_lg,
	)
	demo = build_ui()
	demo.queue()
	demo.launch(
		inbrowser=True,
		server_name='127.0.0.1',
		server_port=7860,
		show_error=True,
		theme=theme,
		css=CUSTOM_CSS,
	)
