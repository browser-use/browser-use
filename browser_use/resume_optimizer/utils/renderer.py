"""
模板渲染器

支持将优化后的简历渲染为不同格式：HTML、Markdown、PDF
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime


class TemplateRenderer:
    """简历模板渲染器"""

    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = Path(template_dir) if template_dir else Path(__file__).parent.parent / 'templates'

    def render_to_html(
        self,
        resume_data: Dict[str, Any],
        style: str = 'modern',
        output_path: Optional[str] = None
    ) -> str:
        """
        渲染为HTML

        Args:
            resume_data: 简历数据
            style: 模板风格 (modern, classic, minimal)
            output_path: 输出路径

        Returns:
            str: HTML内容
        """
        html = self._generate_html(resume_data, style)

        if output_path:
            Path(output_path).write_text(html, encoding='utf-8')

        return html

    def render_to_markdown(
        self,
        resume_data: Dict[str, Any],
        output_path: Optional[str] = None
    ) -> str:
        """
        渲染为Markdown

        Args:
            resume_data: 简历数据
            output_path: 输出路径

        Returns:
            str: Markdown内容
        """
        md = self._generate_markdown(resume_data)

        if output_path:
            Path(output_path).write_text(md, encoding='utf-8')

        return md

    def render_to_pdf(
        self,
        resume_data: Dict[str, Any],
        style: str = 'modern',
        output_path: Optional[str] = None
    ) -> bytes:
        """
        渲染为PDF

        Args:
            resume_data: 简历数据
            style: 模板风格
            output_path: 输出路径

        Returns:
            bytes: PDF内容
        """
        try:
            from weasyprint import HTML, CSS

            html = self._generate_html(resume_data, style)

            # 添加打印样式
            css = '''
                @page { size: A4; margin: 1cm; }
                body { font-size: 10pt; }
            '''

            pdf = HTML(string=html).write_pdf(stylesheets=[CSS(string=css)])

            if output_path:
                Path(output_path).write_bytes(pdf)

            return pdf

        except ImportError:
            raise ImportError("请安装 weasyprint: pip install weasyprint")

    def _generate_html(self, resume_data: Dict[str, Any], style: str) -> str:
        """生成HTML内容"""
        name = resume_data.get('name', '')
        email = resume_data.get('email', '')
        phone = resume_data.get('phone', '')
        summary = resume_data.get('summary', '')
        skills = resume_data.get('skills', [])
        education = resume_data.get('education', [])
        experience = resume_data.get('experience', [])
        projects = resume_data.get('projects', [])

        # 根据风格选择样式
        styles = self._get_styles(style)

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - 简历</title>
    <style>
{styles}
    </style>
</head>
<body>
    <div class="resume">
        <!-- 头部信息 -->
        <header class="header">
            <h1 class="name">{name}</h1>
            <div class="contact">
                {f'<span class="email">{email}</span>' if email else ''}
                {f'<span class="phone">{phone}</span>' if phone else ''}
            </div>
        </header>

        <!-- 个人总结 -->
        {f'''
        <section class="section summary">
            <h2 class="section-title">个人总结</h2>
            <p class="summary-text">{summary}</p>
        </section>
        ''' if summary else ''}

        <!-- 技能 -->
        {f'''
        <section class="section skills">
            <h2 class="section-title">技能</h2>
            <div class="skills-list">
                {', '.join(f'<span class="skill-tag">{skill}</span>' for skill in skills)}
            </div>
        </section>
        ''' if skills else ''}

        <!-- 工作经历 -->
        {f'''
        <section class="section experience">
            <h2 class="section-title">工作经历</h2>
            {''.join(f"""
            <div class="experience-item">
                <div class="experience-header">
                    <h3 class="company">{exp.get('company', '')}</h3>
                    <span class="duration">{exp.get('duration', '')}</span>
                </div>
                <p class="experience-desc">{exp.get('description', '')}</p>
            </div>
            """ for exp in experience)}
        </section>
        ''' if experience else ''}

        <!-- 项目经历 -->
        {f'''
        <section class="section projects">
            <h2 class="section-title">项目经历</h2>
            {''.join(f"""
            <div class="project-item">
                <h3 class="project-name">{proj.get('name', '')}</h3>
                <p class="project-desc">{proj.get('description', '')}</p>
            </div>
            """ for proj in projects)}
        </section>
        ''' if projects else ''}

        <!-- 教育背景 -->
        {f'''
        <section class="section education">
            <h2 class="section-title">教育背景</h2>
            {''.join(f"""
            <div class="education-item">
                <h3 class="institution">{edu.get('institution', '')}</h3>
                <p class="degree">{edu.get('degree', '')} - {edu.get('field', '')}</p>
            </div>
            """ for edu in education)}
        </section>
        ''' if education else ''}
    </div>
</body>
</html>'''

        return html

    def _generate_markdown(self, resume_data: Dict[str, Any]) -> str:
        """生成Markdown内容"""
        lines = []

        # 标题
        name = resume_data.get('name', '')
        lines.append(f'# {name}')
        lines.append('')

        # 联系方式
        email = resume_data.get('email', '')
        phone = resume_data.get('phone', '')
        contacts = []
        if email:
            contacts.append(f'Email: {email}')
        if phone:
            contacts.append(f'Phone: {phone}')
        if contacts:
            lines.append(' | '.join(contacts))
            lines.append('')

        # 个人总结
        summary = resume_data.get('summary', '')
        if summary:
            lines.append('## 个人总结')
            lines.append('')
            lines.append(summary)
            lines.append('')

        # 技能
        skills = resume_data.get('skills', [])
        if skills:
            lines.append('## 技能')
            lines.append('')
            for skill in skills:
                lines.append(f'- {skill}')
            lines.append('')

        # 工作经历
        experience = resume_data.get('experience', [])
        if experience:
            lines.append('## 工作经历')
            lines.append('')
            for exp in experience:
                company = exp.get('company', '')
                duration = exp.get('duration', '')
                desc = exp.get('description', '')
                lines.append(f'### {company}')
                if duration:
                    lines.append(f'*{duration}*')
                if desc:
                    lines.append(desc)
                lines.append('')

        # 项目经历
        projects = resume_data.get('projects', [])
        if projects:
            lines.append('## 项目经历')
            lines.append('')
            for proj in projects:
                name = proj.get('name', '')
                desc = proj.get('description', '')
                lines.append(f'### {name}')
                if desc:
                    lines.append(desc)
                lines.append('')

        # 教育背景
        education = resume_data.get('education', [])
        if education:
            lines.append('## 教育背景')
            lines.append('')
            for edu in education:
                institution = edu.get('institution', '')
                degree = edu.get('degree', '')
                field = edu.get('field', '')
                lines.append(f'- **{institution}** - {degree} in {field}')
            lines.append('')

        return '\n'.join(lines)

    def _get_styles(self, style: str) -> str:
        """获取CSS样式"""
        styles = {
            'modern': '''
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 2rem;
                }
                .header {
                    border-bottom: 2px solid #2563eb;
                    padding-bottom: 1rem;
                    margin-bottom: 1.5rem;
                }
                .name {
                    font-size: 2rem;
                    color: #1e40af;
                    margin-bottom: 0.5rem;
                }
                .contact {
                    color: #666;
                    font-size: 0.9rem;
                }
                .contact span {
                    margin-right: 1rem;
                }
                .section {
                    margin-bottom: 1.5rem;
                }
                .section-title {
                    font-size: 1.2rem;
                    color: #2563eb;
                    border-bottom: 1px solid #e5e7eb;
                    padding-bottom: 0.3rem;
                    margin-bottom: 0.8rem;
                }
                .skills-list {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.5rem;
                }
                .skill-tag {
                    background: #dbeafe;
                    color: #1e40af;
                    padding: 0.2rem 0.6rem;
                    border-radius: 4px;
                    font-size: 0.85rem;
                }
                .experience-item, .project-item, .education-item {
                    margin-bottom: 1rem;
                }
                .company, .project-name, .institution {
                    font-size: 1.1rem;
                    color: #374151;
                }
                .duration {
                    color: #6b7280;
                    font-size: 0.9rem;
                }
            ''',
            'classic': '''
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: Georgia, serif;
                    line-height: 1.6;
                    color: #222;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 2rem;
                }
                .header {
                    text-align: center;
                    margin-bottom: 2rem;
                }
                .name {
                    font-size: 2rem;
                    font-weight: normal;
                    text-transform: uppercase;
                    letter-spacing: 2px;
                }
                .section-title {
                    font-size: 1rem;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    border-bottom: 1px solid #ccc;
                    margin: 1.5rem 0 1rem;
                }
            ''',
            'minimal': '''
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: system-ui, sans-serif;
                    line-height: 1.5;
                    color: #333;
                    max-width: 700px;
                    margin: 0 auto;
                    padding: 2rem;
                }
                .name { font-size: 1.5rem; font-weight: 600; }
                .section-title {
                    font-size: 0.875rem;
                    text-transform: uppercase;
                    color: #666;
                    margin-top: 1.5rem;
                    margin-bottom: 0.5rem;
                }
            '''
        }

        return styles.get(style, styles['modern'])

    def preview_changes(
        self,
        original: Dict[str, Any],
        optimized: Dict[str, Any],
        changes: List[Dict[str, Any]]
    ) -> str:
        """
        生成变更预览

        Args:
            original: 原始简历
            optimized: 优化后的简历
            changes: 变更记录

        Returns:
            str: 变更预览HTML
        """
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { font-family: system-ui, sans-serif; padding: 2rem; }
                .change-item { margin-bottom: 1rem; padding: 1rem; background: #f3f4f6; border-radius: 8px; }
                .change-type { font-weight: bold; color: #2563eb; }
                .change-desc { color: #666; margin: 0.5rem 0; }
                .change-rationale { font-size: 0.9rem; color: #059669; }
            </style>
        </head>
        <body>
            <h1>简历优化变更记录</h1>
        '''

        for change in changes:
            html += f'''
            <div class="change-item">
                <div class="change-type">{change.get('type', 'Unknown')}</div>
                <div class="change-desc">{change.get('description', '')}</div>
                <div class="change-rationale">原因: {change.get('rationale', '')}</div>
            </div>
            '''

        html += '</body></html>'
        return html
