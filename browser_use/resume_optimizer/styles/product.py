"""
产品风格优化器

特点：
- 强调用户思维和产品sense
- 突出数据驱动决策
- 展示跨部门协作能力
- 适合申请产品经理或产品工程师岗位
"""

from typing import Any

from .base import BaseStyle, StyleConfig


class ProductStyle(BaseStyle):
	"""产品风格简历优化"""

	def __init__(self):
		config = StyleConfig(
			name="产品风格",
			description="适合申请产品相关岗位的简历风格",
			priority_skills=[
				'Product Management', 'User Experience', 'Data Analysis',
				'A/B Testing', 'User Research', 'Market Analysis',
				'Agile', 'Scrum', 'Product Strategy', 'Roadmap Planning'
			],
			keywords=[
				'user', 'customer', 'product', 'feature', 'launch',
				'metrics', 'KPI', 'conversion', 'retention', 'engagement',
				'data-driven', 'insight', 'iteration', 'feedback'
			],
			emphasis_areas=[
				'user_focus', 'data_driven', 'business_impact', 'iteration'
			]
		)
		super().__init__(config)

	def optimize(
		self,
		resume_data: dict[str, Any],
		job_requirements: dict[str, Any]
	) -> tuple[dict[str, Any], list[dict[str, Any]]]:
		"""优化简历为产品风格"""
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
					'description': '将产品相关技能前置',
					'rationale': '突出产品思维和方法论'
				})

		# 2. 优化项目描述 - 强调用户和数据
		if 'projects' in optimized:
			for i, project in enumerate(optimized['projects']):
				old_desc = project.get('description', '')
				new_desc = self._enhance_product_description(old_desc)

				if old_desc != new_desc:
					project['description'] = new_desc
					changes.append({
						'type': 'project_enhanced',
						'index': i,
						'project_name': project.get('name', f'Project {i}'),
						'description': '添加用户思维和数据驱动描述',
						'rationale': '产品岗关注用户价值和数据洞察'
					})

		# 3. 生成产品型个人总结
		if 'summary' not in optimized or not optimized['summary']:
			optimized['summary'] = self.generate_summary(optimized)
			changes.append({
				'type': 'summary_added',
				'description': '添加产品风格的个人总结',
				'rationale': '展示产品思维和用户导向'
			})

		return optimized, changes

	def generate_summary(self, resume_data: dict[str, Any]) -> str:
		"""生成产品风格的个人总结"""
		return (
			"具备技术背景的产品工程师，善于从用户需求出发设计和迭代产品。"
			"擅长通过数据分析驱动产品决策，具备出色的跨部门协作能力。"
			"致力于创造有用户价值的产品体验。"
		)

	def _enhance_product_description(self, description: str) -> str:
		"""增强产品项目描述"""
		if not description:
			return description

		enhanced = description

		# 检查是否提到用户
		user_keywords = ['用户', 'user', 'customer', '客户']
		has_user_focus = any(kw in description.lower() for kw in user_keywords)

		if not has_user_focus:
			enhanced += (
				" 基于用户反馈持续优化产品体验，"
				"提升了用户满意度和产品指标。"
			)

		# 检查是否提到数据
		data_keywords = ['数据', '指标', 'metrics', 'conversion', 'retention']
		has_data_focus = any(kw in description.lower() for kw in data_keywords)

		if not has_data_focus:
			enhanced += (
				" 通过A/B测试和数据验证指导产品迭代方向。"
			)

		return enhanced
