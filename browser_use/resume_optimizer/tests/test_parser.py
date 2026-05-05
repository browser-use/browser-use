"""
测试简历解析器
"""

import json
import tempfile
from pathlib import Path

import pytest

from ..utils.parser import ResumeParser, ParsedResume


class TestResumeParser:
    @pytest.fixture
    def parser(self):
        return ResumeParser()

    def test_extract_skills(self, parser):
        """测试技能提取"""
        text = "精通 Python、Java 和 Machine Learning，熟悉 Docker 和 Kubernetes"

        skills = parser._extract_skills(text)

        assert "Python" in skills
        assert "Java" in skills
        assert "Machine Learning" in skills
        assert "Docker" in skills
        assert "Kubernetes" in skills

    def test_extract_skills_avoid_false_positive(self, parser):
        """测试避免误判 - JavaScript 不应该匹配 Java"""
        text = "使用 JavaScript 开发前端应用"

        skills = parser._extract_skills(text)

        # 应该匹配 JavaScript，不应该匹配 Java
        assert "JavaScript" in skills
        assert "Java" not in skills

    def test_extract_email(self, parser):
        """测试邮箱提取"""
        text = "联系邮箱: zhangsan@example.com 或 test+label@gmail.com"

        match = parser.email_pattern.search(text)
        assert match is not None
        assert match.group(0) == "zhangsan@example.com"

    def test_extract_phone(self, parser):
        """测试电话提取"""
        text = "联系电话: 13800138000"

        match = parser.phone_pattern.search(text)
        assert match is not None
        assert "13800138000" in match.group(0)

    def test_parse_json_file(self, parser, tmp_path):
        """测试解析 JSON 文件"""
        resume_data = {
            "name": "张三",
            "email": "zhangsan@example.com",
            "skills": ["Python", "Java"],
            "education": [{"institution": "清华大学", "degree": "本科"}]
        }

        json_file = tmp_path / "resume.json"
        json_file.write_text(json.dumps(resume_data), encoding="utf-8")

        result = parser.parse(str(json_file))

        assert result.name == "张三"
        assert result.email == "zhangsan@example.com"
        assert result.skills == ["Python", "Java"]

    def test_parse_text_file(self, parser, tmp_path):
        """测试解析纯文本文件"""
        text_content = """
李四
邮箱: lisi@example.com
电话: 13900139000

技能: Python, Java, Spring

教育背景
北京大学 本科

项目经历
订单系统 - 高并发处理
"""

        txt_file = tmp_path / "resume.txt"
        txt_file.write_text(text_content, encoding="utf-8")

        result = parser.parse(str(txt_file))

        assert result.name == "李四"
        assert result.email == "lisi@example.com"
        assert "Python" in result.skills

    def test_parse_nonexistent_file(self, parser):
        """测试解析不存在的文件"""
        with pytest.raises(FileNotFoundError):
            parser.parse("/path/to/nonexistent/file.pdf")

    def test_to_json(self, parser):
        """测试转换为 JSON"""
        parsed = ParsedResume(
            name="测试",
            email="test@example.com",
            skills=["Python"]
        )

        result = parser.to_json(parsed)

        assert result["name"] == "测试"
        assert result["email"] == "test@example.com"
        assert result["skills"] == ["Python"]
