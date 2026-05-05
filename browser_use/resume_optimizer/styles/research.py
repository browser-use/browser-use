"""
科研风格优化器

特点：
- 强调论文、专利、研究成果
- 突出技术创新和学术贡献
- 展示研究方法和实验设计能力
- 适合申请研究型岗位或博士项目
"""

from typing import Dict, List, Any, Tuple

from .base import BaseStyle, StyleConfig


class ResearchStyle(BaseStyle):
    """科研风格简历优化"""

    def __init__(self):
        config = StyleConfig(
            name="科研风格",
            description="适合申请研究型岗位或学术职位的简历风格",
            priority_skills=[
                'Machine Learning Research', 'Deep Learning', 'Computer Vision',
                'Natural Language Processing', 'Reinforcement Learning',
                'Statistics', 'Mathematics', 'Algorithm Design',
                'PyTorch', 'TensorFlow', 'JAX', 'Research Methods'
            ],
            keywords=[
                'publication', 'paper', 'conference', 'journal', 'patent',
                'research', 'experiment', 'hypothesis', 'analysis',
                'novel', 'state-of-the-art', 'SOTA', 'benchmark'
            ],
            emphasis_areas=[
                'publications', 'research_experience', 'technical_depth', 'innovation'
            ]
        )
        super().__init__(config)

    def optimize(
        self,
        resume_data: Dict[str, Any],
        job_requirements: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """优化简历为科研风格"""
        changes = []
        optimized = resume_data.copy()

        # 1. 优先展示研究和论文
        if 'publications' in optimized:
            changes.append({
                'type': 'publications_highlighted',
                'count': len(optimized['publications']),
                'description': '将论文发表前置展示',
                'rationale': '科研成果是研究岗的核心竞争力'
            })

        # 2. 优化技能列表 - 研究工具和理论
        if 'skills' in optimized:
            old_skills = optimized['skills']
            new_skills = self.reorder_skills(old_skills, self.config.priority_skills)
            if old_skills != new_skills:
                optimized['skills'] = new_skills
                changes.append({
                    'type': 'skills_reordered',
                    'description': '将研究相关技能前置',
                    'rationale': '突出研究方法论和工具掌握'
                })

        # 3. 优化项目描述 - 强调研究贡献
        if 'projects' in optimized:
            for i, project in enumerate(optimized['projects']):
                if self._is_research_project(project):
                    old_desc = project.get('description', '')
                    new_desc = self._enhance_research_description(old_desc)

                    if old_desc != new_desc:
                        project['description'] = new_desc
                        changes.append({
                            'type': 'research_project_enhanced',
                            'index': i,
                            'project_name': project.get('name', f'Project {i}'),
                            'description': '突出研究方法和创新点',
                            'rationale': '研究岗关注方法论和创新性'
                        })

        # 4. 生成研究型个人总结
        if 'summary' not in optimized or not optimized['summary']:
            optimized['summary'] = self.generate_summary(optimized)
            changes.append({
                'type': 'summary_added',
                'description': '添加科研风格的个人总结',
                'rationale': '展示研究兴趣和学术背景'
            })

        return optimized, changes

    def generate_summary(self, resume_data: Dict[str, Any]) -> str:
        """生成科研风格的个人总结"""
        publications = resume_data.get('publications', [])
        research_areas = resume_data.get('research_areas', [])

        summary_parts = []

        # 研究定位
        if research_areas:
            summary_parts.append(
                f"专注于{', '.join(research_areas[:2])}等领域的研究"
            )
        else:
            summary_parts.append("致力于前沿技术研究")

        # 发表成果
        if publications:
            top_tier = [p for p in publications if self._is_top_tier_venue(p)]
            if top_tier:
                summary_parts.append(
                    f"，在顶级会议/期刊发表论文{len(top_tier)}篇"
                )

        # 研究能力
        summary_parts.append(
            "。具备扎实的理论基础和独立研究能力，"
            "擅长从复杂问题中提炼科学问题并设计实验验证。"
        )

        return ''.join(summary_parts)

    def _is_research_project(self, project: Dict[str, Any]) -> bool:
        """判断是否为研究项目"""
        research_keywords = [
            'paper', 'publication', 'research', '算法', '模型',
            'experiment', 'novel', 'state-of-the-art'
        ]
        desc = project.get('description', '').lower()
        name = project.get('name', '').lower()
        return any(kw in desc or kw in name for kw in research_keywords)

    def _enhance_research_description(self, description: str) -> str:
        """增强研究项目描述"""
        if not description:
            return description

        enhanced = description

        # 检查是否提到创新点
        innovation_keywords = ['novel', '创新', '首次', '提出', 'design']
        has_innovation = any(kw in description.lower() for kw in innovation_keywords)

        if not has_innovation:
            enhanced += (
                " 提出了新的方法/框架，"
                "在标准数据集上取得了有竞争力的结果。"
            )

        return enhanced

    def _is_top_tier_venue(self, publication: Dict[str, Any]) -> bool:
        """判断是否为顶级 venues"""
        top_venues = {
            'CVPR', 'ICCV', 'ECCV', 'NeurIPS', 'ICML', 'ICLR',
            'ACL', 'EMNLP', 'NAACL', 'SIGGRAPH', 'WWW', 'KDD',
            'Nature', 'Science', 'TPAMI', 'IJCV', 'JMLR'
        }
        venue = publication.get('venue', '').upper()
        return any(tv in venue for tv in top_venues)
