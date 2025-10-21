"""
Standalone init command for browser-use template generation.

This module provides a minimal command-line interface for generating
browser-use templates without requiring heavy TUI dependencies.
"""

import sys
from pathlib import Path

import click

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
		'description': 'Custom action examples - extend the agent with your own functions',
	},
}


def _write_init_file(output_path: Path, content: str, force: bool = False) -> bool:
	"""Write content to a file, with safety checks."""
	# Check if file already exists
	if output_path.exists() and not force:
		click.echo(f'⚠️  File already exists: {output_path}')
		if not click.confirm('Overwrite?', default=False):
			click.echo('❌ Cancelled')
			return False

	# Ensure parent directory exists
	output_path.parent.mkdir(parents=True, exist_ok=True)

	# Write file
	try:
		output_path.write_text(content, encoding='utf-8')
		return True
	except Exception as e:
		click.echo(f'❌ Error writing file: {e}', err=True)
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
		click.echo('Available templates:\n')
		for name, info in INIT_TEMPLATES.items():
			click.echo(f'  {name:12} - {info["description"]}')
		return

	# Interactive template selection if not provided
	if not template:
		click.echo('Available templates:\n')
		for name, info in INIT_TEMPLATES.items():
			click.echo(f'  {name:12} - {info["description"]}')
		click.echo()

		template = click.prompt(
			'Which template would you like to use?',
			type=click.Choice(['default', 'advanced', 'tools'], case_sensitive=False),
			default='default',
		)

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
		click.echo(f'❌ Error reading template: {e}', err=True)
		sys.exit(1)

	# Write file
	if _write_init_file(output_path, content, force):
		click.echo(f'✅ Created {output_path}')
		click.echo('\nNext steps:')
		click.echo('  1. Install browser-use:')
		click.echo('     uv pip install browser-use')
		click.echo('  2. Set up your API key in .env file or environment:')
		click.echo('     BROWSER_USE_API_KEY=your-key')
		click.echo('     (Get your key at https://cloud.browser-use.com/dashboard/api)')
		click.echo('  3. Run your script:')
		click.echo(f'     python {output_path.name}')
	else:
		sys.exit(1)


if __name__ == '__main__':
	main()
