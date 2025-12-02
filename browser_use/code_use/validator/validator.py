"""Code validator LLM for code-use mode.

Validates code before execution, detects edge cases, and supports code conversion.
"""

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage

if TYPE_CHECKING:
	from browser_use.code_use.validator.sandbox_executor import SandboxExecutor

logger = logging.getLogger(__name__)


class ValidationIssue(BaseModel):
	"""Represents a single validation issue."""

	severity: str  # 'error' | 'warning' | 'info'
	category: str  # 'code_quality' | 'edge_case' | 'browser_api' | 'syntax'
	message: str
	line_number: int | None = None
	suggestion: str | None = None


class ValidationResult(BaseModel):
	"""Result of code validation."""

	is_valid: bool
	improved_code: str | None = None
	issues: list[ValidationIssue] = []
	summary: str = ''


class CodeValidator:
	"""Validates and converts code using LLM."""

	def __init__(self, llm: BaseChatModel):
		"""
		Initialize code validator.

		Args:
			llm: LLM instance for validation and conversion
		"""
		self.llm = llm
		self._system_prompt_content: str | None = None

	def _load_system_prompt(self) -> str:
		"""Load system prompt from validator/system_prompt.md file."""
		if self._system_prompt_content is None:
			# Get the directory where this file is located
			validator_dir = Path(__file__).parent
			system_prompt_path = validator_dir / 'system_prompt.md'

			if system_prompt_path.exists():
				self._system_prompt_content = system_prompt_path.read_text(encoding='utf-8')
			else:
				logger.warning(f'System prompt file not found at {system_prompt_path}, using default')
				self._system_prompt_content = ''

		return self._system_prompt_content

	async def validate_code(
		self,
		code: str,
		context: dict[str, Any] | None = None,
		strict: bool = False,
		use_sandbox: bool = True,
		sandbox: 'SandboxExecutor | None' = None,
	) -> tuple[str, ValidationResult]:
		"""
		Validate code using static analysis, sandbox execution, and LLM.

		Args:
			code: Python code to validate
			context: Optional context (browser state, recent actions, etc.)
			strict: If True, block execution on errors; if False, warn but proceed
			use_sandbox: If True, execute code in sandbox to test if it works
			sandbox: Optional SandboxExecutor instance to use (creates new one if not provided)

		Returns:
			Tuple of (validated_code, validation_result)
		"""
		# No static analysis - rely on execution and LLM validation only

		# Execute code in sandbox to test if it actually works
		execution_result = None
		execution_info = ''
		execution_logs = ''
		execution_files_content = ''
		if use_sandbox:
			try:
				from browser_use.code_use.validator.sandbox_executor import SandboxExecutor

				executor = sandbox if sandbox is not None else SandboxExecutor()
				execution_result = await executor.execute_with_browser_use_context(code, timeout=30)

				if execution_result.success:
					execution_info = f'\n\n✅ Sandbox Execution: PASSED ({execution_result.duration:.2f}s)'
					if execution_result.stdout:
						# Capture full output (truncate if too long)
						stdout_preview = execution_result.stdout[:500] + ('...' if len(execution_result.stdout) > 500 else '')
						execution_info += f'\n   Output: {stdout_preview}'
						execution_logs = execution_result.stdout
					if execution_result.files_created:
						execution_info += f'\n   Files created: {", ".join(execution_result.files_created)}'
						# Read file contents for LLM analysis
						for file_path in execution_result.files_created:
							try:
								full_path = executor.workdir / file_path
								if full_path.exists():
									content = full_path.read_text(encoding='utf-8', errors='replace')
									execution_files_content += (
										f'\n\nFile: {file_path}\n{content[:1000]}{"..." if len(content) > 1000 else ""}'
									)
							except Exception as e:
								logger.debug(f'Failed to read sandbox file {file_path}: {e}')
				else:
					execution_info = f'\n\n❌ Sandbox Execution: FAILED ({execution_result.duration:.2f}s)'
					execution_info += f'\n   Return code: {execution_result.return_code}'
					execution_info += f'\n   Error: {execution_result.error or execution_result.stderr[:500]}'
					if execution_result.stdout:
						execution_info += f'\n   Partial output: {execution_result.stdout[:300]}'
					if execution_result.stderr:
						execution_logs = execution_result.stderr

			except Exception as e:
				logger.warning(f'Sandbox execution failed: {e}')
				execution_info = f'\n\n⚠️ Sandbox execution unavailable: {e}'

		# Build validation prompt for LLM
		context_str = ''
		if context:
			context_str = f'\n\nContext:\n- Recent actions: {context.get("recent_actions", "N/A")}\n'
			if 'browser_state_summary' in context:
				# Truncate browser state if too long
				browser_state = context['browser_state_summary']
				if len(browser_state) > 2000:
					browser_state = browser_state[:2000] + '... [truncated]'
				context_str += f'- Browser state: {browser_state}\n'

		# Extract expected behavior from context if available
		expected_behavior = ''
		expected_output = ''
		if context:
			expected_behavior = context.get('expected_behavior', '')
			expected_output = context.get('expected_output', '')

		# Determine validation focus based on execution results
		validation_focus = []
		if execution_result:
			if not execution_result.success:
				validation_focus.append('SYNTAX ERROR: Code failed to execute. Fix syntax/runtime errors.')
			else:
				validation_focus.append('✅ SYNTAX: Code executed successfully without errors.')
				if execution_result.stdout:
					validation_focus.append(f'📤 OUTPUT: {execution_result.stdout[:300]}')
				if expected_output and execution_result.stdout:
					if (
						expected_output.lower() in execution_result.stdout.lower()
						or execution_result.stdout.lower() in expected_output.lower()
					):
						validation_focus.append('✅ FUNCTIONAL: Output matches expected behavior.')
					else:
						validation_focus.append('❌ FUNCTIONAL: Output does NOT match expected behavior.')
				if expected_behavior:
					validation_focus.append(f'🎯 EXPECTED: {expected_behavior}')

		focus_summary = '\n'.join(f'- {f}' for f in validation_focus) if validation_focus else 'No execution results available.'

		validation_prompt = f"""You are a code validator for browser automation. Your PRIMARY job is to verify TWO things:

1. **SYNTACTICAL CORRECTNESS**: Does the code run without syntax or runtime errors?
2. **FUNCTIONAL CORRECTNESS**: Does the code produce the expected output/results?

CRITICAL INSTRUCTIONS:
- IGNORE style warnings, code quality suggestions, or "best practices" unless they cause functional issues
- FOCUS on whether the code actually WORKS and produces CORRECT output
- Only suggest improvements if they fix errors or correct functional behavior
- If code executes successfully AND produces expected output, mark it as VALID

Static analysis detected these issues (NOTE: Ignore warnings, only care about errors):
No static analysis - relying on execution and LLM validation only.

Code to validate:
```python
{code}
```
{context_str}

{focus_summary}

{execution_info}

{
			f'''
Full Execution Logs:
{execution_logs[:1500] if execution_logs else 'No logs'}
'''
			if execution_logs
			else ''
		}
{
			f'''
Output Files Created:
{execution_files_content[:1500] if execution_files_content else 'No files'}
'''
			if execution_files_content
			else ''
		}

VALIDATION CRITERIA:
1. **Syntax Check**: Did the code execute without errors? If NO → provide fixed code.
2. **Functional Check**: Does the output match what's expected? If NO → identify why and suggest fixes.
3. **Warning Filter**: Only report issues that affect functionality. Ignore style/quality warnings.

CRITICAL RULE FOR fixed_code:
When fixing JavaScript/DOM access code (evaluate() calls), you MUST use the reliable DOM access patterns from the system prompt:
- Use document.querySelector('selector')?.textContent instead of document.title
- Use document.querySelector('meta[name="..."]')?.content instead of direct meta property access
- Always follow the DOM access patterns shown in the system prompt when generating fixed_code
- Example: Change evaluate('document.title') to evaluate('document.querySelector("title")?.textContent || document.title || "No title found"')

CRITICAL: COMPLETE CODE OUTPUT REQUIRED
When providing fixed_code, you MUST output the ENTIRE, COMPLETE code from the "Code to validate" section above. DO NOT:
- Skip parts of the code
- Use placeholders like "..."
- Output partial code
- Truncate or summarize the code
- Only show the changed parts

You MUST include:
- ALL code cells/comments (e.g., "# Cell 1", "# Cell 2", etc.)
- ALL JavaScript variable definitions (e.g., extract_jobs variable with its full JavaScript code)
- ALL imports and setup code that appears in the original
- COMPLETE, EXECUTABLE code that can run without any missing parts

The fixed_code must be a drop-in replacement for the entire original code block.

Provide the following structure:
1. **syntax_errors**: List of syntax/runtime errors found (empty list if none). Format: ["Error description 1", "Error description 2"]
2. **logic_error**: Description of logical/functional error if the code doesn't do what it should (None if code works correctly)
3. **fixed_code**: COMPLETE, FULL fixed code ONLY if there are syntax errors or logic errors, otherwise return None. MUST include ALL code from the original (all cells, all variables, all imports). MUST follow DOM access patterns from system prompt when fixing JavaScript code. MUST use proper Python syntax:
   - NEVER use `printf()` - ALWAYS use `print()` for Python output
   - NEVER change `print(` to `printf(` - if you see `print(` keep it as `print(`
   - Fix escape sequences: In JavaScript regex inside Python strings, replace single backslash-dollar with double backslash-dollar
   - `console.log()` is NOT valid Python - use `print()` instead
   DO NOT truncate or summarize.
4. **summary**: Brief summary of validation results (e.g., "Syntax OK, functional OK" or "Syntax error found: missing parenthesis")"""

		# Log what we're sending to LLM
		logger.info('=' * 80)
		logger.info('SENDING TO LLM VALIDATOR:')
		logger.info('=' * 80)
		logger.info(f'Code to validate ({len(code)} chars):')
		logger.info(code)
		if context_str:
			logger.info(f'\nContext: {context_str}')
		if execution_info:
			logger.info(f'\nExecution Info: {execution_info}')
		if execution_logs:
			logger.info(f'\nExecution Logs ({len(execution_logs)} chars):')
			logger.info(execution_logs[:500] + ('...' if len(execution_logs) > 500 else ''))
		if execution_files_content:
			logger.info(f'\nOutput Files Content ({len(execution_files_content)} chars):')
			logger.info(execution_files_content[:500] + ('...' if len(execution_files_content) > 500 else ''))
		logger.info('=' * 80)

		# Load system prompt with DOM access patterns
		dom_patterns_prompt = self._load_system_prompt()

		base_system_prompt = """You are a code validator focused on TWO things:
1. Syntactical correctness (does it run without errors?)
2. Functional correctness (does it produce expected output?)

IGNORE style warnings, code quality suggestions, or minor improvements unless they affect functionality.
ONLY flag issues that cause errors or produce wrong results.
If code works correctly, mark it as valid even if style could be improved.

CRITICAL: PYTHON SYNTAX - NEVER USE printf
- Python uses `print()` for output, NEVER `printf()`
- If you see `print(` in the original code, keep it as `print(` - DO NOT change it to `printf(`
- `printf` does NOT exist in Python - it will cause NameError
- Always use `print(...)` for Python code output

CRITICAL: When fixing code that uses JavaScript/DOM access, you MUST follow these reliable DOM access patterns:"""

		system_prompt_content = base_system_prompt
		if dom_patterns_prompt:
			# Extract the relevant content (skip the title)
			patterns_content = dom_patterns_prompt.split('\n', 1)[1] if '\n' in dom_patterns_prompt else dom_patterns_prompt
			system_prompt_content += '\n\n' + patterns_content

		system_prompt_content += """

IMPORTANT: When generating fixed_code, you MUST use the reliable DOM access patterns shown above. For example:
- Instead of: await evaluate('document.title')
- Use: await evaluate('(function() { const titleEl = document.querySelector("title"); return titleEl ? titleEl.textContent : (document.title || "No title found"); })()')
- Or simpler: await evaluate('document.querySelector("title")?.textContent || document.title || "No title found"')

Always prefer DOM element access (querySelector) over direct document properties when fixing code.

CRITICAL: PROPER PYTHON SYNTAX REQUIRED
When generating fixed_code, you MUST use correct Python syntax:
- Use `print(...)` NOT `printf(...)` - Python uses print, not printf. NEVER use printf in Python code.
- CORRECT: print(f"Extracted {len(jobs)} jobs.")
- WRONG: printf(f"Extracted {len(jobs)} jobs.")
- If the original code has `print(`, keep it as `print(` - NEVER change it to `printf(`
- Use proper Python indentation (tabs or spaces, be consistent)
- Use proper Python string formatting (f-strings, .format(), or %)
- Ensure all Python keywords and built-ins are spelled correctly (print, not printf; if, not ifdef; etc.)
- Do NOT mix JavaScript syntax with Python (e.g., don't use console.log in Python)
- If you see printf, console.log, or other non-Python syntax, fix it to proper Python

CRITICAL: ESCAPE SEQUENCES IN JAVASCRIPT CODE BLOCKS
When JavaScript code is stored in Python triple-quoted strings (like extract_jobs = triple-quote...triple-quote):
- JavaScript regex patterns with backslash-dollar cause Python SyntaxWarning errors
- When you see patterns like: match(/(backslash + dollar[...])/), you must fix them
- FIX: Replace single backslash-dollar with DOUBLE backslash-dollar in the regex
- Example: Change regex patterns from backslash-dollar to double-backslash-dollar
- Alternative: Use character class with dollar sign inside brackets instead
- Always fix escape sequence warnings when generating fixed_code for JavaScript in Python strings

CRITICAL: COMPLETE CODE OUTPUT REQUIRED
When generating fixed_code, you MUST output the ENTIRE, COMPLETE code. DO NOT be lazy, DO NOT truncate, DO NOT use "...", DO NOT skip sections. 
The fixed_code must include:
- ALL code from the original (every line, every cell, every comment)
- ALL variable definitions (especially JavaScript code blocks)
- ALL imports and setup
- Complete, executable, runnable code that is a full replacement for the original

Output the COMPLETE code - no shortcuts, no summaries, no partial output."""

		system_prompt = SystemMessage(content=system_prompt_content)

		class ValidationResponse(BaseModel):
			"""
			Structured response from LLM validator.

			This model ensures the LLM returns a properly structured response with:
			- syntax_errors: List of syntax/runtime errors
			- logic_error: Description of logical/functional errors
			- fixed_code: COMPLETE corrected code if errors found (must include ALL code from original, no truncation)
			- summary: Validation summary

			IMPORTANT: fixed_code must be COMPLETE - include all cells, all variables, all imports, everything.
			"""

			syntax_errors: list[str] = []
			logic_error: str | None = None
			fixed_code: str | None = None  # Must be COMPLETE code, not partial or truncated
			summary: str

			model_config = {'extra': 'forbid'}  # Reject any extra fields

		try:
			# Request structured output from LLM - returns ValidationResponse object
			response = await self.llm.ainvoke(
				[system_prompt, UserMessage(content=validation_prompt)],
				output_format=ValidationResponse,  # Forces structured JSON schema output
			)

			# Extract structured response (already validated by LLM provider)
			llm_result: ValidationResponse = response.completion  # type: ignore[assignment]

			# Additional validation to ensure all required fields are present
			if not isinstance(llm_result, ValidationResponse):
				raise ValueError(f'Expected ValidationResponse, got {type(llm_result)}')

			# Log LLM response
			logger.info('=' * 80)
			logger.info('LLM VALIDATOR RESPONSE:')
			logger.info('=' * 80)
			logger.info(f'Summary: {llm_result.summary}')
			logger.info(f'Syntax Errors: {len(llm_result.syntax_errors)}')
			for i, error in enumerate(llm_result.syntax_errors, 1):
				logger.info(f'  {i}. {error}')
			if llm_result.logic_error:
				logger.info(f'Logic Error: {llm_result.logic_error}')
			if llm_result.fixed_code:
				logger.info(f'Fixed Code ({len(llm_result.fixed_code)} chars):')
				logger.info(llm_result.fixed_code[:500] + ('...' if len(llm_result.fixed_code) > 500 else ''))
			logger.info('=' * 80)

			# Collect LLM issues
			all_issues = []

			# Convert LLM-detected syntax errors to ValidationIssue objects
			for syntax_error in llm_result.syntax_errors:
				all_issues.append(
					ValidationIssue(
						severity='error',
						category='syntax',
						message=syntax_error,
						line_number=None,
					)
				)

			# Convert logic error to ValidationIssue if present
			if llm_result.logic_error:
				all_issues.append(
					ValidationIssue(
						severity='error',
						category='logic',
						message=llm_result.logic_error,
						line_number=None,
					)
				)

			# Determine final validation status
			# Focus on syntax and functional correctness
			has_execution_errors = execution_result is not None and not execution_result.success
			has_syntax_errors = len(llm_result.syntax_errors) > 0 or has_execution_errors
			has_logic_error = llm_result.logic_error is not None

			# Check functional correctness if execution succeeded
			functionally_correct = True
			if execution_result and execution_result.success:
				# If expected output was provided, verify it matches
				if context and context.get('expected_output'):
					expected = context.get('expected_output', '').lower()
					actual = execution_result.stdout.lower()
					# Simple check: expected content should appear in actual output
					# or vice versa for flexibility
					if expected and not (
						expected in actual
						or actual in expected
						or any(word in actual for word in expected.split() if len(word) > 3)
					):
						functionally_correct = False
						logger.warning('Functional check: Output does not match expected')
						# If LLM didn't catch this logic error, add it
						if not llm_result.logic_error:
							logger.info('Adding logic error: Output mismatch detected but not reported by LLM')

			# Code is valid only if: no syntax errors AND no logic errors AND functionally correct
			has_errors = has_syntax_errors or has_logic_error or not functionally_correct
			is_valid = not has_errors and (not strict or not has_syntax_errors)

			# Use fixed code if provided, otherwise use original
			final_code = llm_result.fixed_code if llm_result.fixed_code else code

			# Build summary from LLM result
			summary = llm_result.summary

			# Enhance summary with execution results if available
			if execution_result:
				if execution_result.success:
					if not has_syntax_errors and not has_logic_error:
						if summary and 'OK' not in summary:
							summary = f'✅ {summary}'
				else:
					if 'failed' not in summary.lower() and 'error' not in summary.lower():
						error_msg = execution_result.error[:100] if execution_result.error else 'Unknown error'
						summary = f'❌ Syntax error: {error_msg}'

			result = ValidationResult(
				is_valid=is_valid,
				improved_code=final_code if final_code != code else None,
				issues=all_issues,
				summary=summary,
			)

			logger.info(f'Code validation: {"✅ Passed" if is_valid else "❌ Failed"} - {result.summary}')

			return final_code, result

		except Exception as e:
			logger.warning(f'LLM validation failed: {e}')
			# Return original code with error result
			result = ValidationResult(
				is_valid=False,
				improved_code=None,
				issues=[],
				summary=f'Validation failed: LLM validation error - {e}',
			)
			return code, result

	async def convert_code(
		self,
		code: str,
		target_format: str,
		context: dict[str, Any] | None = None,
	) -> str:
		"""
		Convert code to target format (TypeScript, Playwright, etc.).

		Args:
			code: Python code to convert
			target_format: Target format ('typescript', 'playwright', etc.)
			context: Optional context (browser state, available functions, etc.)

		Returns:
			Converted code as string
		"""
		context_str = ''
		if context:
			context_str = f'\n\nContext:\n{context}\n'

		# Build conversion knowledge base hints
		conversion_hints = {
			'playwright': """
Key conversions:
- navigate(url) → await page.goto(url)
- click(index) → await page.locator(selector).click()  # Note: convert index to selector first
- input(index, text) → await page.locator(selector).fill(text)
- evaluate(code) → await page.evaluate(code)
- scroll(...) → await page.evaluate('window.scrollBy(...)')
- get_selector_from_index(index) → Use page.locator() directly with selector
- All browser-use functions are async, maintain async/await patterns
""",
			'typescript': """
Key conversions:
- navigate(url) → await page.goto(url)  # Using Playwright
- click(index) → await page.locator(selector).click()
- input(index, text) → await page.locator(selector).fill(text)
- evaluate(code) → await page.evaluate(code)
- Python dict/list → TypeScript object/array
- Type hints: Python → TypeScript types
- Use Playwright API for browser automation in TypeScript
""",
		}

		hints = conversion_hints.get(target_format.lower(), '')

		conversion_prompt = f"""Convert the following Python browser automation code to {target_format.upper()}.

Maintain all functionality while translating to the target format.
{hints}

Original Python code:
```python
{code}
```
{context_str}

Provide the converted code in a code block with language tag ```{target_format.lower()}.
Include all necessary imports and setup code.
Preserve logic, error handling, and all operations."""

		system_prompt = SystemMessage(
			content=f"""You are an expert code converter specializing in browser automation.
Convert Python browser-use code to {target_format.upper()} while preserving all functionality.
Use appropriate APIs and patterns for the target language."""
		)

		class ConversionResponse(BaseModel):
			"""Structured response from LLM converter."""

			converted_code: str
			notes: str = ''

		try:
			response = await self.llm.ainvoke(
				[system_prompt, UserMessage(content=conversion_prompt)],
				output_format=ConversionResponse,
			)

			llm_result: ConversionResponse = response.completion  # type: ignore[assignment]
			converted = llm_result.converted_code

			# Extract code from markdown code block if present (LLM might return markdown)
			code_block_pattern = rf'```{target_format.lower()}\s*\n(.*?)```'
			match = re.search(code_block_pattern, converted, re.DOTALL)
			if match:
				converted = match.group(1).strip()
			else:
				# Also check for generic code blocks
				generic_pattern = r'```\s*\n(.*?)```'
				match = re.search(generic_pattern, converted, re.DOTALL)
				if match:
					converted = match.group(1).strip()

			logger.info(f'Code converted to {target_format}')
			if llm_result.notes:
				logger.debug(f'Conversion notes: {llm_result.notes}')

			return converted

		except Exception as e:
			logger.error(f'Code conversion failed: {e}')
			raise RuntimeError(f'Failed to convert code to {target_format}: {e}')
