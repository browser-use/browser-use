"""
Standalone init command for browser-use template generation.

This module provides a minimal command-line interface for generating
browser-use templates without requiring heavy TUI dependencies.
"""

import json
import sys
from pathlib import Path
from urllib import request
from urllib.error import URLError

import click
from InquirerPy.base.control import Choice
from InquirerPy.prompts.list import ListPrompt
from InquirerPy.utils import InquirerPyStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Hardcoded template metadata (fallback if GitHub fetch fails)
FALLBACK_TEMPLATES = {
	'default': {
		'file': 'default_template.py',
		'description': 'Simplest setup - capable of any web task with minimal configuration',
	},
	'advanced': {
		'file': 'advanced_template.py',
		'description': 'All configuration options shown with defaults',
	},
	'tools': {
		'file': 'tools_template.py',
		'description': 'Custom tool example - extend agent capabilities with your own functions',
	},
	'shopping': {
		'file': 'shopping/main.py',
		'description': 'E-commerce automation with structured output (Pydantic models)',
	},
	'job-application': {
		'file': 'job-application/main.py',
		'description': 'Automated job application form submission with resume upload',
	},
}

# Export for backward compatibility with cli.py
INIT_TEMPLATES = FALLBACK_TEMPLATES

# Rich console for styled output
console = Console()

# GitHub template repository URL (for runtime fetching)
TEMPLATE_REPO_URL = 'https://raw.githubusercontent.com/browser-use/template-library/main'


def _fetch_template_list() -> dict[str, dict[str, str]] | None:
	"""
	Fetch template list from GitHub templates.json.

	Returns template dict if successful, None if failed.
	"""
	try:
		url = f'{TEMPLATE_REPO_URL}/templates.json'
		with request.urlopen(url, timeout=5) as response:
			data = response.read().decode('utf-8')
			return json.loads(data)
	except (URLError, TimeoutError, json.JSONDecodeError, Exception):
		return None


def _get_template_list() -> dict[str, dict[str, str]]:
	"""
	Get template list - tries GitHub first, falls back to hardcoded.
	"""
	templates = _fetch_template_list()
	if templates is not None:
		return templates
	return FALLBACK_TEMPLATES


def _fetch_from_github(file_path: str) -> str | None:
	"""
	Fetch template file from GitHub.

	Returns file content if successful, None if failed.
	"""
	try:
		url = f'{TEMPLATE_REPO_URL}/{file_path}'
		with request.urlopen(url, timeout=5) as response:
			return response.read().decode('utf-8')
	except (URLError, TimeoutError, Exception):
		return None


def _fetch_binary_from_github(file_path: str) -> bytes | None:
	"""
	Fetch binary file from GitHub.

	Returns file content if successful, None if failed.
	"""
	try:
		url = f'{TEMPLATE_REPO_URL}/{file_path}'
		with request.urlopen(url, timeout=5) as response:
			return response.read()
	except (URLError, TimeoutError, Exception):
		return None


def _get_template_content(file_path: str) -> str:
	"""
	Get template file content from GitHub.

	Raises exception if fetch fails.
	"""
	content = _fetch_from_github(file_path)

	if content is not None:
		return content

	raise FileNotFoundError(f'Could not fetch template from GitHub: {file_path}')


# InquirerPy style for template selection (browser-use orange theme)
inquirer_style = InquirerPyStyle(
	{
		'pointer': '#fe750e bold',
		'highlighted': '#fe750e bold',
		'question': 'bold',
		'answer': '#fe750e bold',
		'questionmark': '#fe750e bold',
	}
)


def _write_init_file(output_path: Path, content: str, force: bool = False) -> bool:
	"""Write content to a file, with safety checks."""
	# Check if file already exists
	if output_path.exists() and not force:
		console.print(f'[yellow]⚠[/yellow]  File already exists: [cyan]{output_path}[/cyan]')
		if not click.confirm('Overwrite?', default=False):
			console.print('[red]✗[/red] Cancelled')
			return False

	# Ensure parent directory exists
	output_path.parent.mkdir(parents=True, exist_ok=True)

	# Write file
	try:
		output_path.write_text(content, encoding='utf-8')
		return True
	except Exception as e:
		console.print(f'[red]✗[/red] Error writing file: {e}')
		return False


