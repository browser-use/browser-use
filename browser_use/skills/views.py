"""Skills views - wraps SDK types with helper methods"""

from typing import Any

from browser_use_sdk.types import (
	app_api_v2skills_views_parameter_schema as parameter_schema_module,
)
from browser_use_sdk.types import (
	app_api_v2skills_views_parameter_type as parameter_type_module,
)
from browser_use_sdk.types import (
	execute_skill_response,
	skill_response,
	skills_generation_status,
)
from pydantic import BaseModel, ConfigDict, Field

# Re-export SDK types for convenience
SkillsGenerationStatus = skills_generation_status.SkillsGenerationStatus
ParameterType = parameter_type_module.AppApiV2SkillsViewsParameterType
ParameterSchema = parameter_schema_module.AppApiV2SkillsViewsParameterSchema
SkillResponse = skill_response.SkillResponse
ExecuteSkillResponse = execute_skill_response.ExecuteSkillResponse


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

	@property
	def parameters_pydantic(self) -> type[BaseModel]:
		"""Convert parameter schemas to a pydantic model for structured output"""
		from browser_use.skills.utils import convert_parameters_to_pydantic

		return convert_parameters_to_pydantic(self.parameters, model_name=f'{self.title}Parameters')

	@property
	def output_type_pydantic(self) -> type[BaseModel] | None:
		"""Convert output schema to a pydantic model for structured output"""
		if not self.output_schema:
			return None

		from browser_use.skills.utils import convert_json_schema_to_pydantic

		return convert_json_schema_to_pydantic(self.output_schema, model_name=f'{self.title}Output')
