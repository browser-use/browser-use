"""Code validator LLM for code-use mode.

Validates code before execution, detects edge cases, and supports code conversion.
"""

import ast
import logging
import re
from typing import Any

from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import SystemMessage, UserMessage

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

	def _detect_edge_cases(self, code: str) -> list[ValidationIssue]:
		"""
		Static analysis to detect common edge cases.

		Args:
			code: Python code to analyze

		Returns:
			List of detected issues
		"""
		issues: list[ValidationIssue] = []

		try:
			# Parse code to AST for analysis
			tree = ast.parse(code, mode='exec')
		except SyntaxError:
			# Syntax errors will be caught by execution, skip AST analysis
			return issues

		# Pattern 1: Stale index usage in loops after page changes
		# Look for: for idx in [...]: await click(index=idx)
		# This pattern is dangerous because indices become stale after first click
		stale_index_pattern = re.compile(
			r'for\s+\w+\s+in\s+.*?:\s*.*?await\s+(click|input|upload_file|select_dropdown)\s*\([^)]*index\s*=.*?\)',
			re.MULTILINE | re.DOTALL,
		)
		if stale_index_pattern.search(code):
			# Try to find the line number
			line_num = None
			for i, line in enumerate(code.split('\n'), 1):
				if re.search(r'for\s+\w+\s+in.*index', line):
					line_num = i
					break

			issues.append(
				ValidationIssue(
					severity='error',
					category='edge_case',
					message='Using element indices in a loop after page changes. Indices become stale after the first interaction.',
					line_number=line_num,
					suggestion='Extract URLs or selectors first, then navigate/click. See: links = await evaluate("..."); for url in links: await navigate(url)',
				)
			)

		# Pattern 2: Multiple similar extraction blocks
		# Detect repeated patterns of similar code (potential redundancy)
		extraction_patterns = re.findall(
			r'await\s+evaluate\s*\([^)]*querySelector[^)]*\)',
			code,
			re.IGNORECASE,
		)
		if len(extraction_patterns) > 2:
			issues.append(
				ValidationIssue(
					severity='warning',
					category='code_quality',
					message=f'Multiple similar extraction patterns detected ({len(extraction_patterns)}). Consider combining into a single extraction.',
					line_number=None,
					suggestion='Combine multiple extraction attempts into one evaluate() call that extracts all needed data at once.',
				)
			)

		# Pattern 3: Missing error handling around get_element_by_index
		if 'get_element_by_index' in code or 'get_selector_from_index' in code:
			# Check if wrapped in try-except
			try_except_count = len(re.findall(r'try\s*:', code))
			get_index_count = len(re.findall(r'get_(element|selector)_from_index', code))
			if get_index_count > 0 and try_except_count < get_index_count:
				issues.append(
					ValidationIssue(
						severity='warning',
						category='edge_case',
						message='get_element_by_index or get_selector_from_index used without error handling. These can fail if indices are stale.',
						line_number=None,
						suggestion='Wrap get_element_by_index/get_selector_from_index calls in try-except to handle stale indices gracefully.',
					)
				)

		# Pattern 4: Check for proper async/await usage
		has_await = 'await' in code
		has_async_func = bool(re.search(r'async\s+def', code))
		if has_await and not has_async_func:
			# This might be okay in top-level code, but flag if in a function
			has_def = bool(re.search(r'^\s*def\s+', code, re.MULTILINE))
			if has_def:
				issues.append(
					ValidationIssue(
						severity='error',
						category='syntax',
						message='Using await in a non-async function. Functions with await must be async.',
						line_number=None,
						suggestion='Add async keyword before def: async def function_name(...)',
					)
				)

		return issues

	async def validate_code(
		self,
		code: str,
		context: dict[str, Any] | None = None,
		strict: bool = False,
	) -> tuple[str, ValidationResult]:
		"""
		Validate code using both static analysis and LLM.

		Args:
			code: Python code to validate
			context: Optional context (browser state, recent actions, etc.)
			strict: If True, block execution on errors; if False, warn but proceed

		Returns:
			Tuple of (validated_code, validation_result)
		"""
		# First, run static analysis
		static_issues = self._detect_edge_cases(code)
		critical_errors = [issue for issue in static_issues if issue.severity == 'error']

		# If strict mode and critical errors, return early
		if strict and critical_errors:
			result = ValidationResult(
				is_valid=False,
				improved_code=None,
				issues=static_issues,
				summary=f'Validation failed: {len(critical_errors)} critical error(s) found.',
			)
			return code, result

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

		validation_prompt = f"""You are a code validator for browser automation. Analyze the following Python code for:
1. Code quality (redundancy, clean structure, best practices)
2. Edge cases (stale element indices, missing error handling)
3. Browser API usage correctness
4. Potential bugs or runtime errors

Static analysis has already detected these issues:
{chr(10).join(f'- [{issue.severity.upper()}] {issue.message}' for issue in static_issues) if static_issues else 'None detected'}

Code to validate:
```python
{code}
```
{context_str}

Analyze the code and provide:
1. A validation summary
2. Improved code if issues are found (or the original code if it's good)
3. Additional issues not caught by static analysis

Focus on:
- Combining redundant code (e.g., multiple similar extraction attempts)
- Fixing stale index patterns
- Improving error handling
- Code cleanliness and efficiency"""

		system_prompt = SystemMessage(
			content="""You are an expert code validator specializing in browser automation.
Your task is to validate code, detect issues, and provide improved versions when needed.
Return structured validation results with improved code when applicable."""
		)

		class ValidationResponse(BaseModel):
			"""Structured response from LLM validator."""

			is_valid: bool
			improved_code: str | None = None
			additional_issues: list[str] = []
			summary: str
			reasoning: str = ''

		try:
			response = await self.llm.ainvoke(
				[system_prompt, UserMessage(content=validation_prompt)],
				output_format=ValidationResponse,
			)

			llm_result: ValidationResponse = response.completion  # type: ignore[assignment]

			# Combine static and LLM issues
			all_issues = static_issues.copy()

			# Convert LLM-detected issues to ValidationIssue objects
			for issue_msg in llm_result.additional_issues:
				all_issues.append(
					ValidationIssue(
						severity='warning',
						category='code_quality',
						message=issue_msg,
						line_number=None,
					)
				)

			# Determine final validation status
			has_errors = any(issue.severity == 'error' for issue in all_issues)
			is_valid = not has_errors or not strict

			# Use improved code if provided, otherwise use original
			final_code = llm_result.improved_code if llm_result.improved_code else code

			result = ValidationResult(
				is_valid=is_valid,
				improved_code=final_code if final_code != code else None,
				issues=all_issues,
				summary=llm_result.summary or 'Code validated successfully.',
			)

			logger.info(f'Code validation: {"✅ Passed" if is_valid else "❌ Failed"} - {result.summary}')

			return final_code, result

		except Exception as e:
			logger.warning(f'LLM validation failed: {e}, falling back to static analysis')
			# Fall back to static analysis only
			is_valid = not critical_errors or not strict
			result = ValidationResult(
				is_valid=is_valid,
				improved_code=None,
				issues=static_issues,
				summary=f'Validation completed with static analysis only. {len(static_issues)} issue(s) found.',
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