@click.command('browser-use-init')
@click.option(
	'--template',
	'-t',
	type=str,
	help='Template to use',
)
@click.option(
	'--output',
	'-o',
	type=click.Path(),
	help='Output file path (default: browser_use_<template>.py)',
)
@click.option(
	'--force',
	'-f',
	is_flag=True,
	help='Overwrite existing files without asking',
)
@click.option(
	'--list',
	'-l',
	'list_templates',
	is_flag=True,
	help='List available templates',
)
def main(
	template: str | None,
	output: str | None,
	force: bool,
	list_templates: bool,
):
	"""
	Generate a browser-use template file to get started quickly.

	Examples:

	\b
	# Interactive mode - prompts for template selection
	uvx browser-use init
	uvx browser-use init --template

	\b
	# Generate default template
	uvx browser-use init --template default

	\b
	# Generate advanced template with custom filename
	uvx browser-use init --template advanced --output my_script.py

	\b
	# List available templates
	uvx browser-use init --list
	"""

	# Fetch template list at runtime
	INIT_TEMPLATES = _get_template_list()

	# Handle --list flag
	if list_templates:
		console.print('\n[bold]Available templates:[/bold]\n')
		for name, info in INIT_TEMPLATES.items():
			console.print(f'  [#fe750e]{name:12}[/#fe750e] - {info["description"]}')
		console.print()
		return

	# Interactive template selection if not provided
	if not template:
		# Create choices with numbered display
		template_list = list(INIT_TEMPLATES.keys())
		choices = [
			Choice(
				name=f'{i}. {name:12} - {info["description"]}',
				value=name,
			)
			for i, (name, info) in enumerate(INIT_TEMPLATES.items(), 1)
		]

		# Create the prompt
		prompt = ListPrompt(
			message='Select a template:',
			choices=choices,
			default='default',
			style=inquirer_style,
		)

		# Register custom keybindings for instant selection with number keys
		@prompt.register_kb('1')
		def _(event):
			event.app.exit(result=template_list[0])

		@prompt.register_kb('2')
		def _(event):
			event.app.exit(result=template_list[1])

		@prompt.register_kb('3')
		def _(event):
			event.app.exit(result=template_list[2])

		@prompt.register_kb('4')
		def _(event):
			event.app.exit(result=template_list[3])

		@prompt.register_kb('5')
		def _(event):
			event.app.exit(result=template_list[4])

		template = prompt.execute()

		# Handle user cancellation (Ctrl+C)
		if template is None:
			console.print('\n[red]✗[/red] Cancelled')
			sys.exit(1)

	# Template is guaranteed to be set at this point (either from option or prompt)
	assert template is not None

	# Create template directory
	template_dir = Path.cwd() / template
	if template_dir.exists() and not force:
		console.print(f'[yellow]⚠[/yellow]  Directory already exists: [cyan]{template_dir}[/cyan]')
		if not click.confirm('Continue and overwrite files?', default=False):
			console.print('[red]✗[/red] Cancelled')
			sys.exit(1)

	# Create directory
	template_dir.mkdir(parents=True, exist_ok=True)

	# Determine output path
	if output:
	output_path = template_dir / Path(output)
	else:
		output_path = template_dir / 'main.py'

	# Read template file (tries GitHub first, falls back to bundled)
	try:
		template_file = INIT_TEMPLATES[template]['file']
		content = _get_template_content(template_file)
	except Exception as e:
		console.print(f'[red]✗[/red] Error reading template: {e}')
		sys.exit(1)

	# Write file
	if _write_init_file(output_path, content, force):
		console.print(f'\n[green]✓[/green] Created [cyan]{output_path}[/cyan]')

		# Generate additional files for shopping template
		if template == 'shopping':
			# Generate launch_chrome_debug.py
			launcher_path = output_path.parent / 'launch_chrome_debug.py'
			launcher_content = _get_template_content('shopping/launch_chrome_debug.py')
			if _write_init_file(launcher_path, launcher_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{launcher_path.name}[/cyan]')
				# Make executable on Unix systems
				if sys.platform != 'win32':
					import stat

					launcher_path.chmod(launcher_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

			# Generate pyproject.toml
			pyproject_path = output_path.parent / 'pyproject.toml'
			pyproject_content = _get_template_content('shopping/pyproject.toml.template')
			if _write_init_file(pyproject_path, pyproject_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{pyproject_path.name}[/cyan]')

			# Generate .gitignore
			gitignore_path = output_path.parent / '.gitignore'
			gitignore_content = _get_template_content('gitignore.template')
			if _write_init_file(gitignore_path, gitignore_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{gitignore_path.name}[/cyan]')

			# Generate .env.example
			env_example_path = output_path.parent / '.env.example'
			env_example_content = _get_template_content('shopping/.env.example.template')
			if _write_init_file(env_example_path, env_example_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{env_example_path.name}[/cyan]')

			# Generate README.md
			readme_path = output_path.parent / 'README.md'
			readme_content = _get_template_content('shopping/README.md')
			if _write_init_file(readme_path, readme_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{readme_path.name}[/cyan]')

		elif template == 'job-application':
			# Generate pyproject.toml
			pyproject_path = output_path.parent / 'pyproject.toml'
			pyproject_content = _get_template_content('job-application/pyproject.toml.template')
			if _write_init_file(pyproject_path, pyproject_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{pyproject_path.name}[/cyan]')

			# Generate .gitignore
			gitignore_path = output_path.parent / '.gitignore'
			gitignore_content = _get_template_content('gitignore.template')
			if _write_init_file(gitignore_path, gitignore_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{gitignore_path.name}[/cyan]')

			# Generate .env.example
			env_example_path = output_path.parent / '.env.example'
			env_example_content = _get_template_content('job-application/.env.example.template')
			if _write_init_file(env_example_path, env_example_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{env_example_path.name}[/cyan]')

			# Generate README.md
			readme_path = output_path.parent / 'README.md'
			readme_content = _get_template_content('job-application/README.md')
			if _write_init_file(readme_path, readme_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{readme_path.name}[/cyan]')

			# Copy applicant_data.json
			applicant_data_path = output_path.parent / 'applicant_data.json'
			applicant_data_content = _get_template_content('job-application/applicant_data.json')
			if _write_init_file(applicant_data_path, applicant_data_content, force):
				console.print(f'[green]✓[/green] Created [cyan]{applicant_data_path.name}[/cyan]')

			# Copy example resume PDF (binary file - fetch from GitHub)
			resume_dst = output_path.parent / 'example_resume.pdf'
			if not resume_dst.exists() or force:
				resume_content = _fetch_binary_from_github('job-application/example_resume.pdf')
				if resume_content:
					resume_dst.write_bytes(resume_content)
					console.print(f'[green]✓[/green] Created [cyan]{resume_dst.name}[/cyan]')
				else:
					console.print(f'[yellow]⚠[/yellow]  Could not fetch [cyan]{resume_dst.name}[/cyan] from GitHub')

		# Create a nice panel for next steps
		next_steps = Text()

		if template == 'shopping':
			# Shopping template has different workflow (no uv init needed)
			next_steps.append('\n1. Navigate to project directory:\n', style='bold')
			next_steps.append(f'   cd {template}\n\n', style='dim')
			next_steps.append('2. Set up your API key:\n', style='bold')
			next_steps.append('   cp .env.example .env\n', style='dim')
			next_steps.append('   # Edit .env and add your BROWSER_USE_API_KEY\n', style='dim')
			next_steps.append(
				'   (Get your key at https://cloud.browser-use.com/dashboard/settings?tab=api-keys&new)\n\n',
				style='dim italic',
			)
			next_steps.append('3. Install dependencies:\n', style='bold')
			next_steps.append('   uv sync\n\n', style='dim')
			next_steps.append('4. Launch Chrome with debugging (in a separate terminal):\n', style='bold')
			next_steps.append('   python launch_chrome_debug.py\n', style='dim')
			next_steps.append('   (Run with --help to see options like --profile)\n', style='dim italic')
			next_steps.append('   (Keep this terminal open!)\n\n', style='dim italic')
			next_steps.append('5. Run your script (in a NEW terminal):\n', style='bold')
			next_steps.append(f'   cd {template} && uv run {output_path.name}\n\n', style='dim')
			next_steps.append('📖 See README.md for detailed instructions\n', style='dim italic')
		elif template == 'job-application':
			# Job application template workflow
			next_steps.append('\n1. Navigate to project directory:\n', style='bold')
			next_steps.append(f'   cd {template}\n\n', style='dim')
			next_steps.append('2. Set up your API key:\n', style='bold')
			next_steps.append('   cp .env.example .env\n', style='dim')
			next_steps.append('   # Edit .env and add your OPENAI_API_KEY\n', style='dim')
			next_steps.append('   (Get your key at https://platform.openai.com/api-keys)\n\n', style='dim italic')
			next_steps.append('3. Install dependencies:\n', style='bold')
			next_steps.append('   uv sync\n\n', style='dim')
			next_steps.append('4. Customize your data:\n', style='bold')
			next_steps.append('   # Edit applicant_data.json with your information\n', style='dim')
			next_steps.append('   # Replace example_resume.pdf with your resume\n\n', style='dim')
			next_steps.append('5. Run the application:\n', style='bold')
			next_steps.append(f'   uv run {output_path.name} --resume example_resume.pdf\n\n', style='dim')
			next_steps.append('📖 See README.md for customization and troubleshooting\n', style='dim italic')
		else:
			# Default workflow for other templates
			next_steps.append('\n1. Navigate to project directory:\n', style='bold')
			next_steps.append(f'   cd {template}\n\n', style='dim')
			next_steps.append('2. Initialize uv project:\n', style='bold')
			next_steps.append('   uv init\n\n', style='dim')
			next_steps.append('3. Install browser-use:\n', style='bold')
			next_steps.append('   uv add browser-use\n\n', style='dim')
			next_steps.append('4. Set up your API key in .env file or environment:\n', style='bold')
			next_steps.append('   BROWSER_USE_API_KEY=your-key\n', style='dim')
			next_steps.append(
				'   (Get your key at https://cloud.browser-use.com/dashboard/settings?tab=api-keys&new)\n\n',
				style='dim italic',
			)
			next_steps.append('5. Run your script:\n', style='bold')
			next_steps.append(f'   uv run {output_path.name}\n', style='dim')

	console.print(
		Panel(
			next_steps,
			title='[bold]Next steps[/bold]',
			border_style='#fe750e',
			padding=(1, 2),
		)
	)


if __name__ == '__main__':
	main()
