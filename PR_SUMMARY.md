# PR: Remove Planner Functionality from Browser-Use

## Overview
This PR removes all planner-related code from the browser-use codebase. The planner functionality was marked as deprecated in v0.3.3+ and is no longer supported. This change cleans up the codebase by removing deprecated code paths and simplifying the agent initialization.

## Changes Made

### Core Agent Components
- **`browser_use/agent/service.py`**: 
  - Removed `planner_llm`, `use_vision_for_planner`, `planner_interval`, `is_planner_reasoning`, and `extend_planner_system_message` parameters from Agent.__init__
  - Removed deprecation warning logic for planner parameters
  - Removed planner-related settings initialization
  - Cleaned up commented planner model setup code
  - Removed planner references from logging and telemetry

- **`browser_use/agent/views.py`**:
  - Removed all planner-related fields from `AgentSettings` class:
    - `use_vision_for_planner`
    - `planner_llm` 
    - `planner_interval`
    - `is_planner_reasoning`
    - `extend_planner_system_message`

- **`browser_use/agent/prompts.py`**:
  - Completely removed `PlannerPrompt` class and all its methods
  - Removed planner system prompt functionality

### Supporting Components
- **`browser_use/cli.py`**:
  - Removed planner display logic from model information panel

- **`browser_use/telemetry/views.py`**:
  - Removed `planner_llm` field from `AgentTelemetryEvent`

### Examples and Documentation
- **`examples/features/planner.py`**: 
  - **DELETED** - Removed entire planner example file

- **`docs/customize/agent-settings.mdx`**:
  - Removed "Run with planner model" section
  - Removed planner parameters documentation
  - Cleaned up parameter lists

- **`docs/customize/system-prompt.mdx`**:
  - Removed "Extend Planner System Prompt" section
  - Simplified documentation structure

### CI/CD and Workflows
- **`.github/workflows/eval.yaml`**:
  - Removed `DEFAULT_PLANNER_INTERVAL` 
  - Removed `PLANNER_INTERVAL` and `PLANNER_MODEL` parameter handling
  - Removed planner-related command line arguments

- **`.github/ISSUE_TEMPLATE/`**:
  - Updated issue templates to remove planner references from log examples

### Evaluation System
- **`eval/service.py`**:
  - Removed `planner_llm` and `planner_interval` parameters from all function signatures:
    - `run_agent_with_browser()`
    - `run_task_with_semaphore()`
    - `run_multiple_tasks()`
    - `run_evaluation_pipeline()`
  - Removed planner argument parser options
  - Removed planner LLM initialization code
  - Updated logging to reflect planner removal
  - Cleaned up function calls to remove planner parameters

## Files Modified
1. `browser_use/agent/service.py`
2. `browser_use/agent/views.py` 
3. `browser_use/agent/prompts.py`
4. `browser_use/cli.py`
5. `browser_use/telemetry/views.py`
6. `docs/customize/agent-settings.mdx`
7. `docs/customize/system-prompt.mdx`
8. `.github/workflows/eval.yaml`
9. `.github/ISSUE_TEMPLATE/1_element_detection_bug.yml`
10. `.github/ISSUE_TEMPLATE/2_bug_report.yml`
11. `eval/service.py`

## Files Deleted
1. `examples/features/planner.py`

## Breaking Changes
⚠️ **This is a breaking change** for users who were still using the deprecated planner parameters:

- `planner_llm` parameter removed from `Agent.__init__()`
- `use_vision_for_planner` parameter removed from `Agent.__init__()`
- `planner_interval` parameter removed from `Agent.__init__()`
- `is_planner_reasoning` parameter removed from `Agent.__init__()`  
- `extend_planner_system_message` parameter removed from `Agent.__init__()`

### Migration Guide
Users who were using planner parameters should:
1. Remove all planner-related parameters from `Agent()` initialization
2. Rely on the improved agent context handling introduced in v0.3.2+
3. Use the main LLM for all planning and reasoning tasks

### Before (deprecated):
```python
agent = Agent(
    task="your task",
    llm=main_llm,
    planner_llm=planner_llm,
    use_vision_for_planner=False,
    planner_interval=4
)
```

### After:
```python
agent = Agent(
    task="your task", 
    llm=main_llm
)
```

## Testing
- All changes maintain backward compatibility except for the documented breaking changes
- The agent's core functionality remains unchanged
- No functional tests were broken as planner was already deprecated

## Rationale
1. **Code Cleanup**: Removes a significant amount of deprecated code that was confusing users
2. **Simplification**: Simplifies agent initialization and reduces parameter complexity
3. **Maintenance**: Eliminates maintenance burden for unused functionality
4. **Performance**: Reduces initialization overhead by removing unused code paths

## Related Issues
This PR addresses the deprecation warnings that were introduced in v0.3.3+ and completes the removal of planner functionality that was no longer supported.