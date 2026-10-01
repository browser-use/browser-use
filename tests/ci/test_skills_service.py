"""Tests for SkillService against a local stand-in for the Browser Use skills API."""

import json
from typing import Any

import pytest
from browser_use_sdk import AsyncBrowserUse
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from browser_use.skills.service import SkillService
from browser_use.skills.views import MissingCookieException

FINISHED_SKILL_ID = '11111111-1111-1111-1111-111111111111'
FAILED_SKILL_ID = '22222222-2222-2222-2222-222222222222'


def _skill_json(skill_id: str, status: str, parameters: list[dict[str, Any]]) -> dict[str, Any]:
	return {
		'id': skill_id,
		'title': f'Shop orders {status}',
		'description': 'List my orders on shop.test',
		'categories': [],
		'domains': ['shop.test'],
		'status': status,
		'parameters': parameters,
		'outputSchema': {},
		'isEnabled': True,
		'isPublic': False,
		'currentVersion': 1,
		'createdAt': '2026-01-01T00:00:00Z',
		'updatedAt': '2026-01-01T00:00:00Z',
	}


PARAMETERS = [
	{'name': 'query', 'type': 'string', 'required': True},
	{'name': 'limit', 'type': 'number', 'required': True},
	{'name': 'include_cancelled', 'type': 'boolean', 'required': False},
	{'name': 'tags', 'type': 'array', 'required': False},
	{'name': 'filters', 'type': 'object', 'required': False},
	{'name': 'session', 'type': 'cookie', 'required': True, 'cookieDomain': 'shop.test'},
	{'name': 'locale', 'type': 'cookie', 'required': False},
]


@pytest.fixture
def executed_bodies() -> list[dict[str, Any]]:
	return []


@pytest.fixture
async def skill_service(httpserver: HTTPServer, executed_bodies: list[dict[str, Any]]):
	skills = [
		_skill_json(FINISHED_SKILL_ID, 'finished', PARAMETERS),
		_skill_json(FAILED_SKILL_ID, 'failed', []),
	]
	httpserver.expect_request('/skills', method='GET').respond_with_json(
		{'items': skills, 'totalItems': len(skills), 'pageNumber': 1, 'pageSize': 100}
	)

	def execute(request: Request) -> Response:
		executed_bodies.append(request.get_json())
		return Response(json.dumps({'success': True, 'result': 'ok'}), content_type='application/json')

	httpserver.expect_request(f'/skills/{FINISHED_SKILL_ID}/execute', method='POST').respond_with_handler(execute)

	service = SkillService(skill_ids=['*'], api_key='test-key')
	service._client = AsyncBrowserUse(api_key='test-key', base_url=httpserver.url_for('').rstrip('/'), max_retries=0)
	yield service
	await service.close()


def _cookie(domain: str, value: str, name: str = 'session') -> Any:
	return {'name': name, 'value': value, 'domain': domain, 'path': '/'}


async def test_only_finished_skills_are_loaded(skill_service: SkillService):
	skills = await skill_service.get_all_skills()
	assert [skill.id for skill in skills] == [FINISHED_SKILL_ID]


async def test_parameter_types_are_kept_and_cookies_hidden_from_llm(skill_service: SkillService):
	skill = await skill_service.get_skill(FINISHED_SKILL_ID)
	assert skill is not None

	properties = skill.parameters_pydantic(exclude_cookies=True).model_json_schema()['properties']
	assert 'session' not in properties
	assert properties['query']['type'] == 'string'
	assert properties['limit']['type'] == 'number'
	# optional params are rendered as anyOf[<type>, null]
	assert {'type': 'boolean'} in properties['include_cancelled']['anyOf']
	assert properties['tags']['anyOf'][0]['type'] == 'array'
	assert properties['filters']['anyOf'][0]['type'] == 'object'


async def test_cookie_param_is_filled_from_matching_domain(skill_service: SkillService, executed_bodies: list[dict[str, Any]]):
	cookies = [_cookie('.shop.test', 'shop-session'), _cookie('bank.test', 'bank-session')]

	result = await skill_service.execute_skill(FINISHED_SKILL_ID, {'query': 'shoes', 'limit': 5}, cookies)

	assert result.success is True
	assert len(executed_bodies) == 1
	sent = executed_bodies[0]['parameters']
	assert sent['session'] == 'shop-session'
	assert sent['limit'] == 5
	assert sent['query'] == 'shoes'


async def test_cookie_from_other_domain_is_not_used(skill_service: SkillService, executed_bodies: list[dict[str, Any]]):
	with pytest.raises(MissingCookieException):
		await skill_service.execute_skill(
			FINISHED_SKILL_ID, {'query': 'shoes', 'limit': 5}, [_cookie('bank.test', 'bank-session')]
		)
	assert executed_bodies == []


async def test_cookie_param_without_domain_uses_last_matching_cookie(
	skill_service: SkillService, executed_bodies: list[dict[str, Any]]
):
	cookies = [
		_cookie('shop.test', 'shop-session'),
		_cookie('a.test', 'en', name='locale'),
		_cookie('b.test', 'fr', name='locale'),
	]

	await skill_service.execute_skill(FINISHED_SKILL_ID, {'query': 'shoes', 'limit': 5}, cookies)

	assert executed_bodies[0]['parameters']['locale'] == 'fr'
