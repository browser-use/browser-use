# Browser User Data Directory

Browser-use supports persistent browser sessions through the use of a user data directory. This allows you to:

- Maintain login sessions between browser runs
- Preserve cookies, site settings, and other browser state
- Use different browser profiles for different automation tasks
- Avoid repetitive login workflows

## Basic Usage

To use a persistent browser session, specify a `user_data_dir` when creating a `BrowserConfig`:

```python
from browser_use.browser.browser import Browser, BrowserConfig

# Create browser config with user_data_dir
config = BrowserConfig(
    headless=False,
    user_data_dir="/path/to/your/user_data_dir"
)

# Create browser with this config
browser = Browser(config=config)
```

The browser will use this directory to store all profile data, which will persist between browser sessions.  
Only one browser at a time can be running with this `user_data_dir`, make sure to close any browsers using it before starting `browser-use`.

## Using Profile Directories (Chrome/Chromium only)

For Chrome and Chromium browsers, you can also specify a specific profile within the user data directory:

```python
from browser_use.browser.browser import Browser, BrowserConfig

# Create browser config with user_data_dir and profile_directory
config = BrowserConfig(
    headless=False,
    user_data_dir="/path/to/your/user_data_dir",
    profile_directory="Profile 1",  # or "Default", "Profile 2", etc.
    browser_class="chromium"  # Must use chromium for profile_directory
)

# Create browser with this config
browser = Browser(config=config)
```

This allows you to maintain separate browser profiles with different cookies, settings, and state.

## Common Use Cases

### Maintaining Login Sessions

One of the most common uses for persistent browser sessions is to maintain login state across automation runs:

```python
import asyncio
import os
from browser_use.browser.browser import Browser, BrowserConfig

async def main():
    # Define persistent directory for user data
    user_data_dir = os.path.expanduser("~/.browser-use/my-automation")
    os.makedirs(user_data_dir, exist_ok=True)
    
    config = BrowserConfig(
        headless=False,
        user_data_dir=user_data_dir
    )
    
    browser = Browser(config=config)
    context = await browser.new_context()
    
    # Your automation tasks here...
    # Login sessions will be preserved between runs
    
    await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Using Multiple Profiles

You can create and use multiple browser profiles for different purposes:

```python
import asyncio
import os
from browser_use.browser.browser import Browser, BrowserConfig

async def run_with_profile(profile_name):
    user_data_dir = os.path.expanduser("~/.browser-use/profiles")
    os.makedirs(user_data_dir, exist_ok=True)
    
    config = BrowserConfig(
        headless=False,
        user_data_dir=user_data_dir,
        profile_directory=profile_name,
        browser_class="chromium"
    )
    
    browser = Browser(config=config)
    context = await browser.new_context()
    
    # Perform tasks with this specific profile
    
    await browser.close()

async def main():
    # Work profile
    await run_with_profile("Work")
    
    # Personal profile
    await run_with_profile("Personal")
    
    # Testing profile
    await run_with_profile("Testing")

if __name__ == "__main__":
    asyncio.run(main())
```

## Important Notes

1. For security reasons, never use your main browser's user data directory for automation.
2. Always create a separate directory specifically for your automation tasks.
3. The `profile_directory` parameter only works with Chrome/Chromium browsers.
4. If multiple instances of the browser try to use the same user data directory simultaneously, you may encounter errors.
5. When using `user_data_dir`, be cautious with headless mode as some features may behave differently.

## Examples

See the example scripts for more detailed usage:

- [Basic User Data Directory Example](../../examples/browser/user_data_dir_example.py)
- [Profile Directory Example](../../examples/browser/profile_directory_example.py) 