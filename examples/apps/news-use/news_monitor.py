#!/usr/bin/env python3
"""
News monitoring agent with browser-use + Gemini Flash.
Automatically extracts and analyzes the latest articles from any news website.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Literal

from dateutil import parser as dtparser
from pydantic import BaseModel


def setup_environment(debug: bool):
	if not debug:
		os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'
		os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'critical'
		logging.getLogger().setLevel(logging.CRITICAL)
	else:
		os.environ['BROWSER_USE_SETUP_LOGGING'] = 'true'
		os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'info'


parser = argparse.ArgumentParser(description='News extractor using Browser-Use + Gemini')
parser.add_argument('--url', default='https://www.techcrunch.com', help='News site root URL')
parser.add_argument('--interval', type=int, default=300, help='Seconds between checks in monitor mode')
parser.add_argument('--once', action='store_true', help='Run a single extraction and exit')
parser.add_argument('--output', default='news_data.json', help='Path to JSON file where articles are stored')
parser.add_argument('--debug', action='store_true', help='Verbose console output and non-headless browser')
args = parser.parse_args()

setup_environment(args.debug)

from browser_use import Agent, BrowserSession, ChatGoogle

GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY') or 'xxxx'

if GEMINI_API_KEY == 'xxxx':
	print('⚠️  WARNING: Please set GOOGLE_API_KEY environment variable')
	print('   You can get an API key at: https://makersuite.google.com/app/apikey')
	print("   Then run: export GEMINI_API_KEY='your-api-key-here'")
	print()


class NewsArticle(BaseModel):
	title: str
	url: str
	posting_time: str
	short_summary: str
	long_summary: str
	sentiment: Literal['positive', 'neutral', 'negative']


# ---------------------------------------------------------
# Core extractor
# ---------------------------------------------------------


async def extract_latest_article(site_url: str, debug: bool = False) -> dict:
	"""Open site_url, navigate to the newest article and return structured JSON."""

	prompt = (
		f'Navigate to {site_url} and find the most recent headline article (usually at the top). '
		f'Click on it to open the full article page. Once loaded, scroll & extract ALL required information: '
		f'1. title: The article headline '
		f'2. url: The full URL of the article page '
		f'3. posting_time: The publication date/time as shown on the page '
		f"4. short_summary: A 10-word overview of the article's content "
		f'5. long_summary: A 100-word detailed summary of the article '
		f"6. sentiment: Classify as 'positive', 'neutral', or 'negative' based on the article tone. "
		f'When done, call the done action with success=True and put ALL extracted data in the text field '
		f'as valid JSON in this exact format: '
		f'{{"title": "...", "url": "...", "posting_time": "...", "short_summary": "...", "long_summary": "...", "sentiment": "positive|neutral|negative"}}'
	)

	llm = ChatGoogle(model='gemini-2.0-flash', temperature=0.1, api_key=GEMINI_API_KEY)
	browser_session = BrowserSession(headless=not debug)

	agent = Agent(task=prompt, llm=llm, browser_session=browser_session, use_vision=False)

	if debug:
		print(f'[DEBUG] Starting extraction from {site_url}')
		start = time.time()

	result = await agent.run(max_steps=25)

	raw = result.final_result() if result else None
	if debug:
		print(f'[DEBUG] Raw result type: {type(raw)}')
		print(f'[DEBUG] Raw result: {raw[:500] if isinstance(raw, str) else raw}')
		print(f'[DEBUG] Extraction time: {time.time() - start:.2f}s')

	if isinstance(raw, dict):
		return {'status': 'success', 'data': raw}

	text = str(raw).strip() if raw else ''

	if '<json>' in text and '</json>' in text:
		text = text.split('<json>', 1)[1].split('</json>', 1)[0].strip()

	if text.lower().startswith('here is'):
		brace = text.find('{')
		if brace != -1:
			text = text[brace:]

	if text.startswith('```'):
		text = text.lstrip('`\n ')
		if text.lower().startswith('json'):
			text = text[4:].lstrip()

	def _escape_newlines(src: str) -> str:
		out, in_str, esc = [], False, False
		for ch in src:
			if in_str:
				if esc:
					esc = False
				elif ch == '\\':
					esc = True
				elif ch == '"':
					in_str = False
				elif ch == '\n':
					out.append('\\n')
					continue
				elif ch == '\r':
					continue
			else:
				if ch == '"':
					in_str = True
			out.append(ch)
		return ''.join(out)

	cleaned = _escape_newlines(text)

	def _try_parse(txt: str):
		try:
			return json.loads(txt)
		except Exception:
			return None

	data = _try_parse(cleaned)

	# Fallback: grab first balanced JSON object
	if data is None:
		brace = 0
		start = None
		for i, ch in enumerate(text):
			if ch == '{':
				if brace == 0:
					start = i
				brace += 1
			elif ch == '}':
				brace -= 1
				if brace == 0 and start is not None:
					candidate = _escape_newlines(text[start : i + 1])
					data = _try_parse(candidate)
					if data is not None:
						break

	if isinstance(data, dict):
		return {'status': 'success', 'data': data}
	return {'status': 'error', 'error': f'JSON parse failed. Raw head: {text[:200]}'}


# ---------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------


def load_seen_hashes(file_path: str = 'news_data.json') -> set:
	"""Load already-saved article URL hashes from disk for dedup across restarts."""
	if not os.path.exists(file_path):
		return set()
	try:
		with open(file_path) as f:
			items = json.load(f)
		return {entry['hash'] for entry in items if 'hash' in entry}
	except Exception:
		return set()


def save_article(article: dict, file_path: str = 'news_data.json'):
	"""Append article to disk with a hash for future dedup."""
	payload = {
		'hash': hashlib.md5(article['url'].encode()).hexdigest(),
		'pulled_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
		'data': article,
	}

	existing = []
	if os.path.exists(file_path):
		try:
			with open(file_path) as f:
				existing = json.load(f)
		except Exception:
			existing = []

	existing.append(payload)
	# Keep last 100
	existing = existing[-100:]

	with open(file_path, 'w') as f:
		json.dump(existing, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------
# CLI functions
# ---------------------------------------------------------


def _fmt(ts_raw: str) -> str:
	"""Format timestamp string"""
	try:
		return dtparser.parse(ts_raw).strftime('%Y-%m-%d %H:%M:%S')
	except Exception:
		return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


async def run_once(url: str, output_path: str, debug: bool):
	"""Run a single extraction and exit"""
	res = await extract_latest_article(url, debug)

	if res['status'] == 'success':
		art = res['data']
		url_val = art.get('url', '')
		hash_ = hashlib.md5(url_val.encode()).hexdigest() if url_val else None
		if url_val:
			save_article(art, output_path)
		ts = _fmt(art.get('posting_time', ''))
		sentiment = art.get('sentiment', 'neutral')
		emoji = {'positive': '🟢', 'negative': '🔴', 'neutral': '🟡'}.get(sentiment, '🟡')
		summary = art.get('short_summary', art.get('summary', art.get('title', '')))
		if debug:
			print(json.dumps(art, ensure_ascii=False, indent=2))
			print()
		print(f'[{ts}] - {emoji} - {summary}')
		if not debug:
			print()  # Only add spacing in non-debug mode
		return hash_
	else:
		print(f'Error: {res["error"]}')
		return None


async def monitor(url: str, interval: int, output_path: str, debug: bool):
	"""Continuous monitoring mode"""
	seen = load_seen_hashes(output_path)
	print(f'Monitoring {url} every {interval}s')
	print()

	while True:
		try:
			res = await extract_latest_article(url, debug)

			if res['status'] == 'success':
				art = res['data']
				url_val = art.get('url', '')
				hash_ = hashlib.md5(url_val.encode()).hexdigest() if url_val else None
				if hash_ and hash_ not in seen:
					seen.add(hash_)
					ts = _fmt(art.get('posting_time', ''))
					sentiment = art.get('sentiment', 'neutral')
					emoji = {'positive': '🟢', 'negative': '🔴', 'neutral': '🟡'}.get(sentiment, '🟡')
					summary = art.get('short_summary', art.get('title', ''))
					save_article(art, output_path)
					if debug:
						print(json.dumps(art, ensure_ascii=False, indent=2))
					print(f'[{ts}] - {emoji} - {summary}')
					if not debug:
						print()  # Add spacing between articles in non-debug mode
			elif debug:
				print(f'Error: {res["error"]}')

		except Exception as e:
			if debug:
				import traceback

				traceback.print_exc()
			else:
				print(f'Unhandled error: {e}')

		await asyncio.sleep(interval)


def main():
	"""Main entry point"""
	if args.once:
		asyncio.run(run_once(args.url, args.output, args.debug))
	else:
		try:
			asyncio.run(monitor(args.url, args.interval, args.output, args.debug))
		except KeyboardInterrupt:
			print('\nStopped by user')


if __name__ == '__main__':
	main()
