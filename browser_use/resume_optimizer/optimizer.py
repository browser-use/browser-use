"""
简历优化核心逻辑
"""

import copy
import re
from enum import Enum
from pathlib import Path

from .views import (
	ResumeData,
	JobRequirement,
	OptimizationResult,
	OptimizationChange,
	Education,
	Experience,
	Project,
)
from .llm_enhancer import LLMEnhancer


class OptimizationStyle(Enum):
	"""简历优化风格"""
	BIG_TECH = 'big_tech'		# 大厂风
	RESEARCH = 'research'		# 科研风
	PRODUCT = 'product'			# 产品风
	ALGORITHM = 'algorithm'		# 算法岗风
	BACKEND = 'backend'			# 后端岗风


class ResumeOptimizer:
	"""
	简历优化器

	根据目标岗位需求，使用不同风格模板优化简历
	"""

	def __init__(self, llm_service: 'LLMService | None' = None):
		self.llm_enhancer = LLMEnhancer(llm_service)
		self.style_handlers = {
			OptimizationStyle.BIG_TECH: self._apply_big_tech_style,
			OptimizationStyle.RESEARCH: self._apply_research_style,
			OptimizationStyle.PRODUCT: self._apply_product_style,
			OptimizationStyle.ALGORITHM: self._apply_algorithm_style,
			OptimizationStyle.BACKEND: self._apply_backend_style,
		}

	async def optimize(
		self,
		resume: ResumeData,
		job: JobRequirement,
		style: OptimizationStyle = OptimizationStyle.BIG_TECH
	) -> OptimizationResult:
		"""
		优化简历以匹配目标岗位

		Args:
			resume: 原始简历数据
			job: 目标岗位信息
			style: 优化风格

		Returns:
			OptimizationResult: 优化结果
		"""
		# 计算当前匹配度
		current_score = self._calculate_match_score(resume, job)

		# 根据风格应用优化
		handler = self.style_handlers.get(style, self._apply_big_tech_style)
		optimized_resume, changes = await handler(resume, job)

		# 计算优化后匹配度
		new_score = self._calculate_match_score(optimized_resume, job)

		# 生成建议
		suggestions = await self.llm_enhancer.suggest_improvements(resume, job)

		return OptimizationResult(
			original_resume=resume,
			optimized_resume=optimized_resume,
			style=style.value,
			changes=changes,
			match_score=new_score,
			suggestions=suggestions
		)

	def _calculate_match_score(self, resume: ResumeData, job: JobRequirement) -> float:
		"""计算简历与岗位的匹配分数"""
		score = 0.0
		total = 0

		# 必需技能匹配
		for skill in job.required_skills:
			total += 2
			if any(
				skill.lower() in rs.lower() or rs.lower() in skill.lower()
				for rs in resume.skills
			):
				score += 2

		# 优先技能匹配
		for skill in job.preferred_skills:
			total += 1
			if any(
				skill.lower() in rs.lower() or rs.lower() in skill.lower()
				for rs in resume.skills
			):
				score += 1

		return (score / total * 100) if total > 0 else 0.0

	async def _apply_big_tech_style(
		self,
		resume: ResumeData,
		job: JobRequirement
	) -> tuple[ResumeData, list[OptimizationChange]]:
		"""
		大厂风格优化
		- 强调技术深度和系统设计
		- 量化成果（用户量、性能提升、营收等）
		- 突出协作和影响力
		"""
		changes: list[OptimizationChange] = []
		optimized = self._deep_copy_resume(resume)

		# 优化项目描述 - 使用 LLM 增强
		for i, project in enumerate(optimized.projects):
			old_desc = project.description
			new_desc, enh_changes = await self.llm_enhancer.enhance_project_description(
				old_desc, 'big_tech', job
			)
			if old_desc != new_desc:
				project.description = new_desc
				changes.append(OptimizationChange(
					change_type='project_enhancement',
					index=i,
					field='description',
					reason='大厂风格：强调量化成果和业务影响'
				))
			changes.extend(enh_changes)

		# 优化技能列表 - 匹配岗位需求
		skill_changes = self._optimize_skills_for_job(optimized.skills, job)
		if skill_changes:
			optimized.skills = skill_changes['optimized']
			changes.append(OptimizationChange(
				change_type='skills_optimization',
				description='技能列表优化',
				reason='大厂风格：优先展示岗位相关技能',
				added=skill_changes.get('added', []),
				prioritized=skill_changes.get('prioritized', [])
			))

		# 生成或优化个人总结
		if not optimized.summary:
			optimized.summary = await self.llm_enhancer.generate_summary(
				resume, 'big_tech', job
			)
			changes.append(OptimizationChange(
				change_type='summary_added',
				description='添加大厂风格的个人总结',
				reason='突出技术深度和影响力'
			))

		return optimized, changes

	async def _apply_research_style(
		self,
		resume: ResumeData,
		job: JobRequirement
	) -> tuple[ResumeData, list[OptimizationChange]]:
		"""
		科研风格优化
		- 强调论文、专利、研究成果
		- 突出技术创新和学术贡献
		- 展示研究方法和实验设计
		"""
		changes: list[OptimizationChange] = []
		optimized = self._deep_copy_resume(resume)

		# 突出研究项目和学术成果
		research_projects = [
			p for p in optimized.projects
			if self._is_research_project(p)
		]
		if research_projects:
			changes.append(OptimizationChange(
				change_type='research_highlight',
				description=f'突出{len(research_projects)}个研究项目',
				reason='科研风格：展示研究能力和学术贡献'
			))

		# 优化项目描述
		for i, project in enumerate(optimized.projects):
			if self._is_research_project(project):
				old_desc = project.description
				new_desc, enh_changes = await self.llm_enhancer.enhance_project_description(
					old_desc, 'research', job
				)
				if old_desc != new_desc:
					project.description = new_desc
					changes.extend(enh_changes)

		# 生成科研风格总结
		if not optimized.summary:
			optimized.summary = await self.llm_enhancer.generate_summary(
				resume, 'research', job
			)
			changes.append(OptimizationChange(
				change_type='summary_added',
				description='添加科研风格的个人总结',
				reason='展示研究兴趣和学术背景'
			))

		return optimized, changes

	async def _apply_product_style(
		self,
		resume: ResumeData,
		job: JobRequirement
	) -> tuple[ResumeData, list[OptimizationChange]]:
		"""
		产品风格优化
		- 强调用户思维和产品sense
		- 突出数据驱动决策
		- 展示跨部门协作能力
		"""
		changes: list[OptimizationChange] = []
		optimized = self._deep_copy_resume(resume)

		# 优化项目描述 - 强调产品思维
		for i, project in enumerate(optimized.projects):
			old_desc = project.description
			new_desc, enh_changes = await self.llm_enhancer.enhance_project_description(
				old_desc, 'product', job
			)
			if old_desc != new_desc:
				project.description = new_desc
				changes.append(OptimizationChange(
					change_type='product_focus',
					index=i,
					description='添加用户思维和数据驱动描述',
					reason='产品风格：突出用户价值和产品能力'
				))
			changes.extend(enh_changes)

		# 生成产品风格总结
		if not optimized.summary:
			optimized.summary = await self.llm_enhancer.generate_summary(
				resume, 'product', job
			)
			changes.append(OptimizationChange(
				change_type='summary_added',
				description='添加产品风格的个人总结',
				reason='展示产品思维和用户导向'
			))

		return optimized, changes

	async def _apply_algorithm_style(
		self,
		resume: ResumeData,
		job: JobRequirement
	) -> tuple[ResumeData, list[OptimizationChange]]:
		"""
		算法岗风格优化
		- 强调算法能力和模型优化
		- 突出竞赛成绩和开源贡献
		- 展示数学和统计基础
		"""
		changes: list[OptimizationChange] = []
		optimized = self._deep_copy_resume(resume)

		# 优化技能 - 算法相关技能前置
		algo_skills = [
			'Machine Learning', 'Deep Learning', 'PyTorch', 'TensorFlow',
			'Computer Vision', 'NLP', 'Reinforcement Learning',
			'Algorithm', 'Data Structure', 'Mathematics'
		]

		reordered_skills = self._prioritize_skills(optimized.skills, algo_skills)
		if reordered_skills != optimized.skills:
			optimized.skills = reordered_skills
			changes.append(OptimizationChange(
				change_type='skills_reorder',
				description='将算法技能前置',
				reason='算法岗风格：突出核心算法能力'
			))

		# 优化项目描述
		for i, project in enumerate(optimized.projects):
			old_desc = project.description
			new_desc, enh_changes = await self.llm_enhancer.enhance_project_description(
				old_desc, 'algorithm', job
			)
			if old_desc != new_desc:
				project.description = new_desc
				changes.extend(enh_changes)

		# 生成算法岗风格总结
		if not optimized.summary:
			optimized.summary = await self.llm_enhancer.generate_summary(
				resume, 'algorithm', job
			)
			changes.append(OptimizationChange(
				change_type='summary_added',
				description='添加算法岗风格的个人总结',
				reason='展示算法专长和研究能力'
			))

		return optimized, changes

	async def _apply_backend_style(
		self,
		resume: ResumeData,
		job: JobRequirement
	) -> tuple[ResumeData, list[OptimizationChange]]:
		"""
		后端岗风格优化
		- 强调系统设计和架构能力
		- 突出高并发、高可用经验
		- 展示数据库和中间件熟练度
		"""
		changes: list[OptimizationChange] = []
		optimized = self._deep_copy_resume(resume)

		# 优化技能 - 后端相关技能前置
		backend_skills = [
			'Java', 'Go', 'Python', 'Spring', 'Microservices',
			'MySQL', 'Redis', 'Kafka', 'Elasticsearch',
			'Docker', 'Kubernetes', 'Linux'
		]

		reordered_skills = self._prioritize_skills(optimized.skills, backend_skills)
		if reordered_skills != optimized.skills:
			optimized.skills = reordered_skills
			changes.append(OptimizationChange(
				change_type='skills_reorder',
				description='将后端技能前置',
				reason='后端岗风格：突出核心技术栈'
			))

		# 优化项目描述
		for i, project in enumerate(optimized.projects):
			old_desc = project.description
			new_desc, enh_changes = await self.llm_enhancer.enhance_project_description(
				old_desc, 'backend', job
			)
			if old_desc != new_desc:
				project.description = new_desc
				changes.extend(enh_changes)

		# 生成后端岗风格总结
		if not optimized.summary:
			optimized.summary = await self.llm_enhancer.generate_summary(
				resume, 'backend', job
			)
			changes.append(OptimizationChange(
				change_type='summary_added',
				description='添加后端岗风格的个人总结',
				reason='展示后端技术专长'
			))

		return optimized, changes

	def _deep_copy_resume(self, resume: ResumeData) -> ResumeData:
		"""深拷贝简历数据"""
		return ResumeData.model_validate(resume.model_dump())

	def _is_research_project(self, project: Project) -> bool:
		"""判断是否为研究项目"""
		research_keywords = ['paper', 'publication', 'research', '算法', '模型', '论文']
		desc = project.description.lower()
		return any(kw in desc for kw in research_keywords)

	def _optimize_skills_for_job(
		self,
		skills: list[str],
		job: JobRequirement
	) -> dict[str, list[str]] | None:
		"""根据岗位优化技能列表"""
		added = []
		prioritized = []

		# 检查是否有缺失的必需技能
		for job_skill in job.required_skills:
			if not any(
				job_skill.lower() in s.lower() or s.lower() in job_skill.lower()
				for s in skills
			):
				# 可以在这里添加建议学习的技能
				pass

		# 将岗位相关技能前置
		all_job_skills = job.required_skills + job.preferred_skills
		reordered = self._prioritize_skills(skills, all_job_skills)

		if reordered != skills:
			return {
				'optimized': reordered,
				'added': added,
				'prioritized': [s for s in reordered if s in all_job_skills]
			}

		return None

	def _prioritize_skills(
		self,
		skills: list[str],
		priority_skills: list[str]
	) -> list[str]:
		"""将优先技能前置"""
		prioritized = []
		others = []

		for skill in skills:
			is_priority = any(
				ps.lower() in skill.lower() or skill.lower() in ps.lower()
				for ps in priority_skills
			)
			if is_priority:
				prioritized.append(skill)
			else:
				others.append(skill)

		return prioritized + others
