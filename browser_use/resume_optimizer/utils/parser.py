"""
简历解析器

支持从多种格式解析简历：PDF、Word、Markdown、HTML
"""

import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedResume:
    """解析后的简历数据"""
    name: str
    email: str
    phone: str
    education: List[Dict[str, Any]]
    skills: List[str]
    projects: List[Dict[str, Any]]
    experience: List[Dict[str, Any]]
    summary: Optional[str] = None
    publications: Optional[List[Dict[str, Any]]] = None
    competitions: Optional[List[Dict[str, Any]]] = None
    raw_text: Optional[str] = None


class ResumeParser:
    """简历解析器"""

    def __init__(self):
        self.email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        self.phone_pattern = re.compile(r'(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?')

    def parse(self, file_path: str) -> ParsedResume:
        """
        解析简历文件

        Args:
            file_path: 简历文件路径

        Returns:
            ParsedResume: 解析后的简历数据
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == '.pdf':
            return self._parse_pdf(file_path)
        elif suffix in ['.doc', '.docx']:
            return self._parse_word(file_path)
        elif suffix in ['.md', '.markdown']:
            return self._parse_markdown(file_path)
        elif suffix in ['.html', '.htm']:
            return self._parse_html(file_path)
        elif suffix == '.txt':
            return self._parse_text(file_path)
        elif suffix == '.json':
            return self._parse_json(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")

    def parse_from_text(self, text: str) -> ParsedResume:
        """从文本解析简历"""
        return self._extract_structured_data(text)

    def _parse_pdf(self, file_path: str) -> ParsedResume:
        """解析PDF简历"""
        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            return self._extract_structured_data(text)
        except ImportError:
            raise ImportError("请安装 PyPDF2: pip install PyPDF2")

    def _parse_word(self, file_path: str) -> ParsedResume:
        """解析Word简历"""
        try:
            import docx
            doc = docx.Document(file_path)
            text = '\n'.join(paragraph.text for paragraph in doc.paragraphs)
            return self._extract_structured_data(text)
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")

    def _parse_markdown(self, file_path: str) -> ParsedResume:
        """解析Markdown简历"""
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        return self._extract_structured_data(text)

    def _parse_html(self, file_path: str) -> ParsedResume:
        """解析HTML简历"""
        try:
            from bs4 import BeautifulSoup
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
            text = soup.get_text(separator='\n')
            return self._extract_structured_data(text)
        except ImportError:
            raise ImportError("请安装 beautifulsoup4: pip install beautifulsoup4")

    def _parse_text(self, file_path: str) -> ParsedResume:
        """解析纯文本简历"""
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        return self._extract_structured_data(text)

    def _parse_json(self, file_path: str) -> ParsedResume:
        """解析JSON格式简历"""
        import json
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ParsedResume(
            name=data.get('name', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            education=data.get('education', []),
            skills=data.get('skills', []),
            projects=data.get('projects', []),
            experience=data.get('experience', []),
            summary=data.get('summary'),
            publications=data.get('publications'),
            competitions=data.get('competitions'),
            raw_text=json.dumps(data, ensure_ascii=False)
        )

    def _extract_structured_data(self, text: str) -> ParsedResume:
        """从文本中提取结构化数据"""
        # 提取邮箱
        email_match = self.email_pattern.search(text)
        email = email_match.group(0) if email_match else ''

        # 提取电话
        phone_match = self.phone_pattern.search(text)
        phone = phone_match.group(0) if phone_match else ''

        # 提取姓名（通常在第一行）
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        name = lines[0] if lines and not any(kw in lines[0].lower() for kw in ['resume', 'cv', '简历']) else ''

        # 提取技能
        skills = self._extract_skills(text)

        # 提取教育经历
        education = self._extract_education(text)

        # 提取项目经历
        projects = self._extract_projects(text)

        # 提取工作经历
        experience = self._extract_experience(text)

        # 提取个人总结
        summary = self._extract_summary(text)

        return ParsedResume(
            name=name,
            email=email,
            phone=phone,
            education=education,
            skills=skills,
            projects=projects,
            experience=experience,
            summary=summary,
            raw_text=text
        )

    def _extract_skills(self, text: str) -> List[str]:
        """提取技能列表"""
        # 常见技术关键词
        tech_keywords = [
            'Python', 'Java', 'Go', 'C++', 'JavaScript', 'TypeScript',
            'React', 'Vue', 'Angular', 'Node.js', 'Django', 'Flask',
            'Spring', 'MySQL', 'PostgreSQL', 'MongoDB', 'Redis',
            'Docker', 'Kubernetes', 'AWS', 'Azure', 'GCP',
            'Machine Learning', 'Deep Learning', 'TensorFlow', 'PyTorch',
            'Git', 'Linux', 'REST API', 'GraphQL', 'Microservices'
        ]

        found_skills = []
        text_lower = text.lower()

        for skill in tech_keywords:
            if skill.lower() in text_lower:
                found_skills.append(skill)

        return found_skills

    def _extract_education(self, text: str) -> List[Dict[str, Any]]:
        """提取教育经历"""
        education = []

        # 简单的模式匹配
        edu_patterns = [
            r'(Bachelor|Master|Ph\.?D|本科|硕士|博士).*?(?:in|of|专业)?\s*([^\n]+)',
            r'([^\n]+University|大学|学院)[^\n]*',
        ]

        for pattern in edu_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                education.append({
                    'degree': match.group(1) if match.groups() else 'Unknown',
                    'field': match.group(2) if len(match.groups()) > 1 else '',
                    'institution': match.group(0)
                })

        return education

    def _extract_projects(self, text: str) -> List[Dict[str, Any]]:
        """提取项目经历"""
        projects = []

        # 查找项目部分
        project_section = re.search(
            r'(?:Projects?|项目经历|项目经验)[\s\S]*?(?=(?:Experience|工作经历|Education|教育背景|$))',
            text,
            re.IGNORECASE
        )

        if project_section:
            section_text = project_section.group(0)
            # 简单提取项目条目
            project_items = re.split(r'\n(?=[•\-\*]|\d+\.)', section_text)

            for item in project_items[1:]:  # 跳过标题
                if len(item.strip()) > 10:
                    projects.append({
                        'name': item.strip().split('\n')[0][:50],
                        'description': item.strip()
                    })

        return projects

    def _extract_experience(self, text: str) -> List[Dict[str, Any]]:
        """提取工作经历"""
        experience = []

        # 查找工作经历部分
        exp_section = re.search(
            r'(?:Experience|Work Experience|工作经历)[\s\S]*?(?=(?:Education|教育背景|Projects|项目|$))',
            text,
            re.IGNORECASE
        )

        if exp_section:
            section_text = exp_section.group(0)
            # 简单提取经历条目
            exp_items = re.split(r'\n(?=[•\-\*]|\d{4})', section_text)

            for item in exp_items[1:]:  # 跳过标题
                if len(item.strip()) > 10:
                    experience.append({
                        'company': item.strip().split('\n')[0][:50],
                        'description': item.strip()
                    })

        return experience

    def _extract_summary(self, text: str) -> Optional[str]:
        """提取个人总结"""
        # 查找Summary或Objective部分
        summary_match = re.search(
            r'(?:Summary|Objective|Profile|About|个人总结|求职意向)[\s\S]*?(?=\n\n|\n[A-Z]|$)',
            text,
            re.IGNORECASE
        )

        if summary_match:
            summary = summary_match.group(0).strip()
            # 移除标题
            for title in ['Summary', 'Objective', 'Profile', 'About', '个人总结', '求职意向']:
                summary = re.sub(f'^{title}[:\s]*', '', summary, flags=re.IGNORECASE)
            return summary.strip() if len(summary) > 20 else None

        return None

    def to_json(self, parsed_resume: ParsedResume) -> Dict[str, Any]:
        """将解析结果转为JSON格式"""
        return {
            'name': parsed_resume.name,
            'email': parsed_resume.email,
            'phone': parsed_resume.phone,
            'summary': parsed_resume.summary,
            'education': parsed_resume.education,
            'skills': parsed_resume.skills,
            'projects': parsed_resume.projects,
            'experience': parsed_resume.experience,
            'publications': parsed_resume.publications or [],
            'competitions': parsed_resume.competitions or [],
        }
