"""
Pydantic 模型定义

用于简历优化模块的数据验证和序列化。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, EmailStr


class Education(BaseModel):
	"""教育经历"""
	model_config = ConfigDict(extra='forbid')

	institution: str
	degree: str
	field: str | None = None
	gpa: str | None = None
	start_date: str | None = None
	end_date: str | None = None


class Experience(BaseModel):
	"""工作经历"""
	model_config = ConfigDict(extra='forbid')

	company: str
	position: str
	duration: str | None = None
	description: str
	location: str | None = None


class Project(BaseModel):
	"""项目经历"""
	model_config = ConfigDict(extra='forbid')

	name: str
	description: str
	duration: str | None = None
	technologies: list[str] = Field(default_factory=list)
	link: str | None = None


class Publication(BaseModel):
	"""论文发表"""
	model_config = ConfigDict(extra='forbid')

	title: str
	venue: str
	authors: list[str]
	year: int
	link: str | None = None


class Competition(BaseModel):
	"""竞赛成绩"""
	model_config = ConfigDict(extra='forbid')

	name: str
	rank: str
	year: int


class ResumeData(BaseModel):
	"""简历数据模型"""
	model_config = ConfigDict(extra='forbid')

	name: str
	email: str = ''
	phone: str = ''
	location: str | None = None
	linkedin: str | None = None
	github: str | None = None
	website: str | None = None
	summary: str | None = None
	education: list[Education] = Field(default_factory=list)
	skills: list[str] = Field(default_factory=list)
	projects: list[Project] = Field(default_factory=list)
	experience: list[Experience] = Field(default_factory=list)
	publications: list[Publication] = Field(default_factory=list)
	competitions: list[Competition] = Field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		"""转换为字典"""
		return self.model_dump()

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> 'ResumeData':
		"""从字典创建实例"""
		return cls.model_validate(data)


class JobRequirement(BaseModel):
	"""岗位需求模型"""
	model_config = ConfigDict(extra='forbid')

	title: str
	company: str
	required_skills: list[str] = Field(default_factory=list)
	preferred_skills: list[str] = Field(default_factory=list)
	responsibilities: list[str] = Field(default_factory=list)
	qualifications: list[str] = Field(default_factory=list)
	salary_range: str | None = None
	location: str | None = None
	min_years: int = 0
	max_years: int = 0

	def to_dict(self) -> dict[str, Any]:
		"""转换为字典"""
		return self.model_dump()

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> 'JobRequirement':
		"""从字典创建实例"""
		return cls.model_validate(data)


class OptimizationChange(BaseModel):
	"""优化变更记录"""
	model_config = ConfigDict(extra='forbid')

	change_type: str = Field(..., alias='type')
	description: str | None = None
	field: str | None = None
	index: int | None = None
	reason: str | None = None
	added: list[str] | None = None
	prioritized: list[str] | None = None

	model_config = ConfigDict(
		extra='forbid',
		populate_by_name=True,
	)


class OptimizationResult(BaseModel):
	"""优化结果模型"""
	model_config = ConfigDict(extra='forbid')

	original_resume: ResumeData
	optimized_resume: ResumeData
	style: str
	changes: list[OptimizationChange] = Field(default_factory=list)
	match_score: float = 0.0
	suggestions: list[str] = Field(default_factory=list)

	def to_dict(self) -> dict[str, Any]:
		"""转换为字典"""
		return self.model_dump()


class OptimizeRequest(BaseModel):
	"""优化请求模型"""
	model_config = ConfigDict(extra='forbid')

	resume: dict[str, Any]
	job_requirements: dict[str, Any]
	style: str = 'big_tech'
	output_format: str = 'html'

	@classmethod
	def validate_style(cls, v: str) -> str:
		"""验证风格参数"""
		valid_styles = {'big_tech', 'research', 'product', 'algorithm', 'backend'}
		if v not in valid_styles:
			raise ValueError(f'Invalid style: {v}. Must be one of {valid_styles}')
		return v


class OptimizeResponse(BaseModel):
	"""优化响应模型"""
	model_config = ConfigDict(extra='forbid')

	success: bool
	optimized_resume: dict[str, Any] | None = None
	changes: list[dict[str, Any]] | None = None
	match_score: float | None = None
	suggestions: list[str] | None = None
	html_preview: str | None = None
	error_message: str | None = None


class ParseResult(BaseModel):
	"""解析结果模型"""
	model_config = ConfigDict(extra='forbid')

	success: bool
	data: dict[str, Any] | None = None
	error: str | None = None


class RenderResult(BaseModel):
	"""渲染结果模型"""
	model_config = ConfigDict(extra='forbid')

	success: bool
	content: str | bytes | None = None
	format: str | None = None
	error: str | None = None


class StyleInfo(BaseModel):
	"""风格信息模型"""
	model_config = ConfigDict(extra='forbid')

	id: str
	name: str
	description: str
	keywords: list[str]
