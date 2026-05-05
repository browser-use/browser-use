"""
LLM 简历增强器

使用大语言模型智能优化简历描述。
"""

from typing import TYPE_CHECKING

from .views import ResumeData, JobRequirement, OptimizationChange

if TYPE_CHECKING:
	from browser_use.llm.service import LLMService


class LLMEnhancer:
	"""
	使用 LLM 增强简历内容
	"""

	def __init__(self, llm_service: 'LLMService | None' = None):
		self.llm_service = llm_service

	async def enhance_project_description(
		self,
		description: str,
		style: str,
		job_requirements: JobRequirement | None = None
	) -> tuple[str, list[OptimizationChange]]:
		"""
		使用 LLM 增强项目描述

		Args:
			description: 原始描述
			style: 优化风格
			job_requirements: 岗位需求

		Returns:
			(增强后的描述, 变更记录)
		"""
		if not self.llm_service:
			# 如果没有 LLM 服务，返回原始描述
			return description, []

		style_prompts = {
			'big_tech': """
强调以下方面：
1. 使用量化指标（用户数、QPS、性能提升百分比、营收影响等）
2. 突出系统设计和架构能力
3. 体现技术深度和业务影响力
4. 使用强动词开头（设计、实现、优化、主导等）
""",
			'research': """
强调以下方面：
1. 研究方法和创新点
2. 实验设计和结果
3. 技术创新和学术贡献
4. 使用学术化的表达方式
""",
			'product': """
强调以下方面：
1. 用户思维和数据驱动决策
2. 产品迭代过程和结果
3. 跨部门协作能力
4. 突出用户价值和业务指标
""",
			'algorithm': """
强调以下方面：
1. 算法创新和模型优化
2. 性能指标（准确率、F1、AUC等）
3. 计算效率和资源优化
4. 使用专业的算法术语
""",
			'backend': """
强调以下方面：
1. 系统架构和高并发处理
2. 性能优化和稳定性保障
3. 数据库和中间件使用
4. 技术选型和架构决策
"""
		}

		style_prompt = style_prompts.get(style, style_prompts['big_tech'])

		job_context = ""
		if job_requirements:
			job_context = f"""
目标岗位信息：
- 职位：{job_requirements.title}
- 公司：{job_requirements.company}
- 必需技能：{', '.join(job_requirements.required_skills)}
- 优先技能：{', '.join(job_requirements.preferred_skills)}
"""

		prompt = f"""请优化以下项目描述，使其更适合求职简历。

{job_context}

优化风格要求：
{style_prompt}

原始描述：
{description}

请直接输出优化后的描述，不要添加任何解释。保持简洁专业，控制在3-5句话内。"""

		try:
			# 调用 LLM 服务
			response = await self.llm_service.generate(prompt)
			enhanced = response.strip()

			changes = []
			if enhanced != description:
				changes.append(OptimizationChange(
					change_type='llm_enhancement',
					description='使用 LLM 优化项目描述',
					reason=f'根据{style}风格增强表达'
				))

			return enhanced, changes
		except Exception:
			# LLM 调用失败，返回原始描述
			return description, []

	async def generate_summary(
		self,
		resume: ResumeData,
		style: str,
		job_requirements: JobRequirement | None = None
	) -> str:
		"""
		生成个人总结

		Args:
			resume: 简历数据
			style: 优化风格
			job_requirements: 岗位需求

		Returns:
			生成的总结
		"""
		if not self.llm_service:
			return self._generate_basic_summary(resume, style)

		skills_text = ', '.join(resume.skills[:10])
		exp_years = len(resume.experience)

		style_focus = {
			'big_tech': '技术深度、系统设计、业务影响力',
			'research': '研究能力、学术贡献、技术创新',
			'product': '用户思维、数据驱动、产品sense',
			'algorithm': '算法能力、模型优化、数学基础',
			'backend': '架构设计、高并发、系统稳定性'
		}

		job_context = ""
		if job_requirements:
			job_context = f"""
目标岗位：{job_requirements.title} at {job_requirements.company}
"""

		prompt = f"""请为以下候选人生成专业的个人总结（Profile/Summary）。

候选人信息：
- 姓名：{resume.name}
- 工作年限：{exp_years}年
- 核心技能：{skills_text}
{job_context}

风格重点：{style_focus.get(style, '技术能力和项目经验')}

要求：
1. 控制在2-3句话
2. 突出核心竞争力和职业定位
3. 与目标岗位匹配
4. 专业、简洁、有吸引力

请直接输出总结内容。"""

		try:
			response = await self.llm_service.generate(prompt)
			return response.strip()
		except Exception:
			return self._generate_basic_summary(resume, style)

	async def suggest_improvements(
		self,
		resume: ResumeData,
		job_requirements: JobRequirement
	) -> list[str]:
		"""
		提供简历改进建议

		Args:
			resume: 简历数据
			job_requirements: 岗位需求

		Returns:
			建议列表
		"""
		if not self.llm_service:
			return self._basic_suggestions(resume, job_requirements)

		resume_summary = f"""
技能：{', '.join(resume.skills)}
项目数：{len(resume.projects)}
工作经验：{len(resume.experience)}段
"""

		prompt = f"""请分析以下简历与目标岗位的匹配度，并提供3-5条具体改进建议。

简历概况：
{resume_summary}

目标岗位：
- 职位：{job_requirements.title}
- 公司：{job_requirements.company}
- 必需技能：{', '.join(job_requirements.required_skills)}
- 优先技能：{', '.join(job_requirements.preferred_skills)}

要求：
1. 建议要具体可操作
2. 指出缺失的关键技能或经验
3. 提供量化建议（如补充什么项目、学习什么技术）
4. 按优先级排序

请以 bullet point 格式输出。"""

		try:
			response = await self.llm_service.generate(prompt)
			suggestions = [
				line.strip().lstrip('- ').strip()
				for line in response.strip().split('\n')
				if line.strip().startswith('-') or line.strip().startswith('•')
			]
			return suggestions if suggestions else self._basic_suggestions(resume, job_requirements)
		except Exception:
			return self._basic_suggestions(resume, job_requirements)

	def _generate_basic_summary(self, resume: ResumeData, style: str) -> str:
		"""生成基础总结（无 LLM 时）"""
		exp_years = len(resume.experience)
		skills_count = len(resume.skills)

		summaries = {
			'big_tech': f"拥有{exp_years}年工作经验的全栈工程师，精通{skills_count}项核心技术，擅长系统设计和性能优化。",
			'research': f"专注于前沿技术研究的工程师，{exp_years}年研发经验，具备扎实的理论基础和创新能力。",
			'product': f"具备技术背景的产品工程师，{exp_years}年经验，善于用数据驱动产品决策。",
			'algorithm': f"专注于机器学习的算法工程师，{exp_years}年经验，具备扎实的数学和编程基础。",
			'backend': f"资深后端工程师，{exp_years}年经验，专注于高并发系统设计和微服务架构。"
		}

		return summaries.get(style, summaries['big_tech'])

	def _basic_suggestions(
		self,
		resume: ResumeData,
		job_requirements: JobRequirement
	) -> list[str]:
		"""基础建议（无 LLM 时）"""
		suggestions = []

		# 检查技能匹配
		missing_required = [
			skill for skill in job_requirements.required_skills
			if not any(skill.lower() in s.lower() for s in resume.skills)
		]

		if missing_required:
			suggestions.append(f"建议补充以下必需技能的学习或项目经验: {', '.join(missing_required[:3])}")

		# 检查项目数量
		if len(resume.projects) < 2:
			suggestions.append("建议增加至少1-2个有代表性的项目，展示技术深度和解决问题的能力")

		# 检查工作经验
		if len(resume.experience) == 0:
			suggestions.append("建议补充实习或工作经验，突出实际工作成果")

		return suggestions
