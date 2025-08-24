# Follow-up Tasks Implementation

## Summary

This implementation adds support for follow-up tasks where the agent can wait for user input and then continue execution with the user's response. The feature is implemented using a new `wait_for_user_input` action that pauses the agent execution until user input is received.

## What was implemented

### 1. WaitForUserInputAction Model (`browser_use/controller/views.py`)
- Added a new Pydantic model for the action parameter
- Takes a `question` field to ask the user for input

### 2. Action Registration (`browser_use/controller/service.py`)
- Registered `wait_for_user_input` action in the Controller
- Action returns metadata indicating it's waiting for user input
- Added import for `WaitForUserInputAction`

### 3. Agent Logic (`browser_use/agent/service.py`)
- Modified `multi_act` method to detect wait_for_user_input metadata
- Added logic to pause execution when waiting for user input
- Modified `add_new_task` method to reset waiting flag when user input is received
- Added `is_waiting_for_user_input()` helper method
- Updated execution loop to exit when waiting for user input

### 4. System Prompts (all variants)
- Updated system prompts to document the `wait_for_user_input` action
- Added guidance on when and how to use the action

### 5. Example (`examples/features/follow_up_tasks.py`)
- Updated the example to demonstrate the new functionality
- Shows how to check if agent is waiting for input
- Demonstrates the complete user input collection and resumption flow

## Usage

### In Agent Tasks
The agent can use the `wait_for_user_input` action in any task:

```python
task = '''Search for information about Python web frameworks. 
After finding some initial results, use wait_for_user_input to ask me which specific framework I'd like to learn more about, 
then search for detailed information about that framework.'''
```

### In Application Code
Check if the agent is waiting for user input and handle it:

```python
# Start the agent
result = await agent.run()

# Check if agent is waiting for user input
if agent.is_waiting_for_user_input():
    # Get user input
    user_response = input("Your response: ")
    
    # Continue with user's response
    agent.add_new_task(f"User responded: {user_response}. Continue with the original task.")
    
    # Resume agent execution
    await agent.run()
```

## How it works

1. Agent encounters a task that requires user input
2. Agent calls `wait_for_user_input` action with a question
3. Action returns metadata indicating waiting state
4. Agent execution loop detects the waiting state and pauses
5. Agent returns current history to allow application to check status
6. Application detects waiting state using `is_waiting_for_user_input()`
7. Application collects user input
8. Application calls `add_new_task()` with user response
9. This resets the waiting flag and allows agent to continue
10. Agent resumes execution with the user's input

## Key Features

- **Simple to use**: Just call `wait_for_user_input` with a question
- **Clean integration**: Uses existing `add_new_task` mechanism
- **Flexible**: Can be used at any point in task execution
- **Robust**: Properly handles state management and resumption
- **Compatible**: Works with all existing browser-use functionality

This implementation makes it easy to create interactive workflows where the agent can ask for user guidance when needed, making tasks more collaborative and flexible.