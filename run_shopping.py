"""
电商购物助手 — 针对京东/淘宝等需要登录的电商站点优化。

特点：
- headful 模式（有头），大幅降低反爬/captcha 触发率
- 真实 User-Agent，规避自动化检测
- 手机验证码登录 + wait_for_user_input 等待人工输入
- 多模态视觉 + 坐标点击

用法：
    uv run python run_shopping.py "帮我推荐一款1000元以下的耳机"
"""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, BrowserProfile

# 真实 macOS Chrome UA，降低反爬识别
REALISTIC_UA = (
	'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
	'AppleWebKit/537.36 (KHTML, like Gecko) '
	'Chrome/131.0.0.0 Safari/537.36'
)


def build_shopping_profile(headless: bool = False) -> BrowserProfile:
	"""构建反爬友好的浏览器配置。

	headless=False（默认）：有头模式，京东/淘宝反爬触发率最低。
	"""
	return BrowserProfile(
		headless=headless,
		enable_default_extensions=False,  # 禁用扩展，避免阻塞
		user_agent=REALISTIC_UA,
		# 给慢站更宽松的视口
		viewport={'width': 1440, 'height': 900},
	)


async def run_shopping_task(task: str, headless: bool = False, max_steps: int = 25) -> str:
	profile = build_shopping_profile(headless=headless)
	agent = Agent(
		task=task,
		accounts_file='./accounts.json',
		browser_profile=profile,
		max_actions_per_step=2,  # 降低单步动作数，减少格式错误
	)
	result = await agent.run(max_steps=max_steps)
	return result.final_result()


async def main():
	task = (
		sys.argv[1]
		if len(sys.argv) > 1
		else (
			'请在京东(jd.com)上帮我推荐一款1000元以下的耳机。'
			'如果需要登录，请使用手机验证码登录方式（手机号见账户配置），'
			'点击发送验证码后用 wait_for_user_input 等待我手动输入验证码。'
			'登录成功后搜索耳机，对比几款热门商品，推荐性价比最高的一款。'
		)
	)
	print(f'🛒 任务: {task}\n')
	result = await run_shopping_task(task)
	print('\n\n===== 推荐结果 =====')
	print(result)


if __name__ == '__main__':
	asyncio.run(main())
