"""Desearch web search actions for Browser Use."""

import os

import httpx
from pydantic import BaseModel, Field

from browser_use import ActionResult, Tools


class DesearchSearchParams(BaseModel):
	query: str = Field(min_length=1, pattern=r'\S', description='Web search query')
	limit: int = Field(default=5, ge=1, le=5, description='Maximum number of results to return')


class DesearchSearchResult(BaseModel):
	title: str
	link: str
	snippet: str = ''


class DesearchSearchResponse(BaseModel):
	data: list[DesearchSearchResult]


def register_desearch_actions(tools: Tools) -> None:
	"""Register web search using the DESEARCH_API_KEY environment variable."""
	api_key = os.environ.get('DESEARCH_API_KEY')
	if not api_key:
		raise ValueError('DESEARCH_API_KEY is not set')

	@tools.action('Search the web with Desearch. Returns titles, links, and snippets.', param_model=DesearchSearchParams)
	async def desearch_search(params: DesearchSearchParams) -> ActionResult:
		"""Retrieve a bounded list of web results without opening a browser."""
		try:
			async with httpx.AsyncClient(timeout=30.0) as client:
				response = await client.get(
					'https://api.desearch.ai/web',
					params={'query': params.query, 'num': params.limit},
					headers={'Authorization': f'Bearer {api_key}'},
				)
				response.raise_for_status()
			results = DesearchSearchResponse.model_validate(response.json())
			results.data = results.data[: params.limit]
			return ActionResult(extracted_content=results.model_dump_json())
		except httpx.HTTPStatusError as exc:
			return ActionResult(error=f'Desearch search failed with HTTP {exc.response.status_code}.')
		except httpx.RequestError:
			return ActionResult(error='Desearch search request failed.')
		except ValueError:
			return ActionResult(error='Desearch returned an invalid search response.')
