"""
简历优化 API 接口

为后端编排层提供统一的 API 接口。
"""

from typing import Any

from .optimizer import ResumeOptimizer, OptimizationStyle
from .utils import ResumeParser, TemplateRenderer
from .views import (
	ResumeData,
	JobRequirement,
	OptimizeRequest,
	OptimizeResponse,
	ParseResult,
	RenderResult,
	StyleInfo,
)


class ResumeOptimizerAPI:
	"""
	简历优化 API

	提供与后端编排层对接的接口。
	"""

	def __init__(self, llm_service: 'LLMService | None' = None):
		self.optimizer = ResumeOptimizer(llm_service)
		self.parser = ResumeParser()
		self.renderer = TemplateRenderer()

	async def optimize_resume(self, request: OptimizeRequest) -> OptimizeResponse:
		"""
		优化简历

		Args:
			request: 优化请求

		Returns:
			OptimizeResponse: 优化响应
		"""
		try:
			# 解析风格
			style_map = {
				'big_tech': OptimizationStyle.BIG_TECH,
				'research': OptimizationStyle.RESEARCH,
				'product': OptimizationStyle.PRODUCT,
				'algorithm': OptimizationStyle.ALGORITHM,
				'backend': OptimizationStyle.BACKEND,
			}
			style = style_map.get(request.style, OptimizationStyle.BIG_TECH)

			# 构建简历数据
			resume_data = self._dict_to_resume_data(request.resume)

			# 构建岗位需求
			job_requirement = self._dict_to_job_requirement(request.job_requirements)

			# 执行优化
			result = await self.optimizer.optimize(resume_data, job_requirement, style)

			# 生成预览
			optimized_dict = result.optimized_resume.to_dict()
			html_preview = self.renderer.render_to_html(optimized_dict)

			return OptimizeResponse(
				success=True,
				optimized_resume=optimized_dict,
				changes=[c.model_dump(by_alias=True) for c in result.changes],
				match_score=result.match_score,
				suggestions=result.suggestions,
				html_preview=html_preview
			)

		except Exception as e:
			# 记录错误但不暴露敏感信息
			return OptimizeResponse(
				success=False,
				error_message=f'优化失败: {type(e).__name__}'
			)

	def parse_resume(self, file_path: str) -> ParseResult:
		"""
		解析简历文件

		Args:
			file_path: 文件路径

		Returns:
			ParseResult: 解析结果
		"""
		try:
			parsed = self.parser.parse(file_path)
			return ParseResult(
				success=True,
				data=self.parser.to_json(parsed)
			)
		except FileNotFoundError:
			return ParseResult(
				success=False,
				error=f'文件不存在: {file_path}'
			)
		except ValueError as e:
			return ParseResult(
				success=False,
				error=f'不支持的文件格式: {str(e)}'
			)
		except ImportError as e:
			return ParseResult(
				success=False,
				error=f'缺少依赖: {str(e)}'
			)
		except Exception as e:
			return ParseResult(
				success=False,
				error=f'解析失败: {type(e).__name__}'
			)

	def render_resume(
		self,
		resume_data: dict[str, Any],
		output_format: str = 'html',
		output_path: str | None = None,
		style: str = 'modern'
	) -> RenderResult:
		"""
		渲染简历

		Args:
			resume_data: 简历数据
			output_format: 输出格式 (html, markdown, pdf)
			output_path: 输出路径
			style: 模板风格

		Returns:
			RenderResult: 渲染结果
		"""
		try:
			if output_format == 'html':
				content = self.renderer.render_to_html(resume_data, style, output_path)
				return RenderResult(
					success=True,
					content=content,
					format='html'
				)

			elif output_format == 'markdown':
				content = self.renderer.render_to_markdown(resume_data, output_path)
				return RenderResult(
					success=True,
					content=content,
					format='markdown'
				)

			elif output_format == 'pdf':
				content = self.renderer.render_to_pdf(resume_data, style, output_path)
				return RenderResult(
					success=True,
					content=content,
					format='pdf'
				)

			else:
				return RenderResult(
					success=False,
					error=f'不支持的格式: {output_format}'
				)

		except ImportError as e:
			return RenderResult(
				success=False,
				error=f'缺少依赖: {str(e)}'
			)
		except Exception as e:
			return RenderResult(
				success=False,
				error=f'渲染失败: {type(e).__name__}'
			)

	def preview_changes(
		self,
		original: dict[str, Any],
		optimized: dict[str, Any],
		changes: list[dict[str, Any]]
	) -> str:
		"""
		预览变更

		Args:
			original: 原始简历
			optimized: 优化后的简历
			changes: 变更记录

		Returns:
			str: HTML预览
		"""
		return self.renderer.preview_changes(original, optimized, changes)

	def get_available_styles(self) -> list[StyleInfo]:
		"""
		获取可用的优化风格

		Returns:
			list[StyleInfo]: 风格列表
		"""
		return [
			StyleInfo(
				id='big_tech',
				name='大厂风格',
				description='强调技术深度、系统设计和量化成果，适合申请大型科技公司',
				keywords=['系统设计', '分布式', '高并发', '性能优化']
			),
			StyleInfo(
				id='research',
				name='科研风格',
				description='强调论文发表、研究成果和创新性，适合申请研究型岗位',
				keywords=['论文', '研究', '算法', '创新']
			),
			StyleInfo(
				id='product',
				name='产品风格',
				description='强调用户思维和数据驱动，适合申请产品相关岗位',
				keywords=['用户', '数据', '产品', '迭代']
			),
			StyleInfo(
				id='algorithm',
				name='算法岗风格',
				description='强调算法能力和模型优化，适合申请算法工程师岗位',
				keywords=['机器学习', '深度学习', '竞赛', '模型']
			),
			StyleInfo(
				id='backend',
				name='后端岗风格',
				description='强调系统架构和高可用，适合申请后端工程师岗位',
				keywords=['微服务', '数据库', '缓存', '架构']
			)
		]

	def _dict_to_resume_data(self, data: dict[str, Any]) -> ResumeData:
		"""字典转 ResumeData"""
		return ResumeData.from_dict(data)

	def _dict_to_job_requirement(self, data: dict[str, Any]) -> JobRequirement:
		"""字典转 JobRequirement"""
		return JobRequirement.from_dict(data)


# 全局 API 实例（供简单使用）
api = ResumeOptimizerAPI()


async def optimize_resume_endpoint(request_data: dict[str, Any]) -> dict[str, Any]:
	"""
	优化简历端点 (供后端调用)

	Args:
		request_data: 请求数据

	Returns:
		dict: 优化结果
	"""
	try:
		request = OptimizeRequest.model_validate(request_data)
		response = await api.optimize_resume(request)
		return response.model_dump()
	except Exception as e:
		return OptimizeResponse(
			success=False,
			error_message=f'请求参数错误: {str(e)}'
		).model_dump()


def get_styles_endpoint() -> list[dict[str, Any]]:
	"""获取可用风格端点"""
	return [s.model_dump() for s in api.get_available_styles()]


def parse_resume_endpoint(file_path: str) -> dict[str, Any]:
	"""解析简历端点"""
	return api.parse_resume(file_path).model_dump()


def render_resume_endpoint(
	resume_data: dict[str, Any],
	output_format: str = 'html',
	output_path: str | None = None,
	style: str = 'modern'
) -> dict[str, Any]:
	"""渲染简历端点"""
	return api.render_resume(
		resume_data, output_format, output_path, style
	).model_dump()
