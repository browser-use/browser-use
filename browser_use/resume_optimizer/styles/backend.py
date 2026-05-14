"""
后端岗风格优化器

特点：
- 强调系统设计和架构能力
- 突出高并发、高可用经验
- 展示数据库和中间件熟练度
- 适合申请后端工程师岗位
"""

from typing import Any

from .base import BaseStyle, StyleConfig


class BackendStyle(BaseStyle):
	"""后端岗风格简历优化"""

	def __init__(self):
		config = StyleConfig(
			name="后端岗风格",
			description="适合申请后端工程师岗位的简历风格",
			priority_skills=[
				'Java', 'Go', 'Python', 'C++',
				'Spring', 'Spring Boot', 'Microservices',
				'MySQL', 'PostgreSQL', 'Redis', 'MongoDB',
				'Kafka', 'RabbitMQ', 'Elasticsearch',
				'Docker', 'Kubernetes', 'Linux'
			],
			keywords=[
				'concurrent', 'high availability', 'scalability', 'performance',
				'database', 'cache', 'message queue', 'API', 'RESTful',
				'microservices', 'distributed', 'load balancing', 'cluster'
			],
			emphasis_areas=[
				'system_architecture', 'performance', 'reliability', 'scalability'
			]
		)
		super().__init__(config)

	def optimize(
		self,
		resume_data: dict[str, Any],
		job_requirements: dict[str, Any]
	) -> tuple[dict[str, Any], list[dict[str, Any]]]:
		"""优化简历为后端岗风格"""
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
					'description': '将后端技能前置',
					'rationale': '突出核心技术栈'
				})

		# 2. 优化项目描述 - 强调高并发和架构
		if 'projects' in optimized:
			for i, project in enumerate(optimized['projects']):
				old_desc = project.get('description', '')
				new_desc = self._enhance_backend_description(old_desc)

				if old_desc != new_desc:
					project['description'] = new_desc
					changes.append({
						'type': 'project_enhanced',
						'index': i,
						'project_name': project.get('name', f'Project {i}'),
						'description': '添加系统架构和性能优化描述',
						'rationale': '后端岗关注系统设计和性能'
					})

		# 3. 生成后端岗个人总结
		if 'summary' not in optimized or not optimized['summary']:
			optimized['summary'] = self.generate_summary(optimized)
			changes.append({
				'type': 'summary_added',
				'description': '添加后端岗风格的个人总结',
				'rationale': '展示后端技术专长'
			})

		return optimized, changes

	def generate_summary(self, resume_data: dict[str, Any]) -> str:
		"""生成后端岗风格的个人总结"""
		skills = resume_data.get('skills', [])

		# 识别主要技术栈
		has_java = any('java' in s.lower() for s in skills)
		has_go = any('go' in s.lower() or 'golang' in s.lower() for s in skills)

		if has_java:
			role = "资深Java后端工程师"
		elif has_go:
			role = "资深Go后端工程师"
		else:
			role = "资深后端工程师"

		return (
			f"{role}，专注于高并发系统设计和微服务架构。"
			"精通数据库优化、缓存策略和消息队列，"
			"具备丰富的大型系统开发和运维经验。"
		)

	def _enhance_backend_description(self, description: str) -> str:
		"""增强后端项目描述"""
		if not description:
			return description

		enhanced = description

		# 检查是否提到并发/性能
		perf_keywords = ['并发', 'qps', 'tps', 'latency', 'performance', '高可用']
		has_perf = any(kw in description.lower() for kw in perf_keywords)

		if not has_perf:
			enhanced += (
				" 设计了高性能的系统架构，"
				"支持高并发访问和数据处理。"
			)

		# 检查是否提到架构
		arch_keywords = ['架构', '微服务', 'microservices', 'distributed', '分布式']
		has_arch = any(kw in description.lower() for kw in arch_keywords)

		if not has_arch:
			enhanced += (
				" 采用微服务架构，实现服务解耦和水平扩展。"
			)

		return enhanced
