#!/usr/bin/env python3
"""
Run evals using Browser Use Cloud API.

This script creates tasks via the Cloud API and tracks their results.
Note: Cloud API runs on the current production version of browser-use.
For version comparison across 0.11.6, 0.11.7, 0.11.8, 0.11.9, use run_version_eval.py instead.

Usage:
    export BROWSER_USE_API_KEY=<your-key>
    python scripts/run_cloud_eval.py

Requirements:
    - BROWSER_USE_API_KEY: Get from https://cloud.browser-use.com/new-api-key
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
import yaml

API_BASE = "https://api.browser-use.com/api/v2"
TASK_DIR = Path(__file__).parent.parent / "tests" / "agent_tasks"


async def create_task(client: httpx.AsyncClient, api_key: str, task: str, max_steps: int = 15) -> dict:
	"""Create a task via Cloud API."""
	response = await client.post(
		f"{API_BASE}/tasks",
		headers={"X-Browser-Use-API-Key": api_key, "Content-Type": "application/json"},
		json={
			"task": task,
			"llm": "browser-use-llm",  # Use bu-1
			"maxSteps": max_steps,
		},
	)
	response.raise_for_status()
	return response.json()


async def get_task(client: httpx.AsyncClient, api_key: str, task_id: str) -> dict:
	"""Get task status and results."""
	response = await client.get(
		f"{API_BASE}/tasks/{task_id}",
		headers={"X-Browser-Use-API-Key": api_key},
	)
	response.raise_for_status()
	return response.json()


async def wait_for_task(client: httpx.AsyncClient, api_key: str, task_id: str, timeout: int = 300) -> dict:
	"""Wait for a task to complete."""
	start = datetime.now()
	while (datetime.now() - start).seconds < timeout:
		task = await get_task(client, api_key, task_id)
		status = task.get("status")
		if status in ("finished", "stopped"):
			return task
		print(f"  Task {task_id[:8]}... status: {status}")
		await asyncio.sleep(5)
	return {"error": "Task timed out", "status": "timeout"}


async def stop_session(client: httpx.AsyncClient, api_key: str, session_id: str):
	"""Stop a session to avoid charges."""
	try:
		await client.patch(
			f"{API_BASE}/sessions/{session_id}",
			headers={"X-Browser-Use-API-Key": api_key, "Content-Type": "application/json"},
			json={"action": "stop"},
		)
	except Exception:
		pass


async def run_eval_task(client: httpx.AsyncClient, api_key: str, task_file: Path) -> dict:
	"""Run a single eval task via Cloud API."""
	print(f"\n  Running: {task_file.name}")

	# Load task definition
	content = task_file.read_text()
	task_data = yaml.safe_load(content)
	task = task_data["task"]
	judge_context = task_data.get("judge_context", ["The agent must solve the task"])
	max_steps = task_data.get("max_steps", 15)

	try:
		# Create task
		create_response = await create_task(client, api_key, task, max_steps)
		task_id = create_response["id"]
		session_id = create_response["sessionId"]
		print(f"    Created task: {task_id[:8]}...")
		print(f"    Session: {session_id[:8]}...")

		# Wait for completion
		result = await wait_for_task(client, api_key, task_id)

		# Stop session
		await stop_session(client, api_key, session_id)

		# Extract results
		success = result.get("isSuccess", False)
		output = result.get("output", "")
		version = result.get("browserUseVersion", "unknown")

		status = "✅" if success else "❌"
		print(f"    {status} Version: {version}, Success: {success}")

		return {
			"file": task_file.name,
			"task_id": task_id,
			"session_id": session_id,
			"success": success,
			"output": output,
			"browser_use_version": version,
			"steps": len(result.get("steps", [])),
		}

	except httpx.HTTPStatusError as e:
		return {
			"file": task_file.name,
			"success": False,
			"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
		}
	except Exception as e:
		return {
			"file": task_file.name,
			"success": False,
			"error": str(e),
		}


async def main():
	parser = argparse.ArgumentParser(description="Run evals via Browser Use Cloud API")
	parser.add_argument("--output", type=str, help="Output JSON file for results")
	args = parser.parse_args()

	api_key = os.getenv("BROWSER_USE_API_KEY")
	if not api_key:
		print("❌ BROWSER_USE_API_KEY not set")
		print("\nGet your API key from: https://cloud.browser-use.com/new-api-key")
		print("Then run: export BROWSER_USE_API_KEY=<your-key>")
		sys.exit(1)

	# Get task files
	task_files = list(TASK_DIR.glob("*.yaml"))
	if not task_files:
		print(f"❌ No task files found in {TASK_DIR}")
		sys.exit(1)

	print(f"\n🚀 Running Cloud evals with bu-1 (browser-use-llm)")
	print(f"📋 Found {len(task_files)} task(s): {[f.name for f in task_files]}")

	# Check account balance
	async with httpx.AsyncClient(timeout=60.0) as client:
		try:
			response = await client.get(
				f"{API_BASE}/billing/account",
				headers={"X-Browser-Use-API-Key": api_key},
			)
			if response.status_code == 200:
				account = response.json()
				credits = account.get("totalCreditsBalanceUsd", 0)
				print(f"💰 Account credits: ${credits:.2f}")
		except Exception:
			pass

		# Run all tasks
		results = []
		for task_file in task_files:
			result = await run_eval_task(client, api_key, task_file)
			results.append(result)

	# Summary
	passed = sum(1 for r in results if r.get("success"))
	total = len(results)

	print("\n" + "=" * 60)
	print(f"{'CLOUD EVAL RESULTS':^60}")
	print("=" * 60)
	print(f"\n{'Task':<30} {'Success':<10} {'Version':<15}")
	print("-" * 55)
	for r in results:
		status = "✅" if r.get("success") else "❌"
		version = r.get("browser_use_version", "N/A")
		print(f"{r['file']:<30} {status:<10} {version:<15}")
	print("=" * 60)
	print(f"\n{'SCORE':^60}")
	print(f"{'*' * 10}  {passed}/{total} PASSED  {'*' * 10}\n")

	# Save results
	output_data = {
		"timestamp": datetime.now().isoformat(),
		"type": "cloud_eval",
		"llm": "browser-use-llm (bu-1)",
		"task_files": [f.name for f in task_files],
		"results": results,
		"passed": passed,
		"total": total,
	}

	if args.output:
		output_path = Path(args.output)
	else:
		output_path = Path(f"cloud_eval_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

	output_path.write_text(json.dumps(output_data, indent=2))
	print(f"📊 Results saved to: {output_path}")

	return results


if __name__ == "__main__":
	asyncio.run(main())
