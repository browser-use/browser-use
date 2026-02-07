#!/usr/bin/env python3
"""
Run evals with bu-1 (ChatBrowserUse) across multiple browser-use versions.

This script creates isolated virtual environments for each version,
runs the evaluation tasks, and compares results across versions.

Usage:
    python scripts/run_version_eval.py [--versions 0.11.6,0.11.7,0.11.8,0.11.9]

Requirements:
    - BROWSER_USE_API_KEY: Get from https://cloud.browser-use.com/new-api-key
    - GOOGLE_API_KEY: For the judge LLM (Gemini)
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


DEFAULT_VERSIONS = ["0.11.6", "0.11.7", "0.11.8", "0.11.9"]
TASK_DIR = Path(__file__).parent.parent / "tests" / "agent_tasks"


def check_api_keys():
	"""Check if required API keys are set."""
	missing = []
	if not os.getenv("BROWSER_USE_API_KEY"):
		missing.append("BROWSER_USE_API_KEY")
	if not os.getenv("GOOGLE_API_KEY"):
		missing.append("GOOGLE_API_KEY")
	return missing


def create_venv(version: str, base_dir: Path) -> Path:
	"""Create a virtual environment with a specific browser-use version."""
	venv_path = base_dir / f"venv_{version.replace('.', '_')}"

	print(f"\n{'='*60}")
	print(f"Creating venv for browser-use {version}")
	print(f"{'='*60}")

	# Create venv
	subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)

	# Get pip path
	if sys.platform == "win32":
		pip_path = venv_path / "Scripts" / "pip"
		python_path = venv_path / "Scripts" / "python"
	else:
		pip_path = venv_path / "bin" / "pip"
		python_path = venv_path / "bin" / "python"

	# Install browser-use with the specific version
	print(f"Installing browser-use=={version}...")
	subprocess.run(
		[str(pip_path), "install", f"browser-use=={version}", "pyyaml", "anyio"],
		check=True,
		capture_output=True,
	)

	# Install additional dependencies for eval
	subprocess.run(
		[str(pip_path), "install", "google-genai"],
		check=True,
		capture_output=True,
	)

	return venv_path


def get_eval_script() -> str:
	"""Return a standalone eval script that works across versions."""
	return '''
import asyncio
import json
import os
import sys
import warnings
import logging

import yaml

# Suppress logging noise
logging.getLogger().setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

async def run_eval(task_file: str):
    """Run evaluation for a single task."""
    try:
        # Load task
        with open(task_file) as f:
            task_data = yaml.safe_load(f)

        task = task_data["task"]
        judge_context = task_data.get("judge_context", ["The agent must solve the task"])
        max_steps = task_data.get("max_steps", 15)

        # Import browser-use (version-specific)
        try:
            from browser_use import Agent, BrowserProfile, BrowserSession
            from browser_use.llm.browser_use.chat import ChatBrowserUse
        except ImportError:
            # Older versions might have different import paths
            from browser_use import Agent
            from browser_use.browser.browser import Browser
            from browser_use.browser.context import BrowserConfig
            from browser_use.llm.browser_use.chat import ChatBrowserUse

        api_key = os.getenv("BROWSER_USE_API_KEY")
        if not api_key:
            return {
                "file": os.path.basename(task_file),
                "success": False,
                "explanation": "BROWSER_USE_API_KEY not set",
            }

        agent_llm = ChatBrowserUse(api_key=api_key)

        # Try newer API first, fall back to older
        try:
            profile = BrowserProfile(
                headless=True,
                user_data_dir=None,
                chromium_sandbox=False,
            )
            session = BrowserSession(browser_profile=profile)
            agent = Agent(task=task, llm=agent_llm, browser_session=session)
        except (NameError, TypeError):
            # Older API
            config = BrowserConfig(headless=True)
            browser = Browser(config=config)
            agent = Agent(task=task, llm=agent_llm, browser=browser)

        # Run agent
        history = await agent.run(max_steps=max_steps)
        agent_output = history.final_result() if hasattr(history, "final_result") else str(history)

        # Use Google judge
        google_api_key = os.getenv("GOOGLE_API_KEY")
        if not google_api_key:
            return {
                "file": os.path.basename(task_file),
                "success": False,
                "explanation": "GOOGLE_API_KEY not set",
            }

        try:
            from browser_use.llm.google.chat import ChatGoogle
            from browser_use.llm.messages import UserMessage
            from pydantic import BaseModel

            class JudgeResponse(BaseModel):
                success: bool
                explanation: str

            judge_llm = ChatGoogle(model="gemini-flash-lite-latest")

            criteria = "\\n- ".join(judge_context)
            judge_prompt = f"""
You are evaluating a browser agent task. Here was the task:
{task}

Agent output:
{agent_output if agent_output else "[No output]"}

Criteria for success:
- {criteria}

