"""Collect structured arXiv search results with Browser Use.

This example is intended as an optional browser fallback after official
metadata APIs have been tried. It keeps the browser restricted to arXiv and
returns a structured Pydantic result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from urllib.parse import urlencode

from dotenv import load_dotenv
from pydantic import BaseModel, Field

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from browser_use import Agent, BrowserProfile, ChatBrowserUse, Tools


class ArxivPaper(BaseModel):
	title: str
	authors: list[str] = Field(default_factory=list)
	arxiv_id: str = ''
	abstract: str = ''
	url: str = ''
	pdf_url: str = ''
	submitted: str = ''
	subjects: list[str] = Field(default_factory=list)
	notes: str = ''


class ArxivSearchResult(BaseModel):
	query: str
	source_url: str
	papers: list[ArxivPaper] = Field(default_factory=list)
	blocked: bool = False
	notes: str = ''


def build_arxiv_search_url(query: str, limit: int) -> str:
	size = min((25, 50, 100, 200), key=lambda value: abs(value - limit))
	params = {
		'query': query,
		'searchtype': 'all',
		'abstracts': 'show',
		'order': '-announced_date_first',
		'size': str(size),
	}
	return f'https://arxiv.org/search/?{urlencode(params)}'


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('query', help='arXiv search query.')
	parser.add_argument('--limit', type=int, default=10, help='Number of papers to extract.')
	parser.add_argument('--headed', action='store_true', help='Show the browser window.')
	parser.add_argument('--max-steps', type=int, default=12)
	return parser.parse_args()


async def main() -> None:
	load_dotenv()
	args = parse_args()
	limit = max(1, min(args.limit, 50))
	source_url = build_arxiv_search_url(args.query, limit)

	task = f"""
Open this arXiv search URL and extract up to {limit} papers as JSON.

URL: {source_url}

Return exactly this schema: query, source_url, papers, blocked, notes.
For each paper return title, authors, arxiv_id, abstract, url, pdf_url,
submitted, subjects, and notes.

Rules:
- Stay on arxiv.org.
- Prefer DOM text over screenshots.
- Do not solve CAPTCHAs, bypass bot protection, or use login-only data.
- If blocked, set blocked=true and explain the blocker in notes.
""".strip()

	tools = Tools(output_model=ArxivSearchResult)
	browser_profile = BrowserProfile(
		allowed_domains=['*.arxiv.org', 'arxiv.org'],
		enable_default_extensions=False,
		headless=not args.headed,
	)
	agent = Agent(task=task, llm=ChatBrowserUse(), tools=tools, browser_profile=browser_profile)

	history = await agent.run(max_steps=args.max_steps)
	raw_result = history.final_result()
	if not raw_result:
		raise SystemExit('No structured result returned.')

	result = ArxivSearchResult.model_validate_json(raw_result)
	print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
	asyncio.run(main())
