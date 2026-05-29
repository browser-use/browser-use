"""Run a browser-use Agent on a task passed from the command line.

Usage:
	python run_agent.py "find the number of stars of the browser-use repo"
	python run_agent.py find the number of stars of the browser-use repo
	python run_agent.py                      # prompts you to type a task
	python run_agent.py --headless "..."     # run without a visible window
	python run_agent.py --model claude-sonnet-4-6 "..."
	python run_agent.py --pause-on-captcha "..."   # headed: pause on CAPTCHA so you can solve it, then resume

The LLM is chosen from --model:
	bu-* / browser-use/*   -> ChatBrowserUse  (needs BROWSER_USE_API_KEY)
	claude-*               -> ChatAnthropic   (needs ANTHROPIC_API_KEY)
	gpt-* / o1/o3/o4-*     -> ChatOpenAI       (needs OPENAI_API_KEY)
	gemini-*               -> ChatGoogle       (needs GOOGLE_API_KEY)
	qwen-*                 -> ChatDashScope    (needs DASHSCOPE_API_KEY)
"""

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Browser
from browser_use.llm.base import BaseChatModel


def build_llm(model: str) -> BaseChatModel:
	"""Pick the right chat client based on the model name prefix."""
	m = model.lower()
	if model.startswith('bu-') or model.startswith('browser-use/'):
		from browser_use import ChatBrowserUse

		return ChatBrowserUse(model=model)
	if m.startswith('claude'):
		from browser_use import ChatAnthropic

		return ChatAnthropic(model=model)
	if m.startswith(('gpt', 'o1', 'o3', 'o4', 'chatgpt')):
		from browser_use import ChatOpenAI

		return ChatOpenAI(model=model)
	if m.startswith('gemini'):
		from browser_use import ChatGoogle

		return ChatGoogle(model=model)
	if m.startswith('qwen'):
		from browser_use import ChatDashScope

		return ChatDashScope(model=model)
	raise SystemExit(
		f"Don't know which provider to use for model '{model}'. Use a bu-*, claude-*, gpt-*, gemini-*, or qwen-* model name."
	)


# JS that returns a marker string when the current page looks like a CAPTCHA / bot wall, else null.
# The size check skips the tiny invisible reCAPTCHA v3 badge so normal pages don't trip it.
_CAPTCHA_JS = r"""
(() => {
  try {
    if (location.href.includes('/sorry/')) return 'google-sorry-page';
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      return r.width > 50 && r.height > 50 && getComputedStyle(el).visibility !== 'hidden';
    };
    for (const f of document.querySelectorAll('iframe')) {
      const s = ((f.src || '') + ' ' + (f.title || '')).toLowerCase();
      if ((s.includes('recaptcha') || s.includes('hcaptcha')) && visible(f)) return 'captcha-iframe';
    }
    if (visible(document.querySelector('.g-recaptcha, .h-captcha'))) return 'captcha-widget';
    const t = ((document.body && document.body.innerText) || '').toLowerCase();
    if (t.includes('unusual traffic') || t.includes("i'm not a robot") ||
        t.includes('verify you are human') || t.includes('are you a robot')) return 'captcha-text';
    return null;
  } catch (e) { return null; }
})()
"""


async def _detect_captcha(agent) -> str | None:
	"""Return a marker string if the current page looks like a CAPTCHA/bot wall, else None."""
	try:
		cdp = await agent.browser_session.get_or_create_cdp_session()
		res = await cdp.cdp_client.send.Runtime.evaluate(
			params={'expression': _CAPTCHA_JS, 'returnByValue': True},
			session_id=cdp.session_id,
		)
		return res.get('result', {}).get('value')
	except Exception:
		return None


def make_captcha_hook():
	"""Build an on_step_end hook that pauses for the user on a CAPTCHA, injects their hint, then resumes."""

	async def on_step_end(agent) -> None:
		marker = await _detect_captcha(agent)
		if not marker:
			return
		print('\n' + '!' * 64)
		print(f'🛑 CAPTCHA detected ({marker}). Agent paused.')
		if not sys.stdin.isatty():
			# No human at a terminal to solve it (e.g. launched non-interactively); don't block.
			print('   (no interactive terminal available — cannot wait for a human; continuing)')
			print('!' * 64)
			return
		print('   Solve it in the browser window, then come back here.')
		try:
			hint = (await asyncio.to_thread(input, '   Press Enter to resume (or type a hint first): ')).strip()
		except (EOFError, KeyboardInterrupt):
			hint = ''
		# Use the message manager directly: agent.add_new_task() recreates the event bus,
		# which is unsafe mid-run. This just appends a follow-up user message for the next step.
		agent._message_manager.add_new_task(hint or 'I have solved the CAPTCHA manually. Continue with the original task.')
		print('   ▶️  Resuming...\n' + '!' * 64)

	return on_step_end


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description='Run a browser-use Agent on a task.')
	parser.add_argument('task', nargs='*', help='The task for the agent (omit to be prompted).')
	parser.add_argument('--model', default='bu-latest', help='LLM model name (default: bu-latest).')
	parser.add_argument('--max-steps', type=int, default=100, help='Max agent steps (default: 100).')
	parser.add_argument('--start-url', default=None, help='Navigate here before the agent starts (e.g. https://www.google.com).')
	parser.add_argument('--headless', action='store_true', help='Run the browser without a visible window.')
	parser.add_argument('--no-vision', action='store_true', help='Disable screenshots/vision for the LLM.')
	parser.add_argument(
		'--pause-on-captcha',
		action='store_true',
		help='When a CAPTCHA is detected, pause so you can solve it in the browser, then resume (use headed).',
	)
	return parser.parse_args()


async def main() -> int:
	args = parse_args()

	task = ' '.join(args.task).strip() or input('Task: ').strip()
	if not task:
		print('No task given, nothing to do.', file=sys.stderr)
		return 2

	initial_actions = [{'navigate': {'url': args.start_url, 'new_tab': False}}] if args.start_url else None

	agent = Agent(
		task=task,
		llm=build_llm(args.model),
		browser=Browser(headless=args.headless),
		use_vision=not args.no_vision,
		initial_actions=initial_actions,
	)

	if args.pause_on_captcha and args.headless:
		print('Note: --pause-on-captcha needs a headed browser so you can see and solve the CAPTCHA.', file=sys.stderr)

	history = await agent.run(
		max_steps=args.max_steps,
		on_step_end=make_captcha_hook() if args.pause_on_captcha else None,
	)

	print('\n' + '=' * 60)
	print(f'done: {history.is_done()}   successful: {history.is_successful()}')
	result = history.final_result()
	if result:
		print('-' * 60)
		print(result)
	print('=' * 60)
	return 0 if history.is_successful() is not False else 1


if __name__ == '__main__':
	raise SystemExit(asyncio.run(main()))
