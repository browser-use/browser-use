"""Export code-use session to Jupyter notebook format."""

import json
import re
from pathlib import Path

from browser_use.code_use.service import CodeAgent

from .views import CellType, NotebookExport


def export_to_ipynb(agent: CodeAgent, output_path: str | Path) -> Path:
	"""
	Export a NotebookSession to a Jupyter notebook (.ipynb) file.
	Now includes JavaScript code blocks that were stored in the namespace.

	Args:
		session: The NotebookSession to export
		output_path: Path where to save the notebook file
		agent: Optional CodeAgent instance to access namespace for JavaScript blocks

	Returns:
		Path to the saved notebook file

	Example:
		```python
	        session = await agent.run()
	        notebook_path = export_to_ipynb(agent, 'my_automation.ipynb')
	        print(f'Notebook saved to {notebook_path}')
		```
	"""
	output_path = Path(output_path)

	# Create notebook structure
	notebook = NotebookExport(
		metadata={
			'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
			'language_info': {
				'name': 'python',
				'version': '3.11.0',
				'mimetype': 'text/x-python',
				'codemirror_mode': {'name': 'ipython', 'version': 3},
				'pygments_lexer': 'ipython3',
				'nbconvert_exporter': 'python',
				'file_extension': '.py',
			},
		}
	)

	# Add setup cell at the beginning with proper type hints
	setup_code = """import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from typing import Any
from browser_use import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.code_use import create_namespace

# Create temporary user directory for browser isolation (cookies, cache, etc.)
# Note: Files created by your script (e.g., JSON files) will be saved in the current working directory
temp_user_dir = Path(tempfile.mkdtemp(prefix='browser-use-script-'))

# Initialize browser with temporary user directory
profile = BrowserProfile(user_data_dir=str(temp_user_dir))
browser = BrowserSession(browser_profile=profile)
await browser.start()

# Create namespace with all browser control functions
namespace: dict[str, Any] = create_namespace(browser)

# Import all functions into the current namespace
globals().update(namespace)

# Type hints for better IDE support (these are now available globally)
# navigate, click, input, evaluate, search, extract, scroll, done, etc.

print("Browser-use environment initialized!")
print("Available functions: navigate, click, input, evaluate, search, extract, done, etc.")"""

	setup_cell = {
		'cell_type': 'code',
		'metadata': {},
		'source': setup_code.split('\n'),
		'execution_count': None,
		'outputs': [],
	}
	notebook.cells.append(setup_cell)

	# Add JavaScript code blocks as variables FIRST
	if hasattr(agent, 'namespace') and agent.namespace:
		# Look for JavaScript variables in the namespace
		code_block_vars = agent.namespace.get('_code_block_vars', set())

		for var_name in sorted(code_block_vars):
			var_value = agent.namespace.get(var_name)
			if isinstance(var_value, str) and var_value.strip():
				# Check if this looks like JavaScript code
				# Look for common JS patterns
				js_patterns = [
					r'function\s+\w+\s*\(',
					r'\(\s*function\s*\(\)',
					r'=>\s*{',
					r'document\.',
					r'Array\.from\(',
					r'\.querySelector',
					r'\.textContent',
					r'\.innerHTML',
					r'return\s+',
					r'console\.log',
					r'window\.',
					r'\.map\(',
					r'\.filter\(',
					r'\.forEach\(',
				]

				is_js = any(re.search(pattern, var_value, re.IGNORECASE) for pattern in js_patterns)

				if is_js:
					# Create a code cell with the JavaScript variable
					js_cell = {
						'cell_type': 'code',
						'metadata': {},
						'source': [f'# JavaScript Code Block: {var_name}\n', f'{var_name} = """{var_value}"""'],
						'execution_count': None,
						'outputs': [],
					}
					notebook.cells.append(js_cell)

	# Convert cells
	python_cell_count = 0
	for cell in agent.session.cells:
		notebook_cell: dict = {
			'cell_type': cell.cell_type.value,
			'metadata': {},
			'source': cell.source.splitlines(keepends=True),
		}

		if cell.cell_type == CellType.CODE:
			python_cell_count += 1
			notebook_cell['execution_count'] = cell.execution_count
			notebook_cell['outputs'] = []

			# Add output if available
			if cell.output:
				notebook_cell['outputs'].append(
					{
						'output_type': 'stream',
						'name': 'stdout',
						'text': cell.output.split('\n'),
					}
				)

			# Add error if available
			if cell.error:
				notebook_cell['outputs'].append(
					{
						'output_type': 'error',
						'ename': 'Error',
						'evalue': cell.error.split('\n')[0] if cell.error else '',
						'traceback': cell.error.split('\n') if cell.error else [],
					}
				)

			# Add browser state as a separate output
			if cell.browser_state:
				notebook_cell['outputs'].append(
					{
						'output_type': 'stream',
						'name': 'stdout',
						'text': [f'Browser State:\n{cell.browser_state}'],
					}
				)

		notebook.cells.append(notebook_cell)

	# Add cleanup cell at the end
	cleanup_code = """# Clean up browser and temporary directory
await browser.stop()

# Remove temporary user directory
try:
    shutil.rmtree(temp_user_dir, ignore_errors=True)
except Exception:
    pass"""

	cleanup_cell = {
		'cell_type': 'code',
		'metadata': {},
		'source': cleanup_code.split('\n'),
		'execution_count': None,
		'outputs': [],
	}
	notebook.cells.append(cleanup_cell)

	# Write to file
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with open(output_path, 'w', encoding='utf-8') as f:
		json.dump(notebook.model_dump(), f, indent=2, ensure_ascii=False)

	return output_path


