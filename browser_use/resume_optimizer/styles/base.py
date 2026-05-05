"""
风格优化基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class StyleConfig:
	"""风格配置"""
	name: str
	description: str
	priority_skills: list[str]
	keywords: list[str]
	emphasis_areas: list[str]


class BaseStyle(ABC):
	"""简历风格优化基类"""

	def __init__(self, config: StyleConfig):
		self.config = config

	@abstractmethod
	def optimize(
		self,
		resume_data: dict[str, Any],
		job_requirements: dict[str, Any]
	) -> tuple[dict[str, Any], list[dict[str, Any]]]:
		"""
		优化简历

		Args:
			resume_data: 简历数据
			job_requirements: 岗位要求

		Returns:
			(优化后的简历, 变更记录列表)
		"""
		pass

	@abstractmethod
	def generate_summary(self, resume_data: dict[str, Any]) -> str:
		"""生成个人总结"""
		pass

	def reorder_skills(
		self,
		skills: list[str],
		priority_skills: list[str]
	) -> list[str]:
		"""将优先技能前置"""
		prioritized = []
		others = []

		for skill in skills:
			skill_lower = skill.lower()
			is_priority = any(
				ps.lower() in skill_lower or skill_lower in ps.lower()
				for ps in priority_skills
			)
			if is_priority:
				prioritized.append(skill)
			else:
				others.append(skill)

		return prioritized + others

	def enhance_description(
		self,
		description: str,
		keywords: list[str]
	) -> str:
		"""增强描述，突出关键词"""
		# 基础实现，子类可覆盖
		return description

	def calculate_relevance_score(
		self,
		resume_data: dict[str, Any],
		job_requirements: dict[str, Any]
	) -> float:
		"""计算简历与岗位的相关性分数"""
		score = 0.0
		total_weight = 0

		# 技能匹配
		resume_skills = set(s.lower() for s in resume_data.get('skills', []))
		required_skills = set(s.lower() for s in job_requirements.get('required_skills', []))

		if required_skills:
			matched = len(resume_skills & required_skills)
			score += (matched / len(required_skills)) * 50
			total_weight += 50

		# 关键词匹配
		all_text = ' '.join([
			str(resume_data.get('summary', '')),
			' '.join(str(p.get('description', '')) for p in resume_data.get('projects', [])),
			' '.join(str(e.get('description', '')) for e in resume_data.get('experience', []))
		]).lower()

		keyword_matches = sum(1 for kw in self.config.keywords if kw.lower() in all_text)
		if self.config.keywords:
			score += (keyword_matches / len(self.config.keywords)) * 30
			total_weight += 30

		# 经验年限
		exp_years = self._calculate_experience_years(resume_data.get('experience', []))
		required_years = job_requirements.get('min_years', 0)
		if required_years > 0:
			exp_score = min(exp_years / required_years, 1.5)  # 最多1.5倍
			score += exp_score * 20
			total_weight += 20

		return (score / total_weight * 100) if total_weight > 0 else 0.0

	def _calculate_experience_years(self, experience: list[dict[str, Any]]) -> int:
		"""计算工作年限"""
		total_months = 0
		for exp in experience:
			duration = exp.get('duration', '')
			# 简单的解析逻辑，可根据实际格式调整
			if 'year' in duration.lower():
				try:
					years = int(''.join(filter(str.isdigit, duration)))
					total_months += years * 12
				except Exception:
					pass
			if 'month' in duration.lower():
				try:
					months = int(''.join(filter(str.isdigit, duration)))
					total_months += months
				except Exception:
					pass
		return total_months // 12
