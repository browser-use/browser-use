"""
测试 Pydantic 模型
"""

import pytest

from ..views import (
    ResumeData,
    JobRequirement,
    Education,
    Experience,
    Project,
    OptimizationChange,
)


class TestResumeData:
    def test_create_resume(self):
        """测试创建简历数据"""
        resume = ResumeData(
            name="张三",
            email="zhangsan@example.com",
            phone="13800138000",
            skills=["Python", "Java"],
        )

        assert resume.name == "张三"
        assert resume.email == "zhangsan@example.com"
        assert resume.skills == ["Python", "Java"]

    def test_resume_with_education(self):
        """测试带教育经历的简历"""
        edu = Education(
            institution="清华大学",
            degree="本科",
            field="计算机科学"
        )

        resume = ResumeData(
            name="李四",
            education=[edu]
        )

        assert len(resume.education) == 1
        assert resume.education[0].institution == "清华大学"

    def test_resume_to_dict(self):
        """测试转换为字典"""
        resume = ResumeData(
            name="王五",
            email="wangwu@example.com"
        )

        data = resume.to_dict()
        assert data["name"] == "王五"
        assert data["email"] == "wangwu@example.com"


class TestJobRequirement:
    def test_create_job(self):
        """测试创建岗位需求"""
        job = JobRequirement(
            title="后端工程师",
            company="字节跳动",
            required_skills=["Java", "Spring"],
            preferred_skills=["Redis", "Kafka"]
        )

        assert job.title == "后端工程师"
        assert job.company == "字节跳动"
        assert "Java" in job.required_skills


class TestOptimizationChange:
    def test_change_with_alias(self):
        """测试使用别名创建变更记录"""
        change = OptimizationChange(
            change_type="test_change",
            description="测试变更",
            reason="测试原因"
        )

        assert change.change_type == "test_change"
        # 测试序列化时使用别名
        data = change.model_dump(by_alias=True)
        assert data["type"] == "test_change"
