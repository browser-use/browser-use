"""Export code-use session to Jupyter notebook format."""

import json
import re
from pathlib import Path

from browser_use.code_use.service import CodeAgent
from browser_use.llm.base import BaseChatModel

from .views import CellType, NotebookExport


def _fix_js_escape_sequences(js_code: str) -> str:
	"""
	Fix escape sequences in JavaScript code that cause Python SyntaxWarning when stored in triple-quoted strings.

	Args:
		js_code: JavaScript code string

	Returns:
		JavaScript code with fixed escape sequences for Python string literals
	"""
	# Replace \$ (backslash-dollar) with \\$ (double backslash-dollar)
	# But only if it's not already \\$ (avoid double-escaping)
	# Pattern: match \$ that's not preceded by another backslash
	# Using negative lookbehind: (?<!\\\\)\$ means "dollar not preceded by two backslashes"
	fixed_code = re.sub(r'(?<!\\\\)\\$', r'\\\\$', js_code)

	return fixed_code


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
from typing import Any
from browser_use import BrowserSession
from browser_use.code_use import create_namespace

# Initialize browser and namespace
browser = BrowserSession()
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

	# Write to file
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with open(output_path, 'w', encoding='utf-8') as f:
		json.dump(notebook.model_dump(), f, indent=2, ensure_ascii=False)

	return output_path


