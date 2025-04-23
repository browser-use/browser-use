<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./static/browser-use-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="./static/browser-use.png">
  <img alt="Shows a black Browser Use Logo in light color mode and a white one in dark color mode." src="./static/browser-use.png"  width="full">
</picture>

<h1 align="center">Enable AI to control your browser 🤖</h1>

[![GitHub stars](https://img.shields.io/github/stars/gregpr07/browser-use?style=social)](https://github.com/gregpr07/browser-use/stargazers)
[![Discord](https://img.shields.io/discord/1303749220842340412?color=7289DA&label=Discord&logo=discord&logoColor=white)](https://link.browser-use.com/discord)
[![Cloud](https://img.shields.io/badge/Cloud-☁️-blue)](https://cloud.browser-use.com)
[![Documentation](https://img.shields.io/badge/Documentation-📕-blue)](https://docs.browser-use.com)
[![Twitter Follow](https://img.shields.io/twitter/follow/Gregor?style=social)](https://x.com/gregpr07)
[![Twitter Follow](https://img.shields.io/twitter/follow/Magnus?style=social)](https://x.com/mamagnus00)
[![Weave Badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fapp.workweave.ai%2Fapi%2Frepository%2Fbadge%2Forg_T5Pvn3UBswTHIsN1dWS3voPg%2F881458615&labelColor=#EC6341)](https://app.workweave.ai/reports/repository/org_T5Pvn3UBswTHIsN1dWS3voPg/881458615)

🌐 Browser-use is the easiest way to connect your AI agents with the browser.

💡 See what others are building and share your projects in our [Discord](https://link.browser-use.com/discord)! Want Swag? Check out our [Merch store](https://browsermerch.com).

🌤️ Skip the setup - try our <b>hosted version</b> for instant browser automation! <b>[Try the cloud ☁︎](https://cloud.browser-use.com)</b>.

# Quick start

With pip (Python>=3.11):

```bash
pip install browser-use
```

For memory functionality (requires Python<3.13 due to PyTorch compatibility):  

```bash
pip install "browser-use[memory]"
```

Install Playwright:
```bash
playwright install chromium
```

Spin up your agent:

```python
from langchain_openai import ChatOpenAI
from browser_use import Agent
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def main():
    agent = Agent(
        task="Compare the price of gpt-4o and DeepSeek-V3",
        llm=ChatOpenAI(model="gpt-4o"),
    )
    await agent.run()

asyncio.run(main())
```

## Advanced Mode

For complex browser automation tasks requiring full Playwright capabilities:

```python
from langchain_openai import ChatOpenAI
from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def main():
    # Enable advanced mode with full Playwright capabilities
    browser_config = BrowserConfig(
        advanced_mode=True,  # Enable JavaScript execution, iframe support, etc.
        headless=False       # Set to True for headless operation
    )
    
    browser = Browser(config=browser_config)
    
    agent = Agent(
        task="Navigate complex web interfaces with iframes and dynamic content",
        llm=ChatOpenAI(model="gpt-4o"),
        browser=browser
    )
    await agent.run()

asyncio.run(main())
```

Add your API keys for the provider you want to use to your `.env` file.

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=
AZURE_OPENAI_API_VERSION=
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
GROK_API_KEY=
NOVITA_API_KEY=
```

## Command-line Flags

The library supports command-line flags for flexible configuration:

```bash
# Basic usage
python examples/advance.py

# With command-line flags
python examples/advance.py --cdp-port 9222 --no-headless --model gpt-4o --task "Your custom task"

# Using Azure OpenAI
python examples/advance.py --use-azure --model gpt-4o

# With screenshots enabled
python examples/advance.py --screenshots --no-headless --advanced-mode
```

Available flags:
- `--cdp-port PORT`: CDP port for browser connection (for connecting to existing browser)
- `--headless/--no-headless`: Run browser in headless/visible mode
- `--advanced-mode/--no-advanced-mode`: Enable/disable advanced Playwright capabilities
- `--model MODEL`: Model to use (default: gpt-4o)
- `--use-azure`: Use Azure OpenAI instead of OpenAI
- `--task "TASK"`: Custom task to perform
- `--screenshots`: Enable taking screenshots during automation
- `--debug`: Enable debug logging

### Complete Command-line Reference

Example scripts support various command-line arguments:

#### advance.py

```bash
python examples/advance.py [options]
```

Options:
- `--use-azure`: Use Azure OpenAI instead of OpenAI
- `--model MODEL`: Specify the model name (default: gpt-4o)
- `--no-headless`: Run in visible browser mode
- `--advanced-mode`: Enable advanced Playwright capabilities
- `--cdp-port PORT`: Specify CDP port for browser connection
- `--screenshots`: Enable taking screenshots during navigation
- `--debug`: Enable debug logging

Example with all options:
```bash
python examples/advance.py --no-headless --advanced-mode --use-azure --model gpt-4o --cdp-port 9222 --screenshots --debug
```

### Screenshot Functionality

The browser-use library provides screenshot capabilities in two ways:
- **Base64 encoded screenshots**: The BrowserContext.take_screenshot() method returns a base64 encoded screenshot (doesn't save to file)
- **File-based screenshots**: Example scripts like advance.py include custom functions to save screenshots to files

When running examples that support screenshots (like advance.py), you must explicitly enable screenshots with the `--screenshots` flag:

```bash
python examples/advance.py --screenshots --no-headless --advanced-mode
```

Screenshots will be saved to `~/screenshots/` directory. The directory will be created if it doesn't exist.

## Environment-Specific Usage

### Local Mac Usage
```bash
# Extract CDP port
CDP_PORT=$(ps -ax | grep -o '\-\-remote-debugging-port=[0-9]\+' | awk -F= '{print $2}' | head -1)

# Run with visible browser window
python examples/advance.py --no-headless --task "Your custom task"

# Run with advanced mode and custom model
python examples/advance.py --no-headless --advanced-mode --model gpt-4o

# For Naver Maps photo navigation on Mac
python examples/advance.py --cdp-port $CDP_PORT --no-headless --advanced-mode --model gpt-4o

# With screenshots enabled
python examples/advance.py --no-headless --advanced-mode --screenshots
```

#### Mac-Specific Screenshot Notes

When running on macOS:
- The screenshots directory is created at `~/screenshots/` using platform-independent paths
- You must explicitly enable screenshots with the `--screenshots` flag
- Screenshots are saved with timestamps and descriptive names
- The directory will be created automatically if it doesn't exist

### Devin/Remote Environment Usage
```bash
# Extract CDP port for connecting to existing browser
CDP_PORT=$(ps aux | grep -o '\-\-remote-debugging-port=[0-9]\+' | awk -F= '{print $2}' | head -1)

# Run with CDP port connection
python examples/advance.py --cdp-port $CDP_PORT --task "Your custom task"

# Run with Azure OpenAI
python examples/advance.py --cdp-port $CDP_PORT --use-azure --model gpt-4o
```

For other settings, models, and more, check out the [documentation 📕](https://docs.browser-use.com).

## Enhanced Features

### Advanced Mode Capabilities

The advanced mode (`advanced_mode=True`) enables full Playwright capabilities:

- **JavaScript Execution**: Run custom JavaScript via page.evaluate() for complex interactions
- **Iframe Support**: Access and traverse nested iframes using page.frames()
- **Enhanced UI Interaction**: Full locator strategy support and React component interaction
- **Korean Language Support**: Improved handling of Korean text elements
- **Dynamic Content Handling**: Better waiting for JavaScript page loads and state changes

#### Enhanced Korean Text Detection

Advanced mode includes specialized methods for Korean websites:

```python
# Example: Using enhanced Korean text detection
await context.get_element_by_korean_text("외부")  # Find element by Korean text
await context.get_naver_photo_elements(search_in_frames=True)  # Find photo elements in Naver Maps
await context.get_element_by_photo_category("외부")  # Find photo category by name
```

#### Iframe Navigation Enhancements

Advanced mode provides improved iframe handling:

```python
# Example: Working with iframes
frames = await context.get_frames()  # Get all frames on the page
place_frame = await context.get_frame_by_url_pattern("pcmap.place.naver.com")  # Find frame by URL pattern
await context.switch_to_frame(place_frame)  # Switch context to specific frame
```

#### Dynamic Element Selection

Advanced mode provides improved methods for handling dynamic elements:

```python
# Example: Using dynamic element selection
# Find elements with retry logic
element = await context.get_element_with_retry(selector=".dynamic-class", 
                                              retry_count=5, 
                                              wait_time=1000)

# Find elements by text content with fuzzy matching
element = await context.get_element_by_text_content("Approximate text", 
                                                   fuzzy_match=True)
```

#### Timing and State Management

Advanced mode includes improved timing and state management:

```python
# Example: Using enhanced timing and state management
# Wait for network to be idle
await context.wait_for_network_idle(timeout=10000)

# Wait for element to be visible with custom timeout
await context.wait_for_element_visible(".selector", timeout=5000)

# Wait for page to finish navigation
await context.wait_for_navigation_complete()
```

#### Screenshots

Advanced mode provides enhanced screenshot capabilities:

```python
# Take a screenshot and get base64 encoded data
screenshot_b64 = await context.take_screenshot(full_page=True)

# In example scripts, enable screenshots with the --screenshots flag
# python examples/advance.py --screenshots --no-headless --advanced-mode [other options]
```

Screenshots will be saved to `~/screenshots/` directory with timestamps and descriptive names. The directory will be created if it doesn't exist.

Example screenshot usage in custom scripts:
```python
# Save a screenshot to a file
page = await context.get_current_page()
await page.screenshot(path="~/screenshots/my_screenshot.png")

# Process a base64 encoded screenshot
import base64
screenshot_b64 = await context.take_screenshot()
screenshot_bytes = base64.b64decode(screenshot_b64)
with open("~/screenshots/decoded_screenshot.png", "wb") as f:
    f.write(screenshot_bytes)
```

### Test with UI

You can test [browser-use with a UI repository](https://github.com/browser-use/web-ui)

Or simply run the gradio example:

```
uv pip install gradio
```

```bash
python examples/ui/gradio_demo.py
```

# Demos

<br/><br/>

[Task](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/shopping.py): Add grocery items to cart, and checkout.

[![AI Did My Groceries](https://github.com/user-attachments/assets/d9359085-bde6-41d4-aa4e-6520d0221872)](https://www.youtube.com/watch?v=L2Ya9PYNns8)

<br/><br/>

Prompt: Add my latest LinkedIn follower to my leads in Salesforce.

![LinkedIn to Salesforce](https://github.com/user-attachments/assets/1440affc-a552-442e-b702-d0d3b277b0ae)

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/use-cases/find_and_apply_to_jobs.py): Read my CV & find ML jobs, save them to a file, and then start applying for them in new tabs, if you need help, ask me.'

https://github.com/user-attachments/assets/171fb4d6-0355-46f2-863e-edb04a828d04

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/browser/real_browser.py): Write a letter in Google Docs to my Papa, thanking him for everything, and save the document as a PDF.

![Letter to Papa](https://github.com/user-attachments/assets/242ade3e-15bc-41c2-988f-cbc5415a66aa)

<br/><br/>

[Prompt](https://github.com/browser-use/browser-use/blob/main/examples/custom-functions/save_to_file_hugging_face.py): Look up models with a license of cc-by-sa-4.0 and sort by most likes on Hugging face, save top 5 to file.

https://github.com/user-attachments/assets/de73ee39-432c-4b97-b4e8-939fd7f323b3

<br/><br/>

## More examples

For more examples see the [examples](examples) folder or join the [Discord](https://link.browser-use.com/discord) and show off your project.

# Vision

Tell your computer what to do, and it gets it done.

## Roadmap

### Agent

- [ ] Improve agent memory (summarize, compress, RAG, etc.)
- [ ] Enhance planning capabilities (load website specific context)
- [ ] Reduce token consumption (system prompt, DOM state)

### DOM Extraction

- [ ] Improve extraction for datepickers, dropdowns, special elements
- [ ] Improve state representation for UI elements

### Rerunning tasks

- [ ] LLM as fallback
- [ ] Make it easy to define workflow templates where LLM fills in the details
- [ ] Return playwright script from the agent

### Datasets

- [ ] Create datasets for complex tasks
- [ ] Benchmark various models against each other
- [ ] Fine-tuning models for specific tasks

### User Experience

- [ ] Human-in-the-loop execution
- [ ] Improve the generated GIF quality
- [ ] Create various demos for tutorial execution, job application, QA testing, social media, etc.

## Contributing

We love contributions! Feel free to open issues for bugs or feature requests. To contribute to the docs, check out the `/docs` folder.

## Local Setup

To learn more about the library, check out the [local setup 📕](https://docs.browser-use.com/development/local-setup).


`main` is the primary development branch with frequent changes. For production use, install a stable [versioned release](https://github.com/browser-use/browser-use/releases) instead.

---

## Cooperations

We are forming a commission to define best practices for UI/UX design for browser agents.
Together, we're exploring how software redesign improves the performance of AI agents and gives these companies a competitive advantage by designing their existing software to be at the forefront of the agent age.

Email [Toby](mailto:tbiddle@loop11.com?subject=I%20want%20to%20join%20the%20UI/UX%20commission%20for%20AI%20agents&body=Hi%20Toby%2C%0A%0AI%20found%20you%20in%20the%20browser-use%20GitHub%20README.%0A%0A) to apply for a seat on the committee.

## Swag

Want to show off your Browser-use swag? Check out our [Merch store](https://browsermerch.com). Good contributors will receive swag for free 👀.

## Citation

If you use Browser Use in your research or project, please cite:

```bibtex
@software{browser_use2024,
  author = {Müller, Magnus and Žunič, Gregor},
  title = {Browser Use: Enable AI to control your browser},
  year = {2024},
  publisher = {GitHub},
  url = {https://github.com/browser-use/browser-use}
}
```

 <div align="center"> <img src="https://github.com/user-attachments/assets/06fa3078-8461-4560-b434-445510c1766f" width="400"/> 
 
[![Twitter Follow](https://img.shields.io/twitter/follow/Gregor?style=social)](https://x.com/gregpr07)
[![Twitter Follow](https://img.shields.io/twitter/follow/Magnus?style=social)](https://x.com/mamagnus00)
 
 </div>

<div align="center">
Made with ❤️ in Zurich and San Francisco
 </div>
