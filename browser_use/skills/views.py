"""Skills views - wraps SDK types with helper methods"""

from typing import Any

from browser_use_sdk.types.parameter_schema import ParameterSchema
from browser_use_sdk.types.skill_response import SkillResponse
from pydantic import BaseModel, ConfigDict, Field


class MissingCookieException(Exception):
	"""Raised when a required cookie is missing for skill execution

	Attributes:
		cookie_name: The name of the missing cookie parameter
		cookie_description: Description of how to obtain the cookie
	"""

	def __init__(self, cookie_name: str, cookie_description: str):
		self.cookie_name = cookie_name
		self.cookie_description = cookie_description
		super().__init__(f"Missing required cookie '{cookie_name}': {cookie_description}")


class Skill(BaseModel):
	"""Skill model with helper methods for LLM integration

	This wraps the SDK SkillResponse with additional helper properties
	for converting schemas to Pydantic models.
	"""

	model_config = ConfigDict(extra='forbid', validate_assignment=True)

	id: str
	title: str
	description: str
	parameters: list[ParameterSchema]
	output_schema: dict[str, Any] = Field(default_factory=dict)

	@staticmethod
	def from_skill_response(response: SkillResponse) -> 'Skill':
		"""Create a Skill from SDK SkillResponse"""
		return Skill(
			id=response.id,
			title=response.title,
			description=response.description,
			parameters=response.parameters,
			output_schema=response.output_schema,
		)

	def parameters_pydantic(self, exclude_cookies: bool = False) -> type[BaseModel]:
		"""Convert parameter schemas to a pydantic model for structured output

		exclude_cookies is very useful when dealing with LLMs that are not aware of cookies.
		"""
		from browser_use.skills.utils import convert_parameters_to_pydantic

		parameters = list[ParameterSchema](self.parameters)

		if exclude_cookies:
			parameters = [param for param in parameters if param.type != 'cookie']

		return convert_parameters_to_pydantic(parameters, model_name=f'{self.title}Parameters')

	@property
	def output_type_pydantic(self) -> type[BaseModel] | None:
		"""Convert output schema to a pydantic model for structured output"""
		if not self.output_schema:
			return None

		from browser_use.skills.utils import convert_json_schema_to_pydantic

		return convert_json_schema_to_pydantic(self.output_schema, model_name=f'{self.title}Output')
