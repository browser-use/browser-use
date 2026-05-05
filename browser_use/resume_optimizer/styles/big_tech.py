"""
大厂风格优化器

特点：
- 强调技术深度和系统设计
- 量化成果（用户量、性能提升、营收等）
- 突出协作和影响力
- 展示解决复杂问题的能力
"""

import re
from typing import Any

from .base import BaseStyle, StyleConfig


class BigTechStyle(BaseStyle):
	"""大厂风格简历优化"""

	def __init__(self):
		config = StyleConfig(
			name="大厂风格",
			description="适合申请大型科技公司的简历风格",
			priority_skills=[
				'System Design', 'Distributed Systems', 'Microservices',
				'Cloud Computing', 'AWS', 'Azure', 'GCP',
				'Scalability', 'High Availability', 'Performance Optimization'
			],
			keywords=[
				'scalability', 'performance', 'distributed', 'architecture',
				'optimization', 'millions', 'billions', 'latency', 'throughput',
				'reliability', 'availability', 'cross-functional', 'leadership'
			],
			emphasis_areas=[
				'system_design', 'quantified_results', 'impact', 'collaboration'
			]
		)
		super().__init__(config)

	def optimize(
		self,
		resume_data: dict[str, Any],
		job_requirements: dict[str, Any]
	) -> tuple[dict[str, Any], list[dict[str, Any]]]:
		"""优化简历为大厂风格"""
		changes: list[dict[str, Any]] = []
		optimized = resume_data.copy()

		# 1. 优化技能列表
		if 'skills' in optimized:
			old_skills = optimized['skills']
			new_skills = self.reorder_skills(old_skills, self.config.priority_skills)
			if old_skills != new_skills:
				optimized['skills'] = new_skills
				changes.append({
					'type': 'skills_reordered',
					'description': '将系统设计和分布式相关技能前置',
					'rationale': '大厂重视系统架构能力'
				})

		# 2. 优化项目描述 - 强调量化和系统影响
		if 'projects' in optimized:
			for i, project in enumerate(optimized['projects']):
				old_desc = project.get('description', '')
				new_desc = self._enhance_project_description(old_desc)

				if old_desc != new_desc:
					project['description'] = new_desc
					changes.append({
						'type': 'project_enhanced',
						'index': i,
						'project_name': project.get('name', f'Project {i}'),
						'description': '添加量化指标和系统影响描述',
						'rationale': '大厂关注业务影响和规模数据'
					})

		# 3. 优化工作经历 - 突出协作和领导力
		if 'experience' in optimized:
			for i, exp in enumerate(optimized['experience']):
				old_desc = exp.get('description', '')
				new_desc = self._enhance_experience_description(old_desc)

				if old_desc != new_desc:
					exp['description'] = new_desc
					changes.append({
						'type': 'experience_enhanced',
						'index': i,
						'company': exp.get('company', f'Company {i}'),
						'description': '突出跨团队协作和技术领导力',
						'rationale': '大厂重视软技能和影响力'
					})

		# 4. 生成或优化个人总结
		if 'summary' not in optimized or not optimized['summary']:
			optimized['summary'] = self.generate_summary(optimized)
			changes.append({
				'type': 'summary_added',
				'description': '添加大厂风格的个人总结',
				'rationale': '个人总结是简历的第一印象'
			})
		else:
			old_summary = optimized['summary']
			new_summary = self._enhance_summary(old_summary)
			if old_summary != new_summary:
				optimized['summary'] = new_summary
				changes.append({
					'type': 'summary_enhanced',
					'description': '优化个人总结，突出技术深度和影响力',
					'rationale': '强化与大厂文化的匹配度'
				})

		return optimized, changes

	def generate_summary(self, resume_data: dict[str, Any]) -> str:
		"""生成大厂风格的个人总结"""
		skills = resume_data.get('skills', [])
		experience = resume_data.get('experience', [])

		# 识别关键技术能力
		has_system_design = any('system' in s.lower() or 'distributed' in s.lower() for s in skills)
		has_cloud = any(s in skills for s in ['AWS', 'Azure', 'GCP', 'Cloud'])

		summary_parts = []

		# 开场 - 年限和核心定位
		years = self._calculate_experience_years(experience)
		if years > 0:
			summary_parts.append(f"拥有{years}年经验的全栈工程师")
		else:
			summary_parts.append("富有激情的软件工程师")

		# 技术专长
		tech_focus = []
		if has_system_design:
			tech_focus.append("系统设计和分布式架构")
		if has_cloud:
			tech_focus.append("云原生技术栈")
		if tech_focus:
			summary_parts.append(f"，专注于{'、'.join(tech_focus)}")

		# 成果强调
		summary_parts.append(
			"。擅长构建高可用、可扩展的系统，"
			"具备在快速迭代环境中交付高质量产品的能力。"
			"热衷于解决复杂的技术挑战，推动团队技术升级。"
		)

		return ''.join(summary_parts)

	def _enhance_project_description(self, description: str) -> str:
		"""增强项目描述，添加量化指标"""
		if not description:
			return description

		enhanced = description

		# 检查是否已有量化数据
		has_metrics = bool(re.search(r'\d+[%万亿kmb]+', description, re.IGNORECASE))

		if not has_metrics:
			# 添加建议的量化框架
			enhanced += (
				" （建议补充：系统支持的QPS/TPS、服务用户数、"
				"性能优化提升百分比、成本节约等量化指标）"
			)

		# 强调系统设计
		system_keywords = ['设计', '架构', '分布式', 'scalability', 'performance']
		has_system_emphasis = any(kw in description.lower() for kw in system_keywords)

		if not has_system_emphasis:
			enhanced += (
				" 设计了可扩展的系统架构，支持未来业务增长。"
			)

		return enhanced

	def _enhance_experience_description(self, description: str) -> str:
		"""增强工作经历描述"""
		if not description:
			return description

		enhanced = description

		# 检查是否提到协作
		collaboration_keywords = ['团队', '协作', '跨部门', 'cross-functional', 'stakeholder']
		has_collaboration = any(kw in description.lower() for kw in collaboration_keywords)

		if not has_collaboration:
			enhanced += (
				" 与产品、设计团队紧密协作，推动技术方案落地。"
			)

		return enhanced

	def _enhance_summary(self, summary: str) -> str:
		"""增强个人总结"""
		enhanced = summary

		# 确保包含关键元素
		if 'impact' not in summary.lower() and '影响' not in summary:
			enhanced += " 致力于通过技术创新产生实际的业务影响。"

		return enhanced

	def _calculate_experience_years(self, experience: list[dict[str, Any]]) -> int:
		"""计算工作年限"""
		total_years = 0
		for exp in experience:
			duration = exp.get('duration', '')
			# 简单解析，如 "2020-2023" 或 "3 years"
			if 'year' in duration.lower():
				match = re.search(r'(\d+)', duration)
				if match:
					total_years += int(match.group(1))
		return total_years
