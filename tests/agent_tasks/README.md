# Contributing Agent Tasks

Contribute your own agent tasks and we test if the agent solves them for CI testing!

## How to Add a Task

1. Create a new `.yaml` file in this directory (`tests/agent_tasks/`).
2. Use the following format:

```yaml
name: My Task Name
task: Describe the task for the agent to perform
judge_context:
  - List criteria for success, one per line
max_steps: 10
```

## Guidelines
- Be specific in your task and criteria.
- The `judge_context` should list what counts as a successful result.
- The agent's output will be judged by an LLM using these criteria.

## Running the Tests

To run all agent tasks:

```bash
pytest tests/ci/test_agent_real_tasks.py
```

---

Happy contributing! 
