"""
模板渲染器

支持将优化后的简历渲染为不同格式：HTML、Markdown、PDF
"""

import re
from pathlib import Path
from typing import Any


class TemplateRenderer:
	"""简历模板渲染器"""

	def __init__(self, template_dir: str | None = None):
		if template_dir:
			self.template_dir = Path(template_dir)
		else:
			self.template_dir = Path(__file__).parent.parent / 'templates'

	def render_to_html(
		self,
		resume_data: dict[str, Any],
		style: str = 'modern',
		output_path: str | None = None
	) -> str:
		"""
		渲染为HTML

		Args:
			resume_data: 简历数据
			style: 模板风格 (modern, classic)
			output_path: 输出路径

		Returns:
			str: HTML内容
		"""
		# 读取模板文件
		template_file = self.template_dir / f'{style}.html'

		if template_file.exists():
			template = template_file.read_text(encoding='utf-8')
			html = self._render_template(template, resume_data)
		else:
			# 如果模板不存在，使用内置生成
			html = self._generate_html(resume_data, style)

		if output_path:
			Path(output_path).write_text(html, encoding='utf-8')

		return html

	def render_to_markdown(
		self,
		resume_data: dict[str, Any],
		output_path: str | None = None
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
		resume_data: dict[str, Any],
		style: str = 'modern',
		output_path: str | None = None
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

			html = self.render_to_html(resume_data, style)

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
			raise ImportError('请安装 weasyprint: pip install weasyprint')

	def _render_template(self, template: str, data: dict[str, Any]) -> str:
		"""使用简单模板引擎渲染"""
		# 处理 {{#if}} 条件
		template = self._process_conditionals(template, data)

		# 处理 {{#each}} 循环
		template = self._process_loops(template, data)

		// 处理简单变量替换
		def replace_var(match: re.Match) -> str:
			key = match.group(1).strip()
			value = self._get_nested_value(data, key)
			return str(value) if value is not None else ''

		template = re.sub(r'\{\{(\w+)\}\}', replace_var, template)

		return template

	def _process_conditionals(self, template: str, data: dict[str, Any]) -> str:
		"""处理条件语句 {{#if var}}...{{/if}}"""
		pattern = r'\{\{#if (\w+)\}\}(.*?)\{\{/if\}\}'

		def replace_conditional(match: re.Match) -> str:
			key = match.group(1)
			content = match.group(2)
			value = self._get_nested_value(data, key)

			# 如果值为真，返回内容，否则返回空
			if value and (not isinstance(value, list) or len(value) > 0):
				# 递归处理内部变量
				return self._render_template(content, data)
			return ''

		return re.sub(pattern, replace_conditional, template, flags=re.DOTALL)

	def _process_loops(self, template: str, data: dict[str, Any]) -> str:
		"""处理循环语句 {{#each var}}...{{/each}}"""
		pattern = r'\{\{#each (\w+)\}\}(.*?)\{\{/each\}\}'

		def replace_loop(match: re.Match) -> str:
			key = match.group(1)
			item_template = match.group(2)
			items = self._get_nested_value(data, key)

			if not isinstance(items, list):
				return ''

			results = []
			for i, item in enumerate(items):
				# 为每个 item 创建上下文
				if isinstance(item, dict):
					item_context = {**data, **item, '@index': i}
				else:
					item_context = {**data, 'this': item, '@index': i}

				# 渲染 item 模板
				rendered = self._render_template(item_template, item_context)
				results.append(rendered)

			return ''.join(results)

		return re.sub(pattern, replace_loop, template, flags=re.DOTALL)

	def _get_nested_value(self, data: dict[str, Any], key: str) -> Any:
		"""获取嵌套值"""
		if '.' in key:
			parts = key.split('.')
			value = data
			for part in parts:
				if isinstance(value, dict):
					value = value.get(part)
				else:
					return None
			return value
		return data.get(key)

	def _generate_html(self, resume_data: dict[str, Any], style: str) -> str:
		"""生成HTML内容（备用方法）"""
		name = resume_data.get('name', '')
		email = resume_data.get('email', '')
		phone = resume_data.get('phone', '')
		summary = resume_data.get('summary', '')
		skills = resume_data.get('skills', [])
		education = resume_data.get('education', [])
		experience = resume_data.get('experience', [])
		projects = resume_data.get('projects', [])

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
        <header class="header">
            <h1 class="name">{name}</h1>
            <div class="contact">
                {f'<span class="email">{email}</span>' if email else ''}
                {f'<span class="phone">{phone}</span>' if phone else ''}
            </div>
        </header>

        {f'''
        <section class="section summary">
            <h2 class="section-title">个人总结</h2>
            <p class="summary-text">{summary}</p>
        </section>
        ''' if summary else ''}

        {f'''
        <section class="section skills">
            <h2 class="section-title">技能</h2>
            <div class="skills-list">
                {', '.join(f'<span class="skill-tag">{skill}</span>' for skill in skills)}
            </div>
        </section>
        ''' if skills else ''}

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

	def _generate_markdown(self, resume_data: dict[str, Any]) -> str:
		"""生成Markdown内容"""
		lines = []

		name = resume_data.get('name', '')
		lines.append(f'# {name}')
		lines.append('')

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

		summary = resume_data.get('summary', '')
		if summary:
			lines.append('## 个人总结')
			lines.append('')
			lines.append(summary)
			lines.append('')

		skills = resume_data.get('skills', [])
		if skills:
			lines.append('## 技能')
			lines.append('')
			for skill in skills:
				lines.append(f'- {skill}')
			lines.append('')

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
					line-height: 1.6; color: #333;
					max-width: 800px; margin: 0 auto; padding: 2rem;
				}
				.header { border-bottom: 2px solid #2563eb; padding-bottom: 1rem; margin-bottom: 1.5rem; }
				.name { font-size: 2rem; color: #1e40af; margin-bottom: 0.5rem; }
				.contact { color: #666; font-size: 0.9rem; }
				.contact span { margin-right: 1rem; }
				.section { margin-bottom: 1.5rem; }
				.section-title { font-size: 1.2rem; color: #2563eb; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.3rem; margin-bottom: 0.8rem; }
				.skills-list { display: flex; flex-wrap: wrap; gap: 0.5rem; }
				.skill-tag { background: #dbeafe; color: #1e40af; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.85rem; }
				.experience-item, .project-item, .education-item { margin-bottom: 1rem; }
			''',
			'classic': '''
				* { margin: 0; padding: 0; box-sizing: border-box; }
				body { font-family: Georgia, serif; line-height: 1.6; color: #222; max-width: 800px; margin: 0 auto; padding: 2rem; }
				.header { text-align: center; margin-bottom: 2rem; }
				.name { font-size: 2rem; font-weight: normal; text-transform: uppercase; letter-spacing: 2px; }
				.section-title { font-size: 1rem; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #ccc; margin: 1.5rem 0 1rem; }
			'''
		}

		return styles.get(style, styles['modern'])

	def preview_changes(
		self,
		original: dict[str, Any],
		optimized: dict[str, Any],
		changes: list[dict[str, Any]]
	) -> str:
		"""
		生成变更预览

		Args:
			original: 原始简历
			optimized: 优化后的简历
			changes: 变更记录

		Returns:
			str: HTML预览
		"""
		html = '''<!DOCTYPE html>
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
        <div class="change-rationale">原因: {change.get('reason', '')}</div>
    </div>
'''

		html += '</body></html>'
		return html
