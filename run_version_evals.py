#!/usr/bin/env python3
"""
Run browser-use evaluations across multiple framework versions.

Usage:
    python run_version_evals.py

This script:
1. Creates isolated virtual environments for each version
2. Installs browser-use at that specific version
3. Runs the evaluation tasks
4. Collects and compares results across versions
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


VERSIONS = ["0.11.6", "0.11.7", "0.11.8", "0.11.9"]
BASE_DIR = Path(__file__).parent
EVAL_SCRIPT = BASE_DIR / "tests" / "ci" / "evaluate_tasks.py"
TASK_DIR = BASE_DIR / "tests" / "agent_tasks"


def run_command(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> tuple[int, str, str]:
	"""Run a command and return (returncode, stdout, stderr)."""
	result = subprocess.run(
		cmd,
		cwd=cwd,
		env=env or os.environ.copy(),
		capture_output=True,
		text=True,
	)
	return result.returncode, result.stdout, result.stderr


def create_venv_and_install(version: str, venv_dir: Path) -> bool:
	"""Create a virtual environment and install a specific browser-use version."""
	print(f"\n{'='*60}")
	print(f"Setting up environment for browser-use=={version}")
	print(f"{'='*60}")

	# Create virtual environment
	print(f"  Creating venv at {venv_dir}...")
	returncode, stdout, stderr = run_command([sys.executable, "-m", "venv", str(venv_dir)])
	if returncode != 0:
		print(f"  ERROR: Failed to create venv: {stderr}")
		return False

	# Determine pip path
	pip_path = venv_dir / "bin" / "pip"
	python_path = venv_dir / "bin" / "python"

	# Upgrade pip
	print("  Upgrading pip...")
	returncode, stdout, stderr = run_command([str(pip_path), "install", "--upgrade", "pip", "-q"])
	if returncode != 0:
		print(f"  WARNING: pip upgrade failed: {stderr}")

	# Install browser-use at specific version
	print(f"  Installing browser-use=={version}...")
	returncode, stdout, stderr = run_command([
		str(pip_path), "install", f"browser-use=={version}", "-q"
	])
	if returncode != 0:
		print(f"  ERROR: Failed to install browser-use=={version}: {stderr}")
		return False

	# Install additional dependencies needed for eval
	print("  Installing additional dependencies...")
	returncode, stdout, stderr = run_command([
		str(pip_path), "install", "pyyaml", "python-dotenv", "anyio", "-q"
	])
	if returncode != 0:
		print(f"  WARNING: Some dependencies failed to install: {stderr}")

	# Verify installation
	returncode, stdout, stderr = run_command([
		str(python_path), "-c", "import browser_use; print(browser_use.__version__)"
	])
	if returncode == 0:
		print(f"  Installed version: {stdout.strip()}")
		return True
	else:
		print(f"  ERROR: Could not verify installation: {stderr}")
		return False


def run_eval(version: str, venv_dir: Path) -> dict:
	"""Run the evaluation script for a specific version."""
	print(f"\n{'='*60}")
	print(f"Running eval for browser-use=={version}")
	print(f"{'='*60}")

	python_path = venv_dir / "bin" / "python"

	env = os.environ.copy()
	env["PYTHONPATH"] = str(BASE_DIR)

	# Run the eval script
	returncode, stdout, stderr = run_command(
		[str(python_path), str(EVAL_SCRIPT), str(TASK_DIR)],
		cwd=BASE_DIR,
		env=env,
	)

	# Parse results
	result = {
		"version": version,
		"returncode": returncode,
		"passed": 0,
		"total": 0,
		"details": [],
		"stdout": stdout,
		"stderr": stderr,
	}

	# Extract PASSED and TOTAL from output
	for line in stdout.split("\n"):
		if line.startswith("PASSED="):
			result["passed"] = int(line.split("=")[1])
		elif line.startswith("TOTAL="):
			result["total"] = int(line.split("=")[1])
		elif line.startswith("DETAILED_RESULTS="):
			try:
				result["details"] = json.loads(line.split("=", 1)[1])
			except json.JSONDecodeError:
				pass

	print(f"\n  Version {version}: {result['passed']}/{result['total']} passed")

	return result


def print_summary(results: list[dict]) -> None:
	"""Print a summary comparison of all version results."""
	print("\n" + "=" * 80)
	print(f"{'EVALUATION SUMMARY':^80}")
	print("=" * 80)

	# Header
	print(f"\n{'Version':<12} {'Passed':<10} {'Total':<10} {'Rate':<10}")
	print("-" * 42)

	for r in results:
		rate = f"{r['passed']/r['total']*100:.1f}%" if r['total'] > 0 else "N/A"
		print(f"{r['version']:<12} {r['passed']:<10} {r['total']:<10} {rate:<10}")

	print("\n" + "=" * 80)

	# Detail breakdown by task
	if any(r["details"] for r in results):
		print(f"\n{'TASK-BY-TASK BREAKDOWN':^80}")
		print("=" * 80)

		# Get all task names
		all_tasks = set()
		for r in results:
			for d in r["details"]:
				all_tasks.add(d["task"])

		# Print header
		header = f"{'Task':<30}"
		for r in results:
			header += f" {r['version']:<10}"
		print(header)
		print("-" * (30 + 11 * len(results)))

		# Print each task's results across versions
		for task in sorted(all_tasks):
			row = f"{task[:28]:<30}"
			for r in results:
				task_result = next((d for d in r["details"] if d["task"] == task), None)
				if task_result:
					status = "PASS" if task_result["success"] else "FAIL"
				else:
					status = "N/A"
				row += f" {status:<10}"
			print(row)

	print("\n" + "=" * 80)


def main():
	"""Main entry point."""
	print(f"Browser-Use Multi-Version Eval Runner")
	print(f"Started at: {datetime.now().isoformat()}")
	print(f"Versions to test: {', '.join(VERSIONS)}")
	print(f"Eval script: {EVAL_SCRIPT}")
	print(f"Task directory: {TASK_DIR}")

	# Check prerequisites
	if not EVAL_SCRIPT.exists():
		print(f"ERROR: Eval script not found: {EVAL_SCRIPT}")
		sys.exit(1)

	if not TASK_DIR.exists():
		print(f"ERROR: Task directory not found: {TASK_DIR}")
		sys.exit(1)

	# Check for required API keys
	if not os.environ.get("BROWSER_USE_API_KEY"):
		print("ERROR: BROWSER_USE_API_KEY environment variable not set")
		sys.exit(1)

	if not os.environ.get("GOOGLE_API_KEY"):
		print("ERROR: GOOGLE_API_KEY environment variable not set")
		sys.exit(1)

	# Create temporary directory for venvs
	temp_base = Path(tempfile.mkdtemp(prefix="bu_eval_"))
	print(f"Temp directory: {temp_base}")

	results = []

	try:
		for version in VERSIONS:
			venv_dir = temp_base / f"venv_{version.replace('.', '_')}"

			if create_venv_and_install(version, venv_dir):
				result = run_eval(version, venv_dir)
				results.append(result)
			else:
				results.append({
					"version": version,
					"returncode": -1,
					"passed": 0,
					"total": 0,
					"details": [],
					"error": "Failed to set up environment",
				})

		# Print summary
		print_summary(results)

		# Save results to JSON
		output_file = BASE_DIR / f"eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
		with open(output_file, "w") as f:
			json.dump({
				"timestamp": datetime.now().isoformat(),
				"versions": VERSIONS,
				"results": results,
			}, f, indent=2)
		print(f"\nResults saved to: {output_file}")

	finally:
		# Cleanup
		print(f"\nCleaning up temp directory: {temp_base}")
		shutil.rmtree(temp_base, ignore_errors=True)

	print(f"\nCompleted at: {datetime.now().isoformat()}")


if __name__ == "__main__":
	main()
