"""
Standalone init command for browser-use template generation.

This module provides a minimal command-line interface for generating
browser-use templates without requiring heavy TUI dependencies.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import URLError

import click
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.utils import InquirerPyStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Rich console for styled output
console = Console()

# GitHub template repository URL (for runtime fetching)
TEMPLATE_LIBRARY_COMMIT = '36bea3277f4c75b93a7c93b60c3cc4397e5aff77'
TEMPLATE_REPO_URL = f'https://raw.githubusercontent.com/browser-use/template-library/{TEMPLATE_LIBRARY_COMMIT}'

TEMPLATE_MANIFEST_SHA256 = '1de617b7aa7c9f49b9d33c986b1eb4ee7db960423532b2c3fbbb8cbfc8393e5e'
TEMPLATE_FILE_SHA256 = {
	'default_template.py': '2786b926196dcb8cf4e9a37a6fa830a623bcc8c35329bcdac022d36a05897574',
	'advanced_template.py': '4ad638db292622cc3701bd16cfe9476c6dc68c4e4da28be5d40849859c627d38',
	'tools_template.py': '5b3850bbd1e10f62d56199ba03070526b658e1eafa67a73e25e52f041ce8a778',
	'agentmail/email_tools.py': '08b379f4ffe312b556f6d736bd0f4101139dfbcd772154f080c0f117fd9b2120',
	'agentmail/main.py': 'c5ff42dd869dfac8bdec73137362c9e84148a6f669255ac9b28c1cd1417b5fb2',
	'all-openai-jobs/main.py': 'd41d84d2e888e0dd96bae467dc32d2f6fd13065ba26358f73e3d4d2d56c17e60',
	'job-application/main.py': 'b0460ac996e4a376b94b093bc908750d7a2a4b6e71c394d5bead927169d6dfdc',
	'llm-arena/main.py': '11f6e751ee0409a56702eae46ac47d489343a8861406f9d4ff4ee1d028c86739',
	'sandbox/main.py': '562c96d64f23a81c8cc33e0299d174c2bd65b023fd11d348a71c8a33a543980b',
	'scheduler/agents/gmail.py': '10a49bd97eed085bed56c280047c55a7b0502676ffc2a371aa3eefedd375110e',
	'scheduler/agents/x.py': 'c9fdcb87a50c6a46c77beea77b898b541025bc0f91bad7c0a896aab35ba088eb',
	'scheduler/main.py': '45a46a63f98acbc9e8fca7bf94a65b735ffcb4d67f435bc1777115eb9f996e10',
	'shopping/launch_chrome_debug.py': 'a985b6c0c255575455a78999428c60904648151c7093f6287eb03c57fbdf74f9',
	'shopping/main.py': '1e256552217f770d81d5f0f976111a82d8563bb4fede5f5618e05aa820fec7e0',
	'slack/app/main.py': 'fcbabbff8899a520aed014fad155bf8b5a91266c39d60ca855c993a64e0b6d10',
	'slack/app/service.py': 'a6974f20b90390442eec38571d1e22f91c5bb7ecb63ef34d194785b83cd70e60',
}

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
			data = response.read()
		if hashlib.sha256(data).hexdigest() != TEMPLATE_MANIFEST_SHA256:
			raise RuntimeError('Template manifest integrity check failed')
		data = data.decode('utf-8')
		return json.loads(data)
	except (URLError, TimeoutError, json.JSONDecodeError):
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
		expected_hash = TEMPLATE_FILE_SHA256.get(file_path)
		if file_path.endswith('.py'):
			if expected_hash is None:
				raise RuntimeError(f'No integrity metadata for template file: {file_path}')
			actual_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
			if actual_hash != expected_hash:
				raise RuntimeError(f'Template integrity check failed for {file_path}')
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


def _get_terminal_width() -> int:
	"""Get current terminal width in columns."""
	return shutil.get_terminal_size().columns


def _format_choice(name: str, metadata: dict[str, Any], width: int, is_default: bool = False) -> str:
	"""
	Format a template choice with responsive display based on terminal width.

	Styling:
	- Featured templates get [FEATURED] prefix
	- Author name included when width allows (except for default templates)
	- Everything turns orange when highlighted (InquirerPy's built-in behavior)

	Args:
		name: Template name
		metadata: Template metadata (description, featured, author)
		width: Terminal width in columns
		is_default: Whether this is a default template (default, advanced, tools)

	Returns:
		Formatted choice string
	"""
	is_featured = metadata.get('featured', False)
	description = metadata.get('description', '')
	author_name = metadata.get('author', {}).get('name', '') if isinstance(metadata.get('author'), dict) else ''

	# Build the choice string based on terminal width
	if width > 100:
		# Wide: show everything including author (except for default templates)
		if is_featured:
			if author_name:
				return f'[FEATURED] {name} by {author_name} - {description}'
			else:
				return f'[FEATURED] {name} - {description}'
		else:
			# Non-featured templates
			if author_name and not is_default:
				return f'{name} by {author_name} - {description}'
			else:
				return f'{name} - {description}'

	elif width > 60:
		# Medium: show name and description, no author
		if is_featured:
			return f'[FEATURED] {name} - {description}'
		else:
			return f'{name} - {description}'

	else:
		# Narrow: show name only
		return name


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
	except Exception as e:
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
		# Get terminal width for responsive formatting
		width = _get_terminal_width()

		# Separate default and featured templates
		default_template_names = ['default', 'advanced', 'tools']
		featured_templates = [(name, info) for name, info in INIT_TEMPLATES.items() if info.get('featured', False)]
		other_templates = [
			(name, info)
			for name, info in INIT_TEMPLATES.items()
			if name not in default_template_names and not info.get('featured', False)
		]

		# Sort by last_modified_date (most recent first)
		def get_last_modified(item):
			name, info = item
			date_str = (
				info.get('author', {}).get('last_modified_date', '1970-01-01')
				if isinstance(info.get('author'), dict)
				else '1970-01-01'
			)
			return date_str

		# Sort default templates by last modified
		default_templates = [(name, INIT_TEMPLATES[name]) for name in default_template_names if name in INIT_TEMPLATES]
		default_templates.sort(key=get_last_modified, reverse=True)

		# Sort featured and other templates by last modified
		featured_templates.sort(key=get_last_modified, reverse=True)
		other_templates.sort(key=get_last_modified, reverse=True)

		# Build choices in order: defaults first, then featured, then others
		choices = []

		# Add default templates
		for i, (name, info) in enumerate(default_templates):
			formatted = _format_choice(name, info, width, is_default=True)
			choices.append(Choice(name=formatted, value=name))

		# Add featured templates
		for i, (name, info) in enumerate(featured_templates):
			formatted = _format_choice(name, info, width, is_default=False)
			choices.append(Choice(name=formatted, value=name))

		# Add other templates (if any)
		for name, info in other_templates:
			formatted = _format_choice(name, info, width, is_default=False)
			choices.append(Choice(name=formatted, value=name))

		# Use fuzzy prompt for search functionality
		# Use getattr to avoid static analysis complaining about non-exported names
		_fuzzy = getattr(inquirer, 'fuzzy')
		template = _fuzzy(
			message='Select a template (type to search):',
			choices=choices,
			style=inquirer_style,
			max_height='70%',
		).execute()

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
				'   (Get your key at https://cloud.browser-use.com/dashboard/settings?tab=api-keys&new&utm_source=oss&utm_medium=cli)\n\n',
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
