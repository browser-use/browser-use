"""
Standalone init command for browser-use template generation.

This module provides a minimal command-line interface for generating
browser-use templates without requiring heavy TUI dependencies.
"""

import sys
from pathlib import Path

import click
from InquirerPy.base.control import Choice
from InquirerPy.prompts.list import ListPrompt
from InquirerPy.utils import InquirerPyStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Template metadata
INIT_TEMPLATES = {
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
}

# Rich console for styled output
console = Console()

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
	type=click.Choice(['default', 'advanced', 'tools'], case_sensitive=False),
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

		template = prompt.execute()

		# Handle user cancellation (Ctrl+C)
		if template is None:
			console.print('\n[red]✗[/red] Cancelled')
			sys.exit(1)

	# Template is guaranteed to be set at this point (either from option or prompt)
	assert template is not None

	# Determine output path
	if output:
		output_path = Path(output)
	else:
		output_path = Path.cwd() / f'browser_use_{template}.py'

	# Read template file
	try:
		templates_dir = Path(__file__).parent / 'cli_templates'
		template_file = INIT_TEMPLATES[template]['file']
		template_path = templates_dir / template_file
		content = template_path.read_text(encoding='utf-8')
	except Exception as e:
		console.print(f'[red]✗[/red] Error reading template: {e}')
		sys.exit(1)

	# Write file
	if _write_init_file(output_path, content, force):
		console.print(f'\n[green]✓[/green] Created [cyan]{output_path}[/cyan]')

		# Create a nice panel for next steps
		next_steps = Text()
		next_steps.append('\n1. Install browser-use:\n', style='bold')
		next_steps.append('   uv pip install browser-use\n\n', style='dim')
		next_steps.append('2. Set up your API key in .env file or environment:\n', style='bold')
		next_steps.append('   BROWSER_USE_API_KEY=your-key\n', style='dim')
		next_steps.append('   (Get your key at https://cloud.browser-use.com/dashboard/api)\n\n', style='dim italic')
		next_steps.append('3. Run your script:\n', style='bold')
		next_steps.append(f'   python {output_path.name}\n', style='dim')

		console.print(
			Panel(
				next_steps,
				title='[bold]Next steps[/bold]',
				border_style='#fe750e',
				padding=(1, 2),
			)
		)
	else:
		sys.exit(1)


if __name__ == '__main__':
	main()
