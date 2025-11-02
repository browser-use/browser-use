"""Sandbox executor for code validation - runs code in isolated environment."""

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ExecutionResult:
	"""Result of code execution in sandbox."""

	def __init__(
		self,
		success: bool,
		stdout: str = '',
		stderr: str = '',
		return_code: int = 0,
		duration: float = 0.0,
		files_created: list[str] = None,
		error: str | None = None,
	):
		self.success = success
		self.stdout = stdout
		self.stderr = stderr
		self.return_code = return_code
		self.duration = duration
		self.files_created = files_created or []
		self.error = error

	def __str__(self) -> str:
		if self.success:
			return f'Execution succeeded (duration: {self.duration:.2f}s)'
		else:
			return f'Execution failed (code: {self.return_code}): {self.error or self.stderr}'


class SandboxExecutor:
	"""Executes code in an isolated sandbox environment."""

	def __init__(self, workdir: Path | str | None = None, cleanup: bool = True):
		"""
		Initialize sandbox executor.

		Args:
			workdir: Optional working directory (creates temp dir if None)
			cleanup: Whether to cleanup workdir on exit
		"""
		if workdir is None:
			self.workdir = Path(tempfile.mkdtemp(prefix='browser_use_sandbox_'))
			self._should_cleanup = cleanup
		else:
			self.workdir = Path(workdir)
			self.workdir.mkdir(parents=True, exist_ok=True)
			self._should_cleanup = False

		logger.info(f'🚀 Sandbox executor initialized at: {self.workdir}')

	def __del__(self):
		"""Cleanup temporary directory if needed."""
		if self._should_cleanup and self.workdir.exists():
			try:
				shutil.rmtree(self.workdir)
				logger.debug(f'Cleaned up sandbox directory: {self.workdir}')
			except Exception as e:
				logger.warning(f'Failed to cleanup sandbox directory {self.workdir}: {e}')

	async def execute_python_code(
		self,
		code: str,
		setup_code: str = '',
		timeout: int = 60,
		env: dict[str, str] | None = None,
	) -> ExecutionResult:
		"""
		Execute Python code in sandbox.

		Args:
			code: Python code to execute
			setup_code: Optional setup code to run before main code
			timeout: Execution timeout in seconds
			env: Optional environment variables

		Returns:
			ExecutionResult with execution details
		"""
		import time
		import tempfile

		start_time = time.time()

		# Combine setup and main code
		full_code = f"""
{setup_code}

# Main code
{code}
"""

		test_file = None
		try:
			# Create a temporary Python file in a temp directory (not in workdir to avoid persistence)
			with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tmp_file:
				test_file = Path(tmp_file.name)
				tmp_file.write(full_code)

			# Prepare environment
			exec_env = os.environ.copy()
			if env:
				exec_env.update(env)

			# Execute code in subprocess
			try:
				import sys

				python_executable = sys.executable
				process = await asyncio.create_subprocess_exec(
					python_executable,
					str(test_file),
					cwd=str(self.workdir),
					env=exec_env,
					stdout=asyncio.subprocess.PIPE,
					stderr=asyncio.subprocess.PIPE,
				)

				try:
					stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
				except asyncio.TimeoutError:
					process.kill()
					await process.wait()
					return ExecutionResult(
						success=False,
						return_code=-1,
						error=f'Execution timeout after {timeout}s',
						duration=time.time() - start_time,
					)

				stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ''
				stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ''
				return_code = process.returncode

				duration = time.time() - start_time

				# Find files created during execution (only user-created files, not our temp file)
				files_created = []
				if self.workdir.exists():
					for file_path in self.workdir.rglob('*'):
						if file_path.is_file():
							rel_path = file_path.relative_to(self.workdir)
							files_created.append(str(rel_path))

				success = return_code == 0

				result = ExecutionResult(
					success=success,
					stdout=stdout_text,
					stderr=stderr_text,
					return_code=return_code,
					duration=duration,
					files_created=files_created,
					error=stderr_text if not success else None,
				)

				logger.info(f'📊 Code execution: {"✅ SUCCESS" if success else "❌ FAILED"} ({duration:.2f}s)')
				if stdout_text:
					logger.info(f'📤 STDOUT ({len(stdout_text)} chars):')
					logger.info(stdout_text[:500] + ('...' if len(stdout_text) > 500 else ''))
				if stderr_text:
					logger.info(f'📤 STDERR ({len(stderr_text)} chars):')
					logger.info(stderr_text[:500] + ('...' if len(stderr_text) > 500 else ''))
				if files_created:
					logger.info(f'📁 Files created: {", ".join(files_created)}')

				return result

			except FileNotFoundError:
				return ExecutionResult(
					success=False,
					return_code=-1,
					error='Python interpreter not found. Ensure Python is in PATH.',
					duration=time.time() - start_time,
				)
			finally:
				# Clean up temporary file
				if test_file and test_file.exists():
					try:
						test_file.unlink()
					except Exception as e:
						logger.debug(f'Failed to cleanup temp file {test_file}: {e}')

		except Exception as e:
			return ExecutionResult(
				success=False,
				return_code=-1,
				error=f'Sandbox execution error: {str(e)}',
				duration=time.time() - start_time,
			)

	async def execute_with_browser_use_context(
		self,
		code: str,
		timeout: int = 120,
	) -> ExecutionResult:
		"""
		Execute code with real browser-use context (actual browser functions).

		Args:
			code: Python code to execute
			timeout: Execution timeout in seconds

		Returns:
			ExecutionResult with execution details
		"""
		# Setup code that imports and initializes real browser-use
		setup_code = """
import asyncio
import json
import sys
from pathlib import Path

from browser_use import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.code_use import create_namespace
import tempfile

# User code will be executed here
async def run_code():
    try:
        # Create temporary user directory for browser isolation
        temp_user_dir = Path(tempfile.mkdtemp(prefix='sandbox_browser_'))
        
        # Initialize browser with temporary user directory
        profile = BrowserProfile(user_data_dir=str(temp_user_dir))
        browser = BrowserSession(browser_profile=profile)
        
        try:
            await browser.start()
            
            # Create namespace with all browser control functions
            namespace = create_namespace(browser)
            
            # Extract functions from namespace for direct access
            globals().update(namespace)
            
            # Now user code runs here with real browser functions
"""

		end_code = """
        finally:
            # Cleanup browser
            try:
                await browser.stop()
            except Exception as e:
                print(f"Browser cleanup warning: {{e}}")
            # Cleanup temp directory
            try:
                import shutil
                shutil.rmtree(temp_user_dir, ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        import traceback
        print(f"Error during execution: {{e}}")
        traceback.print_exc()
        raise

if __name__ == "__main__":
    asyncio.run(run_code())
"""

		# Wrap code in async function with proper indentation
		indented_code = '\n'.join('            ' + line if line.strip() else line for line in code.split('\n'))
		wrapped_code = setup_code + indented_code + end_code

		return await self.execute_python_code(wrapped_code, timeout=timeout)

	def save_code(self, code: str, filename: str | None = None, with_browser_context: bool = True) -> Path:
		"""
		Save code to be executed to a file.

		Args:
			code: The Python code to save
			filename: Optional custom filename (without extension). If None, uses timestamp.
			with_browser_context: If True, wraps code in browser-use context for standalone execution.

		Returns:
			Path to the saved file

		Example:
			```python
		        executor = SandboxExecutor()
		        file_path = executor.save_code(code="print('Hello, World!')", filename='my_code')
		        print(f'Saved to: {file_path}')
			```
		"""
		# Wrap code in browser-use context if requested
		if with_browser_context:
			setup_code = """
import asyncio
import json
import sys
from pathlib import Path

from browser_use import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.code_use import create_namespace
import tempfile

async def run_code():
    try:
        temp_user_dir = Path(tempfile.mkdtemp(prefix='sandbox_browser_'))
        profile = BrowserProfile(user_data_dir=str(temp_user_dir))
        browser = BrowserSession(browser_profile=profile)
        
        try:
            await browser.start()
            namespace = create_namespace(browser)
            globals().update(namespace)
            
"""
			end_code = """
        finally:
            try:
                await browser.stop()
            except Exception as e:
                print(f"Browser cleanup warning: {{e}}")
            try:
                import shutil
                shutil.rmtree(temp_user_dir, ignore_errors=True)
            except Exception:
                pass
    except Exception as e:
        import traceback
        print(f"Error during execution: {{e}}")
        traceback.print_exc()
        raise

if __name__ == "__main__":
    asyncio.run(run_code())
"""
			indented_code = '\n'.join('            ' + line if line.strip() else line for line in code.split('\n'))
			code = setup_code + indented_code + end_code

		# Save in workdir/code/ subdirectory
		executed_code_dir = self.workdir / 'code'
		executed_code_dir.mkdir(exist_ok=True)

		# Create filename
		if filename is None:
			timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
			filename = f'user_code_{timestamp}'

		# Ensure .py extension
		if not filename.endswith('.py'):
			filename = f'{filename}.py'

		file_path = executed_code_dir / filename
		file_path.write_text(code, encoding='utf-8')
		logger.info(f'💾 Saved user code to: {file_path}')

		return file_path

	async def run_code_directly(
		self,
		code: str,
		timeout: int = 60,
		env: dict[str, str] | None = None,
	) -> ExecutionResult:
		"""
		Run user code directly without browser-use setup (plain Python execution).

		Args:
			code: Python code to execute
			timeout: Execution timeout in seconds
			env: Optional environment variables

		Returns:
			ExecutionResult with execution details

		Example:
			```python
		        executor = SandboxExecutor()
		        result = await executor.run_code_directly(code="print('Hello from sandbox!')")
		        if result.success:
		            print(f'Output: {result.stdout}')
			```
		"""
		return await self.execute_python_code(code, setup_code='', timeout=timeout, env=env)
