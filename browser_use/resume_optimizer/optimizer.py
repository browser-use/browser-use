"""
简历优化核心逻辑
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class OptimizationStyle(Enum):
    """简历优化风格"""
    BIG_TECH = "big_tech"      # 大厂风
    RESEARCH = "research"      # 科研风
    PRODUCT = "product"        # 产品风
    ALGORITHM = "algorithm"    # 算法岗风
    BACKEND = "backend"        # 后端岗风


@dataclass
class JobRequirement:
    """岗位需求"""
    title: str
    company: str
    required_skills: List[str]
    preferred_skills: List[str]
    responsibilities: List[str]
    qualifications: List[str]
    salary_range: Optional[str] = None
    location: Optional[str] = None


@dataclass
class ResumeData:
    """简历数据结构"""
    name: str
    email: str
    phone: str
    education: List[Dict[str, Any]]
    skills: List[str]
    projects: List[Dict[str, Any]]
    experience: List[Dict[str, Any]]
    summary: Optional[str] = None


@dataclass
class OptimizationResult:
    """优化结果"""
    original_resume: ResumeData
    optimized_resume: ResumeData
    style: OptimizationStyle
    changes: List[Dict[str, Any]]
    match_score: float
    suggestions: List[str]


class ResumeOptimizer:
    """
    简历优化器

    根据目标岗位需求，使用不同风格模板优化简历
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.style_handlers = {
            OptimizationStyle.BIG_TECH: self._apply_big_tech_style,
            OptimizationStyle.RESEARCH: self._apply_research_style,
            OptimizationStyle.PRODUCT: self._apply_product_style,
            OptimizationStyle.ALGORITHM: self._apply_algorithm_style,
            OptimizationStyle.BACKEND: self._apply_backend_style,
        }

    def optimize(
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
        optimized_resume, changes = handler(resume, job)

        # 计算优化后匹配度
        new_score = self._calculate_match_score(optimized_resume, job)

        # 生成建议
        suggestions = self._generate_suggestions(resume, job, style)

        return OptimizationResult(
            original_resume=resume,
            optimized_resume=optimized_resume,
            style=style,
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
            if any(s.lower() in [rs.lower() for rs in resume.skills] for s in skill.split('/')):
                score += 2

        # 优先技能匹配
        for skill in job.preferred_skills:
            total += 1
            if any(s.lower() in [rs.lower() for rs in resume.skills] for s in skill.split('/')):
                score += 1

        return (score / total * 100) if total > 0 else 0.0

    def _apply_big_tech_style(
        self,
        resume: ResumeData,
        job: JobRequirement
    ) -> tuple[ResumeData, List[Dict[str, Any]]]:
        """
        大厂风格优化
        - 强调技术深度和系统设计
        - 量化成果（用户量、性能提升、营收等）
        - 突出协作和影响力
        """
        changes = []
        optimized = self._deep_copy_resume(resume)

        # 优化项目描述 - 强调量化和影响力
        for i, project in enumerate(optimized.projects):
            if 'description' in project:
                old_desc = project['description']
                new_desc = self._add_metrics_emphasis(old_desc)
                if old_desc != new_desc:
                    project['description'] = new_desc
                    changes.append({
                        'type': 'project_enhancement',
                        'index': i,
                        'field': 'description',
                        'reason': '大厂风格：强调量化成果和业务影响'
                    })

        # 优化技能列表 - 匹配岗位需求
        skill_changes = self._optimize_skills_for_job(optimized.skills, job)
        if skill_changes:
            optimized.skills = skill_changes['optimized']
            changes.append({
                'type': 'skills_optimization',
                'added': skill_changes['added'],
                'prioritized': skill_changes['prioritized'],
                'reason': '大厂风格：优先展示岗位相关技能'
            })

        return optimized, changes

    def _apply_research_style(
        self,
        resume: ResumeData,
        job: JobRequirement
    ) -> tuple[ResumeData, List[Dict[str, Any]]]:
        """
        科研风格优化
        - 强调论文、专利、研究成果
        - 突出技术创新和学术贡献
        - 展示研究方法和实验设计
        """
        changes = []
        optimized = self._deep_copy_resume(resume)

        # 添加/优化研究经历部分
        research_projects = [p for p in optimized.projects if self._is_research_project(p)]
        if research_projects:
            changes.append({
                'type': 'research_highlight',
                'count': len(research_projects),
                'reason': '科研风格：突出研究项目和学术成果'
            })

        return optimized, changes

    def _apply_product_style(
        self,
        resume: ResumeData,
        job: JobRequirement
    ) -> tuple[ResumeData, List[Dict[str, Any]]]:
        """
        产品风格优化
        - 强调用户思维和产品sense
        - 突出数据驱动决策
        - 展示跨部门协作能力
        """
        changes = []
        optimized = self._deep_copy_resume(resume)

        # 优化项目描述 - 强调产品思维
        for i, project in enumerate(optimized.projects):
            if 'description' in project:
                old_desc = project['description']
                new_desc = self._add_product_emphasis(old_desc)
                if old_desc != new_desc:
                    project['description'] = new_desc
                    changes.append({
                        'type': 'product_focus',
                        'index': i,
                        'reason': '产品风格：强调用户思维和数据驱动'
                    })

        return optimized, changes

    def _apply_algorithm_style(
        self,
        resume: ResumeData,
        job: JobRequirement
    ) -> tuple[ResumeData, List[Dict[str, Any]]]:
        """
        算法岗风格优化
        - 强调算法能力和模型优化
        - 突出竞赛成绩和开源贡献
        - 展示数学和统计基础
        """
        changes = []
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
            changes.append({
                'type': 'skills_reorder',
                'reason': '算法岗风格：算法技能前置'
            })

        return optimized, changes

    def _apply_backend_style(
        self,
        resume: ResumeData,
        job: JobRequirement
    ) -> tuple[ResumeData, List[Dict[str, Any]]]:
        """
        后端岗风格优化
        - 强调系统设计和架构能力
        - 突出高并发、高可用经验
        - 展示数据库和中间件熟练度
        """
        changes = []
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
            changes.append({
                'type': 'skills_reorder',
                'reason': '后端岗风格：后端技能前置'
            })

        return optimized, changes

    def _deep_copy_resume(self, resume: ResumeData) -> ResumeData:
        """深拷贝简历数据"""
        import copy
        return copy.deepcopy(resume)

    def _add_metrics_emphasis(self, description: str) -> str:
        """添加量化指标强调"""
        # 这里可以集成LLM来增强描述
        return description

    def _add_product_emphasis(self, description: str) -> str:
        """添加产品思维强调"""
        return description

    def _is_research_project(self, project: Dict[str, Any]) -> bool:
        """判断是否为研究项目"""
        research_keywords = ['paper', 'publication', 'research', '算法', '模型']
        desc = project.get('description', '').lower()
        return any(kw in desc for kw in research_keywords)

    def _optimize_skills_for_job(
        self,
        skills: List[str],
        job: JobRequirement
    ) -> Optional[Dict[str, Any]]:
        """根据岗位优化技能列表"""
        # 实现技能优化逻辑
        return None

    def _prioritize_skills(
        self,
        skills: List[str],
        priority_skills: List[str]
    ) -> List[str]:
        """将优先技能前置"""
        prioritized = []
        others = []

        for skill in skills:
            if any(ps.lower() in skill.lower() for ps in priority_skills):
                prioritized.append(skill)
            else:
                others.append(skill)

        return prioritized + others

    def _generate_suggestions(
        self,
        resume: ResumeData,
        job: JobRequirement,
        style: OptimizationStyle
    ) -> List[str]:
        """生成优化建议"""
        suggestions = []

        # 检查技能匹配度
        missing_required = []
        for skill in job.required_skills:
            if not any(skill.lower() in s.lower() for s in resume.skills):
                missing_required.append(skill)

        if missing_required:
            suggestions.append(f"建议补充以下必需技能的学习或项目经验: {', '.join(missing_required)}")

        # 风格特定建议
        if style == OptimizationStyle.BIG_TECH:
            suggestions.append("大厂面试重视系统设计，建议在项目描述中增加架构图和性能数据")
        elif style == OptimizationStyle.ALGORITHM:
            suggestions.append("算法岗建议补充LeetCode刷题记录或ACM竞赛成绩")

        return suggestions