async def session_to_python_script(
	agent: CodeAgent,
	validator_llm: BaseChatModel | None = None,
	apply_improvements: bool = False,
) -> str | tuple[str, str]:
	"""
	Convert a CodeAgent session to a Python script.
	Now includes JavaScript code blocks that were stored in the namespace.

	Args:
		agent: The CodeAgent instance to convert
		validator_llm: Optional LLM for code validation (uses agent's LLM if None)
		apply_improvements: If True, applies validator improvements and returns both original and improved versions.

	Returns:
		- If apply_improvements=False: Python script as a string (original version)
		- If apply_improvements=True: Tuple of (original_script, improved_script)
		  If no improvements were found, improved_script will be None

	Example:
		```python
	        await agent.run()
	        script = await session_to_python_script(agent)
	        print(script)

	        # With validation and auto-apply improvements (returns both versions)
	        original, improved = await session_to_python_script(agent, validator_llm=llm, apply_improvements=True)
	        print('Original:', original)
	        if improved:
	            print('Improved:', improved)
		```
	"""
	lines = []

	lines.append('# Generated from browser-use code-use session\n')
	lines.append('import asyncio\n')
	lines.append('import json\n')
	lines.append('from browser_use import BrowserSession\n')
	lines.append('from browser_use.code_use import create_namespace\n\n')

	lines.append('async def main():\n')
	lines.append('\t# Initialize browser and namespace\n')
	lines.append('\tbrowser = BrowserSession()\n')
	lines.append('\tawait browser.start()\n\n')
	lines.append('\t# Create namespace with all browser control functions\n')
	lines.append('\tnamespace = create_namespace(browser)\n\n')
	lines.append('\t# Extract functions from namespace for direct access\n')
	lines.append('\tnavigate = namespace["navigate"]\n')
	lines.append('\tclick = namespace["click"]\n')
	lines.append('\tinput_text = namespace["input"]\n')
	lines.append('\tevaluate = namespace["evaluate"]\n')
	lines.append('\tsearch = namespace["search"]\n')
	lines.append('\textract = namespace["extract"]\n')
	lines.append('\tscroll = namespace["scroll"]\n')
	lines.append('\tdone = namespace["done"]\n')
	lines.append('\tgo_back = namespace["go_back"]\n')
	lines.append('\twait = namespace["wait"]\n')
	lines.append('\tscreenshot = namespace["screenshot"]\n')
	lines.append('\tfind_text = namespace["find_text"]\n')
	lines.append('\tswitch_tab = namespace["switch"]\n')
	lines.append('\tclose_tab = namespace["close"]\n')
	lines.append('\tdropdown_options = namespace["dropdown_options"]\n')
	lines.append('\tselect_dropdown = namespace["select_dropdown"]\n')
	lines.append('\tupload_file = namespace["upload_file"]\n')
	lines.append('\tsend_keys = namespace["send_keys"]\n\n')

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
					# Fix escape sequences in JavaScript code for Python string literals
					fixed_js = _fix_js_escape_sequences(var_value)
					lines.append(f'\t# JavaScript Code Block: {var_name}\n')
					lines.append(f'\t{var_name} = """{fixed_js}"""\n\n')

	# Collect all code cells first
	code_cells = []
	for cell in agent.session.cells:
		if cell.cell_type == CellType.CODE:
			code_cells.append(cell)

	# Validate full script once if validator LLM is provided
	validated_cells = {}
	if validator_llm and code_cells:
		from browser_use.code_use.validator.validator import CodeValidator

		validator = CodeValidator(validator_llm)

		try:
			# Combine JavaScript variables and all code cells into one script for validation
			all_code_lines = []

			# First, include JavaScript code blocks (they're needed for validation)
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
							# Fix escape sequences in JavaScript code for Python string literals
							fixed_js = _fix_js_escape_sequences(var_value)
							all_code_lines.append(f'# JavaScript Code Block: {var_name}\n')
							all_code_lines.append(f'{var_name} = """{fixed_js}"""\n\n')

			# Then, include all code cells
			for i, cell in enumerate(code_cells):
				if cell.source.strip():
					all_code_lines.append(f'# Cell {i + 1}\n')
					all_code_lines.append(cell.source)
					all_code_lines.append('\n\n')

			full_script = ''.join(all_code_lines)

			if full_script.strip():
				# Validate entire script at once
				validated_code, validation_result = await validator.validate_code(
					full_script,
					context={
						'export_type': 'python_script',
						'total_cells': len(code_cells),
						'expected_behavior': 'Execute all cells sequentially in a single script',
					},
					strict=False,
					use_sandbox=True,
				)

				# Log validation summary (always provide verdict)
				import logging

				logger = logging.getLogger(__name__)

				# Always log the validation verdict
				if validation_result.is_valid:
					if validation_result.issues:
						logger.info(f'✅ Script validation: Code is VALID ({len(validation_result.issues)} minor issue(s) found)')
					else:
						logger.info('✅ Script validation: Code is VALID - no issues found')
				else:
					logger.warning(f'❌ Script validation: Code has ISSUES ({len(validation_result.issues)} issue(s) found)')

				# Log all issues
				for issue in validation_result.issues:
					severity_emoji = '🔴' if issue.severity == 'error' else '🟡' if issue.severity == 'warning' else '🔵'
					logger.info(f'{severity_emoji} [{issue.severity.upper()}] {issue.message}')

				if validation_result.summary:
					logger.info(f'📋 Summary: {validation_result.summary}')

				# Only apply improvements if flag is set
				if apply_improvements and validation_result.improved_code:
					logger.info('🔧 Applying validator improvements to code...')
					validated_full = validation_result.improved_code

					# Parse validated code back into cells
					# Split by cell comments: "# Cell N" - preserve boundaries if possible
					cell_pattern = re.compile(r'#\s*Cell\s+(\d+)', re.IGNORECASE)
					parts = cell_pattern.split(validated_full)

					if len(parts) > 1:
						# Successfully found cell boundaries in validated code
						# parts[0] = before first cell, then [cell_num, code, cell_num, code, ...]
						for idx in range(1, len(parts), 2):
							if idx + 1 < len(parts):
								cell_num = int(parts[idx])
								cell_code = parts[idx + 1].strip()
								# Remove trailing empty lines
								while cell_code.endswith('\n'):
									cell_code = cell_code[:-1]
								# Remove any leading empty lines
								while cell_code.startswith('\n'):
									cell_code = cell_code[1:]
								if cell_code:
									validated_cells[cell_num - 1] = cell_code  # 0-indexed
					else:
						# Cell boundaries not preserved - use validated full script as-is
						# Store as a single "meta-cell" that replaces all cells
						logger.debug('Cell boundaries not preserved in validated code, using full validated script')
						validated_cells['_full_script'] = validated_full
				elif validation_result.improved_code and not apply_improvements:
					logger.info(
						'💡 Validator found improvements but apply_improvements=False. Set apply_improvements=True to apply them.'
					)

		except Exception as e:
			import logging

			logging.getLogger(__name__).warning(f'Full script validation failed: {e}')

	# Build output using validated code where available
	if '_full_script' in validated_cells:
		# LLM reorganized code without preserving cell boundaries - use full script
		validated_full = validated_cells['_full_script']
		# Preserve original formatting - just indent everything
		source_lines = validated_full.splitlines(keepends=True)
		for line in source_lines:
			# Skip standalone cell comment lines, but preserve all other formatting
			if line.strip() and not re.match(r'^\s*#\s*Cell\s+\d+', line):
				lines.append(f'\t{line}' if not line.endswith('\n') else f'\t{line}')
			elif not line.strip():
				# Preserve empty lines
				lines.append('\n')
	else:
		# Use validated cells or original code
		for i, cell in enumerate(agent.session.cells):
			if cell.cell_type == CellType.CODE:
				cell_index = code_cells.index(cell)

				# Always use original cell.source for original script
				cell_code = cell.source

				# Preserve original formatting exactly - just indent all lines by one tab
				source_lines = cell_code.splitlines(keepends=True)
				for line in source_lines:
					if line.endswith('\n'):
						lines.append(f'\t{line}')
					elif line:
						lines.append(f'\t{line}\n')
					else:
						# Preserve empty lines
						lines.append('\n')

				# Add single blank line between cells for readability
				lines.append('\n')

	lines.append('\tawait browser.stop()\n\n')
	lines.append("if __name__ == '__main__':\n")
	lines.append('\tasyncio.run(main())\n')

	original_script = ''.join(lines)

	# If apply_improvements=True, also build and return improved version
	if apply_improvements:
		# Check if we have validated improvements to build
		if validated_cells:
			# Build improved script using validated code
			improved_lines = []

			# Same setup code
			improved_lines.append('# Generated from browser-use code-use session (VALIDATED AND IMPROVED)\n')
			improved_lines.append('import asyncio\n')
			improved_lines.append('import json\n')
			improved_lines.append('from browser_use import BrowserSession\n')
			improved_lines.append('from browser_use.code_use import create_namespace\n\n')
			improved_lines.append('async def main():\n')
			improved_lines.append('\t# Initialize browser and namespace\n')
			improved_lines.append('\tbrowser = BrowserSession()\n')
			improved_lines.append('\tawait browser.start()\n\n')
			improved_lines.append('\t# Create namespace with all browser control functions\n')
			improved_lines.append('\tnamespace = create_namespace(browser)\n\n')
			improved_lines.append('\t# Extract functions from namespace for direct access\n')
			improved_lines.append('\tnavigate = namespace["navigate"]\n')
			improved_lines.append('\tclick = namespace["click"]\n')
			improved_lines.append('\tinput_text = namespace["input"]\n')
			improved_lines.append('\tevaluate = namespace["evaluate"]\n')
			improved_lines.append('\tsearch = namespace["search"]\n')
			improved_lines.append('\textract = namespace["extract"]\n')
			improved_lines.append('\tscroll = namespace["scroll"]\n')
			improved_lines.append('\tdone = namespace["done"]\n')
			improved_lines.append('\tgo_back = namespace["go_back"]\n')
			improved_lines.append('\twait = namespace["wait"]\n')
			improved_lines.append('\tscreenshot = namespace["screenshot"]\n')
			improved_lines.append('\tfind_text = namespace["find_text"]\n')
			improved_lines.append('\tswitch_tab = namespace["switch"]\n')
			improved_lines.append('\tclose_tab = namespace["close"]\n')
			improved_lines.append('\tdropdown_options = namespace["dropdown_options"]\n')
			improved_lines.append('\tselect_dropdown = namespace["select_dropdown"]\n')
			improved_lines.append('\tupload_file = namespace["upload_file"]\n')
			improved_lines.append('\tsend_keys = namespace["send_keys"]\n\n')

			# Include JavaScript code blocks
			if hasattr(agent, 'namespace') and agent.namespace:
				code_block_vars = agent.namespace.get('_code_block_vars', set())
				for var_name in sorted(code_block_vars):
					var_value = agent.namespace.get(var_name)
					if isinstance(var_value, str) and var_value.strip():
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
							# Fix escape sequences in JavaScript code for Python string literals
							fixed_js = _fix_js_escape_sequences(var_value)
							improved_lines.append(f'\t# JavaScript Code Block: {var_name}\n')
							improved_lines.append(f'\t{var_name} = """{fixed_js}"""\n\n')

			# Add validated/improved code
			if '_full_script' in validated_cells:
				validated_full = validated_cells['_full_script']
				# Preserve original formatting - just indent everything
				source_lines = validated_full.splitlines(keepends=True)
				for line in source_lines:
					# Skip standalone cell comment lines, but preserve all other formatting
					if line.strip() and not re.match(r'^\s*#\s*Cell\s+\d+', line):
						if line.endswith('\n'):
							improved_lines.append(f'\t{line}')
						elif line:
							improved_lines.append(f'\t{line}\n')
						else:
							improved_lines.append('\n')
					elif not line.strip():
						# Preserve empty lines
						improved_lines.append('\n')
			else:
				# Use validated cells or original code
				for i, cell in enumerate(agent.session.cells):
					if cell.cell_type == CellType.CODE:
						cell_index = code_cells.index(cell)
						cell_code = validated_cells.get(cell_index, cell.source)

						# Preserve original formatting exactly - just indent all lines by one tab
						source_lines = cell_code.splitlines(keepends=True)
						for line in source_lines:
							if line.endswith('\n'):
								improved_lines.append(f'\t{line}')
							elif line:
								improved_lines.append(f'\t{line}\n')
							else:
								# Preserve empty lines
								improved_lines.append('\n')

						# Add single blank line between cells for readability
						improved_lines.append('\n')

			improved_lines.append('\tawait browser.stop()\n\n')
			improved_lines.append("if __name__ == '__main__':\n")
			improved_lines.append('\tasyncio.run(main())\n')

			improved_script = ''.join(improved_lines)
			return original_script, improved_script
		else:
			# apply_improvements=True but no validated improvements found
			return original_script, None

	return original_script