def session_to_python_script(agent: CodeAgent) -> str:
	"""
	Convert a CodeAgent session to a Python script.
	Now includes JavaScript code blocks that were stored in the namespace.

	Args:
		agent: The CodeAgent instance to convert

	Returns:
		Python script as a string

	Example:
		```python
	        await agent.run()
	        script = session_to_python_script(agent)
	        print(script)
		```
	"""
	lines = []

	lines.append('# Generated from browser-use code-use session\n')
	lines.append('import asyncio\n')
	lines.append('import json\n')
	lines.append('import tempfile\n')
	lines.append('import shutil\n')
	lines.append('from pathlib import Path\n')
	lines.append('from browser_use import BrowserSession\n')
	lines.append('from browser_use.browser.profile import BrowserProfile\n')
	lines.append('from browser_use.code_use import create_namespace\n\n')

	lines.append('async def main():\n')
	lines.append('\t# Create temporary user directory for browser isolation\n')
	lines.append("\ttemp_user_dir = Path(tempfile.mkdtemp(prefix='browser-use-script-'))\n")
	lines.append('\t# Clean up on exit\n')
	lines.append('\t\n')
	lines.append('\t# Initialize browser with temporary user directory\n')
	lines.append('\tprofile = BrowserProfile(user_data_dir=str(temp_user_dir))\n')
	lines.append('\tbrowser = BrowserSession(browser_profile=profile)\n')
	lines.append('\tawait browser.start()\n\n')
	lines.append('\t# Create namespace with all browser control functions\n')
	lines.append('\tnamespace = create_namespace(browser)\n\n')
	lines.append('\t# Extract functions from namespace for direct access\n')
	lines.append('\t# Only extract functions that actually exist in the namespace\n')
	# List of functions to try to extract (in order of preference)
	function_map = {
		'navigate': 'navigate',
		'click': 'click',
		'input_text': 'input',  # input is renamed to input_text in namespace
		'evaluate': 'evaluate',
		'scroll': 'scroll',
		'done': 'done',
		'go_back': 'go_back',
		'wait': 'wait',
		'switch_tab': 'switch',
		'close_tab': 'close',
		'dropdown_options': 'dropdown_options',
		'select_dropdown': 'select_dropdown',
		'upload_file': 'upload_file',
		'send_keys': 'send_keys',
		# These may not be available (excluded in CodeAgentTools):
		'search': 'search',
		'extract': 'extract',
		'screenshot': 'screenshot',
		'find_text': 'find_text',
	}

	for local_name, namespace_key in function_map.items():
		# Only include if it exists in the namespace
		# We'll check this at runtime in the generated script
		if namespace_key in ['input']:
			# Special case: input is renamed to input_text
			lines.append(f'\t{local_name} = namespace.get("input_text") or namespace.get("input")\n')
		else:
			lines.append(f'\t{local_name} = namespace.get("{namespace_key}")\n')

	lines.append('\n')

	# Add JavaScript code blocks as variables FIRST
	if hasattr(agent, 'namespace') and agent.namespace:
		code_block_vars = agent.namespace.get('_code_block_vars', set())

		for var_name in sorted(code_block_vars):
			var_value = agent.namespace.get(var_name)
			if isinstance(var_value, str) and var_value.strip():
				# Check if this looks like JavaScript code
				js_patterns = [
					r'function\s+\w+\s*\(',
					r'\(\s*function\s*\(\)',
					r'=>\s*{',
					r'document\.',
					r'Array\.from\(',
					r'\.querySelector',
					r'\.textContent',
					r'\.innerHTML',
					r'return\s+',
					r'console\.log',
					r'window\.',
					r'\.map\(',
					r'\.filter\(',
					r'\.forEach\(',
				]

				is_js = any(re.search(pattern, var_value, re.IGNORECASE) for pattern in js_patterns)

				if is_js:
					lines.append(f'\t# JavaScript Code Block: {var_name}\n')
					lines.append(f'\t{var_name} = """{var_value}"""\n\n')

	for i, cell in enumerate(agent.session.cells):
		if cell.cell_type == CellType.CODE:
			lines.append(f'\t# Cell {i + 1}\n')

			# Normalize indentation: detect base indentation, remove it, then re-indent consistently with tabs
			source_lines = cell.source.split('\n')

			# Convert everything to spaces first to find minimum indentation
			normalized_lines = []
			min_indent = None
			for line in source_lines:
				# Convert tabs to spaces (assuming 4 spaces per tab, matching ruff config)
				normalized = line.expandtabs(4)
				normalized_lines.append(normalized)

				# Only count indentation for non-empty lines
				if normalized.strip():
					leading_spaces = len(normalized) - len(normalized.lstrip())
					if min_indent is None or leading_spaces < min_indent:
						min_indent = leading_spaces

			# Remove base indentation and re-indent with tabs (matching ruff config)
			# If no indentation found (all empty lines), min_indent will be None
			if min_indent is not None and min_indent > 0:
				for line in normalized_lines:
					if line.strip():  # Non-empty line
						if len(line) >= min_indent:
							unindented = line[min_indent:]
							# Calculate how many tabs to use based on remaining indentation
							# Each 4 spaces = 1 tab (matching ruff config)
							remaining_spaces = len(unindented) - len(unindented.lstrip())
							num_tabs = remaining_spaces // 4
							remaining_indent = '\t' * num_tabs
							content = unindented.lstrip()
							lines.append(f'\t{remaining_indent}{content}\n')
						else:
							lines.append(f'\t{line}\n')
					else:
						# Preserve empty lines
						lines.append('\n')
			else:
				# No base indentation to remove, just add function-level tab
				# But still convert any remaining spaces to tabs
				for line in normalized_lines:
					if line.strip():
						# Convert leading spaces to tabs (4 spaces = 1 tab)
						leading_spaces = len(line) - len(line.lstrip())
						num_tabs = leading_spaces // 4
                        tab_indent = '\t' * num_tabs + ' ' * (leading_spaces % 4)
						content = line.lstrip()
						lines.append(f'\t{tab_indent}{content}\n')
					else:
						lines.append('\n')

			lines.append('\n')

	lines.append('\tawait browser.stop()\n\n')
	lines.append('\t# Clean up temporary user directory\n')
	lines.append('\ttry:\n')
	lines.append('\t\tshutil.rmtree(temp_user_dir, ignore_errors=True)\n')
	lines.append('\texcept Exception:\n')
	lines.append('\t\tpass\n\n')
	lines.append("if __name__ == '__main__':\n")
	lines.append('\tasyncio.run(main())\n')

	return ''.join(lines)
