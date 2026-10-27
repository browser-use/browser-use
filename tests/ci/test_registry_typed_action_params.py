"""Regression test: custom actions declared with typed parameters receive validated objects.

The normalized action wrapper turned the validated param model back into plain dicts with
`model_dump()` before calling the user's function, so an action annotated with a pydantic
model (or a list of them) received `dict`s and attribute access like `address.city` failed.
"""

from enum import Enum

from pydantic import BaseModel

from browser_use.agent.views import ActionResult
from browser_use.tools.registry.service import Registry


class Address(BaseModel):
	city: str
	zip_code: str | None = None


class Priority(str, Enum):
	LOW = 'low'
	HIGH = 'high'


async def test_action_receives_pydantic_model_parameters():
	registry = Registry()

	@registry.action('Save a delivery route')
	async def save_route(origin: Address, stops: list[Address], priority: Priority):
		assert isinstance(origin, Address)
		assert all(isinstance(stop, Address) for stop in stops)
		assert isinstance(priority, Priority)
		route = ' -> '.join([origin.city, *(stop.city for stop in stops)])
		return ActionResult(extracted_content=f'{route} ({priority.value})')

	result = await registry.execute_action(
		'save_route',
		{'origin': {'city': 'Paris'}, 'stops': [{'city': 'Lyon', 'zip_code': '69001'}, {'city': 'Nice'}], 'priority': 'high'},
	)

	assert result.extracted_content == 'Paris -> Lyon -> Nice (high)'


async def test_action_receives_pydantic_model_parameters_with_sensitive_data():
	registry = Registry()

	@registry.action('Ship to an address')
	async def ship_to(address: Address):
		return ActionResult(extracted_content=f'{type(address).__name__}: {address.city}')

	result = await registry.execute_action(
		'ship_to',
		{'address': {'city': '<secret>home_city</secret>'}},
		sensitive_data={'home_city': 'Berlin'},
	)

	assert result.extracted_content == 'Address: Berlin'
