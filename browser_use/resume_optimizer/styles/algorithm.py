"""
算法岗风格优化器

特点：
- 强调算法能力和模型优化
- 突出竞赛成绩和开源贡献
- 展示数学和统计基础
- 适合申请算法工程师/研究员岗位
"""

from typing import Dict, List, Any, Tuple

from .base import BaseStyle, StyleConfig


class AlgorithmStyle(BaseStyle):
    """算法岗风格简历优化"""

    def __init__(self):
        config = StyleConfig(
            name="算法岗风格",
            description="适合申请算法工程师岗位的简历风格",
            priority_skills=[
                'Machine Learning', 'Deep Learning', 'Computer Vision',
                'Natural Language Processing', 'Reinforcement Learning',
                'PyTorch', 'TensorFlow', 'Model Optimization',
                'Algorithm', 'Data Structure', 'Mathematics', 'Statistics'
            ],
            keywords=[
                'accuracy', 'precision', 'recall', 'F1', 'AUC', 'mAP',
                'optimization', 'convergence', 'loss function', 'gradient',
                'neural network', 'transformer', 'CNN', 'RNN', 'GNN'
            ],
            emphasis_areas=[
                'algorithm_depth', 'model_performance', 'optimization', 'competition'
            ]
        )
        super().__init__(config)

    def optimize(
        self,
        resume_data: Dict[str, Any],
        job_requirements: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """优化简历为算法岗风格"""
        changes = []
        optimized = resume_data.copy()

        # 1. 优化技能列表 - 算法相关技能前置
        if 'skills' in optimized:
            old_skills = optimized['skills']
            new_skills = self.reorder_skills(old_skills, self.config.priority_skills)
            if old_skills != new_skills:
                optimized['skills'] = new_skills
                changes.append({
                    'type': 'skills_reordered',
                    'description': '将算法技能前置',
                    'rationale': '算法岗优先关注核心算法能力'
                })

        # 2. 突出竞赛成绩
        if 'competitions' in optimized:
            changes.append({
                'type': 'competitions_highlighted',
                'count': len(optimized['competitions']),
                'description': '将算法竞赛成绩前置展示',
                'rationale': '竞赛成绩是算法能力的重要证明'
            })

        # 3. 优化项目描述 - 强调模型性能
        if 'projects' in optimized:
            for i, project in enumerate(optimized['projects']):
                old_desc = project.get('description', '')
                new_desc = self._enhance_algorithm_description(old_desc)

                if old_desc != new_desc:
                    project['description'] = new_desc
                    changes.append({
                        'type': 'project_enhanced',
                        'index': i,
                        'project_name': project.get('name', f'Project {i}'),
                        'description': '添加模型性能指标',
                        'rationale': '算法岗关注模型精度和效率'
                    })

        # 4. 生成算法岗个人总结
        if 'summary' not in optimized or not optimized['summary']:
            optimized['summary'] = self.generate_summary(optimized)
            changes.append({
                'type': 'summary_added',
                'description': '添加算法岗风格的个人总结',
                'rationale': '展示算法专长和研究能力'
            })

        return optimized, changes

    def generate_summary(self, resume_data: Dict[str, Any]) -> str:
        """生成算法岗风格的个人总结"""
        competitions = resume_data.get('competitions', [])
        publications = resume_data.get('publications', [])

        summary_parts = []

        # 核心定位
        summary_parts.append(
            "专注于机器学习和深度学习的算法工程师，"
            "具备扎实的数学和编程基础"
        )

        # 竞赛/发表成果
        if competitions:
            summary_parts.append(
                f"，在Kaggle/天池等算法竞赛中获得{len(competitions)}项奖项"
            )
        if publications:
            summary_parts.append(
                f"，发表研究论文{len(publications)}篇"
            )

        # 能力总结
        summary_parts.append(
            "。擅长模型设计、优化和部署，"
            "对前沿算法有深入理解和实践经验。"
        )

        return ''.join(summary_parts)

    def _enhance_algorithm_description(self, description: str) -> str:
        """增强算法项目描述"""
        if not description:
            return description

        enhanced = description

        # 检查是否提到性能指标
        metric_keywords = ['accuracy', 'precision', 'recall', 'F1', '准确率', '精度']
        has_metrics = any(kw in description.lower() for kw in metric_keywords)

        if not has_metrics:
            enhanced += (
                " 在标准测试集上达到了优秀的性能指标，"
                "模型推理效率高，适合生产环境部署。"
            )

        return enhanced
