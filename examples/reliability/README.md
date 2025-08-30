# Reliability Examples

This directory contains examples focused on **maximum reliability** for browser-use automation. These examples demonstrate techniques to ensure consistent, error-free execution in production environments.

## Examples

### 1. Step-by-Step Reliable (`step_by_step_reliable.py`)
**Focus: Maximum reliability with comprehensive validation**

- 🧠 **OpenAI o3 model** for superior reasoning
- 🌡️ **Zero temperature** for deterministic behavior
- 📋 **Step-by-step prompts** with numbered instructions
- ✅ **Loading validation** after each action
- 🔄 **Enhanced error handling** and retries
- 🎥 **GIF generation** for debugging
- 👁️ **High-detail vision** for accurate validation

**Use Case**: Critical automation requiring 99%+ success rate
**Expected Behavior**: Comprehensive validation and detailed error reporting

## Configuration Patterns

### Reliability Optimization Techniques

1. **LLM Configuration**:
   ```python
   llm = ChatOpenAI(
       model='o3',                       # Most capable model
       temperature=0.0,                  # Deterministic responses
       timeout=120,                      # Extended timeout
   )
   ```

2. **Browser Settings**:
   ```python
   browser_profile=BrowserProfile(
       headless=False,                   # Visible for debugging
       wait_between_actions=2.0,         # Longer waits for stability
       viewport={'width': 1920, 'height': 1080},  # Full HD
       deterministic_rendering=False,    # Keep disabled for performance
   )
   ```

3. **Agent Settings**:
   ```python
   agent = Agent(
       flash_mode=False,                 # Full system prompt
       use_thinking=True,                # Enable reasoning
       max_actions_per_step=3,           # Conservative action limit
       max_failures=5,                   # More retries
       retry_delay=10,                   # Longer retry delay
       step_timeout=180,                 # Extended timeouts
       vision_detail_level='high',       # High accuracy
       validate_output=True,             # Enable validation
   )
   ```

## Reliability Features

### Step-by-Step Execution
The example demonstrates a comprehensive approach to reliable automation:

1. **Explicit Validation Points**:
   - Wait for page load completion
   - Validate element visibility
   - Confirm action success
   - Take screenshots for verification

2. **Error Handling Strategy**:
   - Retry failed actions with delay
   - Detailed error reporting
   - Graceful degradation
   - Debug information collection

3. **Loading Validation**:
   ```
   - Wait for the page to fully load (look for indicators)
   - Validate: Confirm expected elements are visible
   - Validate: Check page title and content
   - Report any issues encountered
   ```

### System Message Enhancement
```python
extend_system_message="""
RELIABILITY PROTOCOL:
- Always wait for pages to fully load before taking actions
- Validate each action's success before proceeding
- If an element is not found, wait 3-5 seconds and retry
- Report step completion status explicitly
- Prioritize accuracy and completeness over speed
"""
```

## Task Structure

The reliable task example follows this pattern:

```
RELIABILITY PRIORITY: Execute each step carefully and validate completion.

STEP-BY-STEP EXECUTION PLAN:

1. [Action Description]
   - Wait for [specific condition]
   - Validate: [specific check]
   - Report: [completion status]

2. [Next Action]
   - [Detailed instructions]
   - Validate: [expected outcome]
   
CRITICAL REQUIREMENTS:
- After each step, explicitly state "Step X completed successfully"
- If any step fails, wait 5 seconds and retry once
- Always wait for loading indicators to disappear
```

## Performance vs Reliability Trade-offs

| Aspect | Reliability Focus | Speed Focus |
|--------|------------------|-------------|
| Temperature | 0.0 (deterministic) | 0.1-0.2 (faster) |
| Wait Times | 2.0s (stable) | 0.0-0.1s (fast) |
| Retries | 5 attempts | 1-2 attempts |
| Timeouts | 180s (extended) | 30s (quick) |
| Actions/Step | 3 (conservative) | 8-10 (aggressive) |
| Vision Detail | High (accurate) | Low (fast) |
| Browser Mode | Visible (debug) | Headless (speed) |

## Monitoring and Debugging

### Built-in Reliability Features

1. **GIF Generation**: Visual record of execution for debugging
2. **Detailed Logging**: Comprehensive step-by-step logs
3. **Error Screenshots**: Automatic capture on failures
4. **Validation Reports**: Explicit success/failure reporting
5. **Cost Tracking**: Monitor LLM usage for optimization

### Debugging Workflow

1. **Review Generated GIF**: Visual debugging of execution flow
2. **Analyze Logs**: Detailed step-by-step execution logs
3. **Check Screenshots**: Error state visualization
4. **Validate Environment**: Network, browser, and API connectivity
5. **Adjust Timeouts**: Increase for slower environments

## Usage Guidelines

### When to Use Reliability Focus

- **Production environments** with SLA requirements
- **Financial or critical business processes**
- **Compliance-required automation**
- **Complex multi-step workflows**
- **Environments with network instability**

### Environment Setup

1. **Stable Network**: Ensure reliable internet connectivity
2. **Adequate Resources**: Sufficient RAM and CPU for browser
3. **Persistent Profile**: Use consistent browser profile
4. **Monitoring**: Set up logging and alerting

### Best Practices

1. **Test Thoroughly**: Validate in staging environment first
2. **Monitor Metrics**: Track success rates and failure patterns
3. **Gradual Rollout**: Start with low-risk scenarios
4. **Fallback Plans**: Design manual intervention procedures
5. **Regular Updates**: Keep browser and dependencies updated

## Getting Started

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Set up environment:
   ```bash
   export OPENAI_API_KEY="your-api-key"
   ```

3. Run the reliable example:
   ```bash
   python examples/reliability/step_by_step_reliable.py
   ```

4. Review results:
   - Check console output for step-by-step progress
   - Review generated GIF for visual validation
   - Analyze any error reports or failures

## Success Metrics

- **Success Rate**: Target 95%+ for production use
- **Error Recovery**: Automatic retry and recovery
- **Execution Time**: Consistent timing within acceptable range
- **Data Accuracy**: 100% accuracy in extracted information
- **Debugging Info**: Complete audit trail for failures