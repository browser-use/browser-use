# Example Testing Workflow

This workflow automatically tests all examples in the `examples/` directory on every release to ensure they continue to work correctly.

## Features

- **Automatic Discovery**: Finds all Python files in the examples directory
- **Configurable Exclusions**: Exclude specific directories (like `api/`, `integrations/`) that may require special setup
- **Failure Tolerance**: Only fails the workflow if there are too many failures or critical examples fail
- **Timeout Protection**: Prevents examples from hanging indefinitely
- **Detailed Reporting**: Provides comprehensive summaries and creates GitHub issues on failures

## Configuration

The workflow is configured via `.github/workflows/example-test-config.json`:

```json
{
  "excluded_directories": ["api", "integrations"],
  "timeout_minutes": 10,
  "max_consecutive_failures": 3,
  "critical_examples": [
    "examples/simple.py",
    "examples/getting_started/01_basic_search.py",
    "examples/getting_started/02_form_filling.py"
  ],
  "optional_examples": [
    "examples/use-cases/shopping.py",
    "examples/features/parallel_agents.py"
  ]
}
```

### Configuration Options

- **`excluded_directories`**: Array of directory names to exclude from testing
- **`timeout_minutes`**: Maximum time to allow each example to run
- **`max_consecutive_failures`**: Maximum number of failed examples before the workflow fails
- **`critical_examples`**: Examples that must pass - any failure causes workflow failure
- **`optional_examples`**: Examples that are allowed to fail (for documentation purposes)

## Workflow Behavior

### When Examples Run
- Automatically on every release (`release.published`)
- Manually via workflow dispatch with optional directory exclusions

### Failure Logic
The workflow fails if:
1. **Any critical example fails** - These are essential examples that must always work
2. **Too many examples fail** - If the number of failed examples reaches `max_consecutive_failures`

### Success Logic
The workflow passes if:
- All critical examples pass
- The number of failed examples is below the threshold

## Testing Strategy

The workflow tests examples by:
1. **Running them as-is** - No modifications to example code
2. **Capturing output** - All stdout/stderr is logged
3. **Timeout protection** - Examples are killed if they run too long
4. **Error detection** - Exit codes and exceptions are caught

### Environment Setup
- Python 3.11 virtual environment
- All project dependencies via `uv sync`
- Playwright Chromium browser
- API keys from repository secrets (optional)

## Outputs

### On Success
- Detailed summary in workflow step summary
- List of passed/failed examples
- Execution times and results

### On Failure
- GitHub issue created/updated with failure details
- Example output logs uploaded as artifacts
- Detailed failure analysis in step summary

## Manual Usage

### Run Manually
```bash
# Via GitHub UI: Actions > test-examples > Run workflow
# Optionally specify excluded directories (comma-separated)
```

### Test Locally
```bash
# Set up environment
uv venv --python 3.11
source .venv/bin/activate
uv sync
uvx playwright install chromium

# Test a specific example
python examples/simple.py

# Test with timeout
timeout 600s python examples/getting_started/01_basic_search.py
```

## Troubleshooting

### Common Issues

1. **Examples requiring API keys**
   - Add secrets to repository settings
   - Examples should gracefully handle missing keys

2. **Examples requiring special setup**
   - Add to `excluded_directories` in config
   - Or modify example to be more robust

3. **Flaky examples**
   - Increase `timeout_minutes`
   - Add retry logic to the example
   - Move to `optional_examples` if appropriate

### Debugging Failed Examples
1. Check workflow run logs
2. Download example output artifacts
3. Run example locally with same environment
4. Check if API keys or special setup is needed

## Best Practices for Examples

To ensure examples work well with this testing workflow:

1. **Handle missing dependencies gracefully**
   ```python
   try:
       from optional_package import something
   except ImportError:
       print("Optional package not available, skipping")
       sys.exit(0)
   ```

2. **Handle missing API keys**
   ```python
   api_key = os.getenv('API_KEY')
   if not api_key:
       print("API_KEY not set, skipping example")
       sys.exit(0)
   ```

3. **Use reasonable timeouts**
   ```python
   # Don't run indefinitely
   agent = Agent(task=task, llm=llm)
   await agent.run(max_steps=10)  # Limit steps
   ```

4. **Clean up resources**
   ```python
   try:
       await agent.run()
   finally:
       await browser_session.close()
   ```

## Maintenance

### Adding New Examples
New examples are automatically discovered - no workflow changes needed.

### Excluding Examples
Add directory names to `excluded_directories` in the config file.

### Marking Examples as Critical
Add file paths to `critical_examples` in the config file.

### Adjusting Failure Tolerance
Modify `max_consecutive_failures` in the config file.