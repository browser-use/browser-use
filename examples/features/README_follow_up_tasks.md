# Follow-up Tasks Examples

This directory contains examples demonstrating how to use follow-up tasks with persistent browser sessions in browser-use.

## Key Concept: `keep_alive=True`

The critical setting for follow-up tasks is `keep_alive=True` in the `BrowserProfile`. This prevents the browser from closing when a task completes, allowing you to add new tasks to the same session.

## Examples

### 1. `reddit_follow_up_example.py`
**Perfect recreation of your CLI scenario:**
- Go to Reddit → agent calls `done()` → browser stays open
- Add follow-up task: "What's the first post?"
- Agent continues with same session

```python
# Key pattern:
browser_session = BrowserSession(
    browser_profile=BrowserProfile(keep_alive=True)
)

# First task
agent = Agent(task="go to reddit", browser_session=browser_session)
await agent.run()  # Completes, browser stays open

# Follow-up task
agent.add_new_task("what's the first post")
await agent.run()  # Continues with same browser
```

### 2. `interactive_session.py`
**Build your own interactive loop:**
- User types tasks one by one
- Browser persists between all tasks
- Great for custom chat interfaces

### 3. `follow_up_tasks.py` (existing)
**Basic follow-up example** (existing file)

## CLI Already Supports This!

The **CLI interactive mode already does exactly what you want**:

```bash
$ browser-use
> go to reddit
[Agent works and calls done(), browser stays open]
✅ Task completed!

> what's the first post
[Agent continues with same browser session]
✅ Task completed!
```

The CLI uses `keep_alive=True` by default and calls `agent.add_new_task()` for subsequent tasks.

## How It Works

1. **Browser Session with `keep_alive=True`**
   ```python
   browser_session = BrowserSession(
       browser_profile=BrowserProfile(keep_alive=True)
   )
   ```

2. **First Task**
   ```python
   agent = Agent(task="initial task", browser_session=browser_session)
   await agent.run()  # Browser stays open after completion
   ```

3. **Follow-up Tasks**
   ```python
   agent.add_new_task("follow-up task")
   await agent.run()  # Same browser, new task
   ```

4. **Cleanup** (when done with all tasks)
   ```python
   await browser_session.kill()  # Manually close browser
   ```

## Key Points

- ✅ **CLI already supports this pattern** - no changes needed
- ✅ **`agent.add_new_task()` exists** - programmatic API available  
- ✅ **`keep_alive=True`** - browser persistence is built-in
- ✅ **Session reuse** - all cookies, localStorage, DOM state preserved
- ✅ **Same tab or new tabs** - depends on actions taken

## Use Cases

- **Interactive chat interfaces** - User asks follow-up questions
- **Multi-step automation** - Complete workflows across multiple tasks
- **Testing scenarios** - Set up state, then test different paths
- **Data extraction pipelines** - Navigate to site, then extract different data points
- **Research workflows** - Go to site, then explore different aspects

## Running the Examples

```bash
# Reddit follow-up example (demonstrates exact CLI pattern)
python examples/features/reddit_follow_up_example.py

# Interactive session (type your own tasks)
python examples/features/interactive_session.py

# Original follow-up example  
python examples/features/follow_up_tasks.py
```

## Configuration Tips

```python
# Recommended browser profile for follow-up tasks
BrowserProfile(
    keep_alive=True,        # Essential: don't close browser after tasks
    headless=False,         # True for server environments
    user_data_dir='~/.config/browseruse/profiles/persistent',  # Reuse profiles
)
```