async def session_to_playwright_script(agent: CodeAgent, validator_llm: BaseChatModel | None = None) -> str:
	"""
	Convert a CodeAgent session to a Playwright script.

	Args:
		agent: The CodeAgent instance to convert
		validator_llm: Optional LLM for code conversion (uses agent's LLM if None)

	Returns:
		Playwright script as a string

	Example:
		```python
	        await agent.run()
	        script = await session_to_playwright_script(agent)
	        print(script)
		```
	"""
	from browser_use.code_use.validator.validator import CodeValidator

	# Use provided LLM or agent's LLM
	conversion_llm = validator_llm or agent.llm
	validator = CodeValidator(conversion_llm)

	# Collect all code from cells
	all_code_lines = []

	# Add setup code
	all_code_lines.append('# Playwright setup\n')
	all_code_lines.append('import asyncio\n')
	all_code_lines.append('from playwright.async_api import async_playwright\n\n')
	all_code_lines.append('async def main():\n')
	all_code_lines.append('    async with async_playwright() as p:\n')
	all_code_lines.append('        browser = await p.chromium.launch()\n')
	all_code_lines.append('        page = await browser.new_page()\n\n')

	# Convert each code cell
	for i, cell in enumerate(agent.session.cells):
		if cell.cell_type == CellType.CODE and cell.source.strip():
			cell_code = cell.source
			# Indent for async context
			indented_code = '\n'.join('    ' + line if line.strip() else line for line in cell_code.split('\n'))

			try:
				# Convert this cell's code to Playwright
				context = {
					'cell_number': i + 1,
					'previous_cells': len([c for c in agent.session.cells[:i] if c.cell_type == CellType.CODE]),
				}
				converted = await validator.convert_code(cell_code, target_format='playwright', context=context)
				# Ensure proper indentation
				indented_converted = '\n'.join('        ' + line if line.strip() else line for line in converted.split('\n'))
				all_code_lines.append(f'        # Cell {i + 1} (converted)\n')
				all_code_lines.append(indented_converted)
				all_code_lines.append('\n\n')
			except Exception as e:
				# Fallback: add original code with comment
				all_code_lines.append(f'        # Cell {i + 1} - Conversion failed: {e}\n')
				all_code_lines.append('        # Original code:\n')
				for line in indented_code.split('\n'):
					all_code_lines.append(f'        # {line}\n')
				all_code_lines.append('\n')

	all_code_lines.append('        await browser.close()\n\n')
	all_code_lines.append("if __name__ == '__main__':\n")
	all_code_lines.append('    asyncio.run(main())\n')

	return ''.join(all_code_lines)


