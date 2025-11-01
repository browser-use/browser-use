"""
Standalone init command for browser-use template generation.

This module provides a minimal command-line interface for generating
browser-use templates without requiring heavy TUI dependencies.
"""

import json
import sys
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import URLError

import click
from InquirerPy.base.control import Choice
from InquirerPy.prompts.list import ListPrompt
from InquirerPy.utils import InquirerPyStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Rich console for styled output
console = Console()

# GitHub template repository URL (for runtime fetching)
TEMPLATE_REPO_URL = 'https://raw.githubusercontent.com/browser-use/template-library/main'

# Export for backward compatibility with cli.py
# Templates are fetched at runtime via _get_template_list()
INIT_TEMPLATES: dict[str, Any] = {}


def _fetch_template_list() -> dict[str, Any] | None:
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


def _get_template_list() -> dict[str, Any]:
	"""
	Get template list from GitHub.

	Raises FileNotFoundError if GitHub fetch fails.
	"""
	templates = _fetch_template_list()
	if templates is not None:
		return templates
	raise FileNotFoundError('Could not fetch templates from GitHub. Check your internet connection.')


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
	try:
		INIT_TEMPLATES = _get_template_list()
	except FileNotFoundError as e:
		console.print(f'[red]✗[/red] {e}')
		sys.exit(1)

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

	# Read template file from GitHub
	try:
		template_file = INIT_TEMPLATES[template]['file']
		content = _get_template_content(template_file)
	except Exception as e:
		console.print(f'[red]✗[/red] Error reading template: {e}')
		sys.exit(1)

	# Write file
	if _write_init_file(output_path, content, force):
		console.print(f'\n[green]✓[/green] Created [cyan]{output_path}[/cyan]')

		# Generate additional files if template has a manifest
		if 'files' in INIT_TEMPLATES[template]:
			import stat

			for file_spec in INIT_TEMPLATES[template]['files']:
				source_path = file_spec['source']
				dest_name = file_spec['dest']
				dest_path = output_path.parent / dest_name
				is_binary = file_spec.get('binary', False)
				is_executable = file_spec.get('executable', False)

				# Skip if we already wrote this file (main.py)
				if dest_path == output_path:
					continue

				# Fetch and write file
				try:
					if is_binary:
						file_content = _fetch_binary_from_github(source_path)
						if file_content:
							if not dest_path.exists() or force:
								dest_path.write_bytes(file_content)
								console.print(f'[green]✓[/green] Created [cyan]{dest_name}[/cyan]')
						else:
							console.print(f'[yellow]⚠[/yellow]  Could not fetch [cyan]{dest_name}[/cyan] from GitHub')
					else:
						file_content = _get_template_content(source_path)
						if _write_init_file(dest_path, file_content, force):
							console.print(f'[green]✓[/green] Created [cyan]{dest_name}[/cyan]')
							# Make executable if needed
							if is_executable and sys.platform != 'win32':
								dest_path.chmod(dest_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
				except Exception as e:
					console.print(f'[yellow]⚠[/yellow]  Error generating [cyan]{dest_name}[/cyan]: {e}')

		# Create a nice panel for next steps
		next_steps = Text()

		# Display next steps from manifest if available
		if 'next_steps' in INIT_TEMPLATES[template]:
			steps = INIT_TEMPLATES[template]['next_steps']
			for i, step in enumerate(steps, 1):
				# Handle footer separately (no numbering)
				if 'footer' in step:
					next_steps.append(f'{step["footer"]}\n', style='dim italic')
					continue

				# Step title
				next_steps.append(f'\n{i}. {step["title"]}:\n', style='bold')

				# Step commands
				for cmd in step.get('commands', []):
					# Replace placeholders
					cmd = cmd.replace('{template}', template)
					cmd = cmd.replace('{output}', output_path.name)
					next_steps.append(f'   {cmd}\n', style='dim')

				# Optional note
				if 'note' in step:
					next_steps.append(f'   {step["note"]}\n', style='dim italic')

				next_steps.append('\n')
		else:
			# Default workflow for templates without custom next_steps
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
