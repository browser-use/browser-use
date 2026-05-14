"""
测试简历优化器
"""

import pytest

from ..optimizer import ResumeOptimizer, OptimizationStyle
from ..views import ResumeData, JobRequirement, Project


class TestResumeOptimizer:
    @pytest.fixture
    def optimizer(self):
        return ResumeOptimizer()

    @pytest.fixture
    def sample_resume(self):
        return ResumeData(
            name="测试用户",
            email="test@example.com",
            skills=["Python", "Java", "Machine Learning"],
            projects=[
                Project(
                    name="测试项目",
                    description="这是一个测试项目描述"
                )
            ]
        )

    @pytest.fixture
    def sample_job(self):
        return JobRequirement(
            title="算法工程师",
            company="测试公司",
            required_skills=["Python", "Machine Learning"],
            preferred_skills=["Deep Learning", "TensorFlow"]
        )

    def test_calculate_match_score(self, optimizer, sample_resume, sample_job):
        """测试匹配分数计算"""
        score = optimizer._calculate_match_score(sample_resume, sample_job)

        # 应该匹配 Python 和 Machine Learning (2个必需技能)
        # Python (2分) + Machine Learning (2分) = 4分
        # 总分 4分，所以应该是 100%
        assert score == 100.0

    def test_calculate_match_score_partial(self, optimizer):
        """测试部分匹配"""
        resume = ResumeData(
            name="测试",
            skills=["Python"]  # 只有 Python，没有 Machine Learning
        )

        job = JobRequirement(
            title="测试",
            company="测试",
            required_skills=["Python", "Machine Learning"],
        )

        score = optimizer._calculate_match_score(resume, job)
        # 只匹配了 1/2 的必需技能，应该是 50%
        assert score == 50.0

    def test_prioritize_skills(self, optimizer):
        """测试技能排序"""
        skills = ["Java", "Python", "Spring", "Redis"]
        priority = ["Python", "Redis"]

        result = optimizer._prioritize_skills(skills, priority)

        # Python 和 Redis 应该排在前面
        assert result[0] == "Python"
        assert result[1] == "Redis"
        assert "Java" in result[2:]
        assert "Spring" in result[2:]

    def test_is_research_project(self, optimizer):
        """测试判断研究项目"""
        project_with_paper = Project(
            name="研究项目",
            description="发表论文关于深度学习的paper"
        )

        project_normal = Project(
            name="普通项目",
            description="开发一个电商网站"
        )

        assert optimizer._is_research_project(project_with_paper) is True
        assert optimizer._is_research_project(project_normal) is False

    @pytest.mark.asyncio
    async def test_optimize_resume(self, optimizer, sample_resume, sample_job):
        """测试简历优化"""
        result = await optimizer.optimize(
            sample_resume,
            sample_job,
            OptimizationStyle.ALGORITHM
        )

        assert result.success is True
        assert result.match_score is not None
        assert isinstance(result.changes, list)
        assert isinstance(result.suggestions, list)

    def test_deep_copy_resume(self, optimizer, sample_resume):
        """测试简历深拷贝"""
        copied = optimizer._deep_copy_resume(sample_resume)

        assert copied.name == sample_resume.name
        assert copied is not sample_resume  # 应该是不同对象


class TestOptimizationStyle:
    def test_style_enum_values(self):
        """测试优化风格枚举值"""
        assert OptimizationStyle.BIG_TECH.value == "big_tech"
        assert OptimizationStyle.RESEARCH.value == "research"
        assert OptimizationStyle.PRODUCT.value == "product"
        assert OptimizationStyle.ALGORITHM.value == "algorithm"
        assert OptimizationStyle.BACKEND.value == "backend"