async def session_to_typescript_script(agent: CodeAgent, validator_llm: BaseChatModel | None = None) -> str:
	"""
	Convert a CodeAgent session to a TypeScript script.

	Args:
		agent: The CodeAgent instance to convert
		validator_llm: Optional LLM for code conversion (uses agent's LLM if None)

	Returns:
		TypeScript script as a string

	Example:
		```python
	        await agent.run()
	        script = await session_to_typescript_script(agent)
	        print(script)
		```
	"""
	from browser_use.code_use.validator.validator import CodeValidator

	# Use provided LLM or agent's LLM
	conversion_llm = validator_llm or agent.llm
	validator = CodeValidator(conversion_llm)

	# Collect all code from cells
	all_code_lines = []

	# Add setup code
	all_code_lines.append('// TypeScript Playwright script\n')
	all_code_lines.append('import { chromium } from "playwright";\n\n')
	all_code_lines.append('async function main() {\n')
	all_code_lines.append('    const browser = await chromium.launch();\n')
	all_code_lines.append('    const page = await browser.newPage();\n\n')

	# Convert each code cell
	for i, cell in enumerate(agent.session.cells):
		if cell.cell_type == CellType.CODE and cell.source.strip():
			cell_code = cell.source

			try:
				# Convert this cell's code to TypeScript
				context = {
					'cell_number': i + 1,
					'previous_cells': len([c for c in agent.session.cells[:i] if c.cell_type == CellType.CODE]),
				}
				converted = await validator.convert_code(cell_code, target_format='typescript', context=context)
				# Ensure proper indentation
				indented_converted = '\n'.join('    ' + line if line.strip() else line for line in converted.split('\n'))
				all_code_lines.append(f'    // Cell {i + 1} (converted)\n')
				all_code_lines.append(indented_converted)
				all_code_lines.append('\n\n')
			except Exception as e:
				# Fallback: add original code with comment
				all_code_lines.append(f'    // Cell {i + 1} - Conversion failed: {e}\n')
				all_code_lines.append('    // Original Python code could not be converted\n')
				all_code_lines.append('\n')

	all_code_lines.append('    await browser.close();\n')
	all_code_lines.append('}\n\n')
	all_code_lines.append('main().catch(console.error);\n')

	return ''.join(all_code_lines)