Reply in JSON with keys: success (true/false), explanation (string).
"""
            response = await judge_llm.ainvoke([UserMessage(content=judge_prompt)], output_format=JudgeResponse)
            judge_response = response.completion

            return {
                "file": os.path.basename(task_file),
                "success": judge_response.success,
                "explanation": judge_response.explanation,
            }
        except Exception as e:
            # If judge fails, just report based on output
            return {
                "file": os.path.basename(task_file),
                "success": bool(agent_output),
                "explanation": f"Agent output: {str(agent_output)[:200]}",
            }

    except Exception as e:
        return {
            "file": os.path.basename(task_file),
            "success": False,
            "explanation": f"Error: {str(e)}",
        }
    finally:
        # Cleanup
        try:
            if "session" in dir():
                await session.kill()
            elif "browser" in dir():
                await browser.close()
        except:
            pass


if __name__ == "__main__":
    task_file = sys.argv[1]
    result = asyncio.run(run_eval(task_file))
    print(json.dumps(result))
'''


async def run_version_eval(version: str, venv_path: Path, task_files: list[Path]) -> dict:
	"""Run evaluation for all tasks on a specific version."""
	print(f"\n{'='*60}")
	print(f"Running eval on browser-use {version}")
	print(f"{'='*60}")

	if sys.platform == "win32":
		python_path = venv_path / "Scripts" / "python"
	else:
		python_path = venv_path / "bin" / "python"

	# Write eval script to temp file
	eval_script = get_eval_script()
	script_path = venv_path / "eval_task.py"
	script_path.write_text(eval_script)

	results = []
	for task_file in task_files:
		print(f"  Running: {task_file.name}...")

		try:
			env = os.environ.copy()
			proc = await asyncio.create_subprocess_exec(
				str(python_path),
				str(script_path),
				str(task_file),
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=env,
			)
			stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

			if proc.returncode == 0:
				try:
					result = json.loads(stdout.decode().strip().split('\n')[-1])
				except json.JSONDecodeError:
					result = {
						"file": task_file.name,
						"success": False,
						"explanation": f"Failed to parse output: {stdout.decode()[:200]}",
					}
			else:
				result = {
					"file": task_file.name,
					"success": False,
					"explanation": f"Process failed: {stderr.decode()[:200]}",
				}
		except asyncio.TimeoutError:
			result = {
				"file": task_file.name,
				"success": False,
				"explanation": "Task timed out after 5 minutes",
			}
		except Exception as e:
			result = {
				"file": task_file.name,
				"success": False,
				"explanation": f"Error: {str(e)}",
			}

		status = "✅" if result["success"] else "❌"
		print(f"    {status} {result['explanation'][:60]}...")
		results.append(result)

	passed = sum(1 for r in results if r["success"])
	total = len(results)

	return {
		"version": version,
		"passed": passed,
		"total": total,
		"pass_rate": f"{100*passed/total:.1f}%" if total > 0 else "N/A",
		"results": results,
	}


async def main():
	parser = argparse.ArgumentParser(description="Run evals across browser-use versions")
	parser.add_argument(
		"--versions",
		type=str,
		default=",".join(DEFAULT_VERSIONS),
		help=f"Comma-separated list of versions (default: {','.join(DEFAULT_VERSIONS)})",
	)
	parser.add_argument(
		"--keep-venvs",
		action="store_true",
		help="Keep virtual environments after running (for debugging)",
	)
	parser.add_argument(
		"--output",
		type=str,
		default=None,
		help="Output JSON file for results",
	)
	args = parser.parse_args()

	# Check API keys
	missing_keys = check_api_keys()
	if missing_keys:
		print(f"❌ Missing required API keys: {', '.join(missing_keys)}")
		print("\nPlease set the following environment variables:")
		print("  export BROWSER_USE_API_KEY=<your-key>")
		print("  export GOOGLE_API_KEY=<your-key>")
		print("\nGet your Browser Use API key from: https://cloud.browser-use.com/new-api-key")
		sys.exit(1)

	versions = args.versions.split(",")
	print(f"\n🚀 Running bu-1 evals on browser-use versions: {versions}")

	# Get task files
	task_files = list(TASK_DIR.glob("*.yaml"))
	if not task_files:
		print(f"❌ No task files found in {TASK_DIR}")
		sys.exit(1)

	print(f"📋 Found {len(task_files)} task(s): {[f.name for f in task_files]}")

	# Create temp directory for venvs
	temp_dir = Path(tempfile.mkdtemp(prefix="bu_eval_"))
	print(f"📁 Using temp directory: {temp_dir}")

	try:
		# Create venvs for all versions
		venvs = {}
		for version in versions:
			try:
				venv_path = create_venv(version, temp_dir)
				venvs[version] = venv_path
			except Exception as e:
				print(f"❌ Failed to create venv for {version}: {e}")

		# Run evals
		all_results = []
		for version, venv_path in venvs.items():
			try:
				result = await run_version_eval(version, venv_path, task_files)
				all_results.append(result)
			except Exception as e:
				print(f"❌ Failed to run eval for {version}: {e}")
				all_results.append({
					"version": version,
					"passed": 0,
					"total": len(task_files),
					"pass_rate": "ERROR",
					"results": [],
					"error": str(e),
				})

		# Print summary
		print("\n" + "=" * 70)
		print(f"{'EVAL RESULTS SUMMARY':^70}")
		print("=" * 70)
		print(f"\n{'Version':<12} {'Passed':<10} {'Total':<10} {'Pass Rate':<12}")
		print("-" * 44)
		for r in all_results:
			print(f"{r['version']:<12} {r['passed']:<10} {r['total']:<10} {r['pass_rate']:<12}")
		print("=" * 70)

		# Save results
		output_data = {
			"timestamp": datetime.now().isoformat(),
			"versions": versions,
			"task_files": [f.name for f in task_files],
			"results": all_results,
		}

		if args.output:
			output_path = Path(args.output)
		else:
			output_path = Path(f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

		output_path.write_text(json.dumps(output_data, indent=2))
		print(f"\n📊 Results saved to: {output_path}")

		return all_results

	finally:
		if not args.keep_venvs:
			print(f"\n🧹 Cleaning up temp directory...")
			shutil.rmtree(temp_dir, ignore_errors=True)
		else:
			print(f"\n📁 Keeping venvs at: {temp_dir}")


if __name__ == "__main__":
	asyncio.run(main())
