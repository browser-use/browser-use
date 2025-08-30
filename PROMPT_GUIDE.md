# Browser-Use AI Agent Prompt Guide

A comprehensive guide for effectively prompting the browser-use AI agent to perform web automation tasks.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Available Actions & Tools](#available-actions--tools)
3. [Prompting Best Practices](#prompting-best-practices)
4. [Step-by-Step Task Structure](#step-by-step-task-structure)
5. [Common Use Cases](#common-use-cases)
6. [Action Reference](#action-reference)
7. [Custom Actions](#custom-actions)
8. [Error Handling](#error-handling)
9. [Advanced Techniques](#advanced-techniques)

## Quick Start

The browser-use agent is an AI that can autonomously interact with web browsers. You simply provide a task description, and it will perform the necessary actions to complete it.

### Basic Example
```python
from browser_use import Agent, ChatOpenAI

task = "Search Google for 'what is browser automation' and tell me the top 3 results"
agent = Agent(task=task, llm=ChatOpenAI(model='gpt-4.1-mini'))
await agent.run()
```

## Available Actions & Tools

The browser-use agent has access to these built-in actions:

### Navigation Actions
- **`search_google`** - Search queries on Google
- **`go_to_url`** - Navigate to specific URLs
- **`go_back`** - Navigate back in browser history
- **`wait`** - Wait for specified seconds (max 10)

### Element Interaction Actions
- **`click_element_by_index`** - Click on interactive elements
- **`input_text`** - Type text into input fields
- **`upload_file_to_element`** - Upload files to form elements
- **`scroll`** - Scroll pages or specific elements
- **`send_keys`** - Send keyboard shortcuts and special keys
- **`scroll_to_text`** - Scroll to specific text on page

### Content Extraction Actions
- **`extract_structured_data`** - Extract specific information from pages using AI

### Dropdown Actions
- **`get_dropdown_options`** - Get available options from dropdowns
- **`select_dropdown_option`** - Select specific dropdown options

### Tab Management Actions
- **`switch_tab`** - Switch between browser tabs
- **`close_tab`** - Close specific tabs

### File System Actions
- **`write_file`** - Create/write files (.md, .txt, .json, .csv, .pdf)
- **`read_file`** - Read file contents
- **`replace_file_str`** - Replace text in files

### Task Completion
- **`done`** - Mark task as complete (when using structured output)

## Prompting Best Practices

### 1. Be Specific and Clear
✅ **Good**: "Go to https://example.com, find the contact form, fill in Name: 'John Doe', Email: 'john@example.com', and submit it"

❌ **Bad**: "Go to some website and fill out a form"

### 2. Break Down Complex Tasks
For complex workflows, structure your prompt with clear steps:

```
Task: Research Python web scraping libraries

Steps:
1. Search Google for "best Python web scraping libraries 2024"
2. Find a reputable article about this topic
3. Extract the top 3 recommended libraries
4. For each library, visit its GitHub page and extract:
   - Name and description
   - GitHub stars
   - Main features
5. Create a comparison summary
```

### 3. Specify Expected Output Format
Always tell the agent how you want results presented:

```
Present the information in this format:
Quote 1: "[quote text]" - Author: [author name] - Tags: [tag1, tag2, ...]
Quote 2: "[quote text]" - Author: [author name] - Tags: [tag1, tag2, ...]
```

### 4. Handle Edge Cases
Include instructions for common issues:

```
Important considerations:
- If an item is out of stock, find a suitable alternative
- If the page requires login, use these credentials: username/password
- If age verification is needed, remove alcoholic products
- Wait for elements to load before interacting
```

### 5. Reference Actions by Name
When using custom actions, reference them explicitly:

```
Steps:
1. Go to login page
2. If prompted for 2FA code:
   2.1. Use the get_2fa_code action to retrieve the code
   2.2. Submit the code from get_2fa_code action

Considerations:
- ALWAYS use the get_2fa_code action for 2FA codes
- NEVER extract codes from the page manually
- NEVER use any other method to get 2FA codes
```

## Step-by-Step Task Structure

### Template for Complex Tasks

```
### Task Title: [Brief description]

**Objective:**
[Clear statement of what needs to be accomplished]

**Important Notes:**
- [Key constraints or requirements]
- [Special handling instructions]

---

### Step 1: [Action Name]
- [Specific instruction 1]
- [Specific instruction 2]

### Step 2: [Action Name]
- [Specific instruction 1]
- [Specific instruction 2]

#### Sub-steps if needed:
1.1. [Detailed sub-action]
1.2. [Detailed sub-action]

---

### Step 3: [Validation/Output]
- [What to check or verify]
- [How to present results]

**Expected Output:**
[Specify exact format for results]
```

### Example: E-commerce Shopping Task

```
### Task: Complete Online Grocery Shopping

**Objective:**
Visit grocery website, add specific items to cart, and complete checkout

**Important:**
- Don't buy more than needed for each item
- If items are unavailable, find suitable alternatives
- Minimum order is $50

---

### Step 1: Navigation
- Go to https://grocery-site.com
- Verify login status

### Step 2: Shopping
Add these items to cart:
- 2 liters milk
- 1 kg carrots
- Bread (whole wheat)
- 6 eggs

### Step 3: Cart Review
- Check cart contents and total price
- If under $50, add basic staples to reach minimum

### Step 4: Checkout
- Proceed to checkout
- Select delivery window (within current week)
- Use credit card payment

### Step 5: Confirmation
Output summary including:
- Final items purchased
- Total cost
- Delivery time selected
```

## Common Use Cases

### 1. Data Extraction
```python
task = """
Go to https://quotes.toscrape.com/ and extract:
- First 5 quotes on the page
- Author of each quote  
- Tags for each quote

Use extract_structured_data action with query: "first 5 quotes with authors and tags"

Format as:
Quote 1: "[text]" - Author: [name] - Tags: [tag1, tag2]
"""
```

### 2. Form Automation
```python
task = """
Go to https://httpbin.org/forms/post and fill contact form:
- Customer name: John Doe
- Telephone: 555-123-4567
- Email: john.doe@example.com
- Size: Medium
- Comments: Test submission

Submit form and report the response.
"""
```

### 3. Research Tasks
```python
task = """
Research topic: "AI code assistants"

1. Search Google for "best AI code assistants 2024"
2. Visit top 3 result articles
3. For each article, extract key AI tools mentioned
4. Visit official website for top 3 tools
5. Extract for each tool:
   - Name and company
   - Key features
   - Pricing (if available)
   - User ratings/reviews

Create comparison table with findings.
"""
```

### 4. Multi-Step Workflows
```python
task = """
E-commerce price comparison workflow:

1. Search "wireless headphones under $100" on Amazon
2. Note top 3 products with prices
3. Search same products on Best Buy
4. Compare prices and availability
5. Create summary table:
   Product | Amazon Price | Best Buy Price | Best Deal
   
Save results to comparison.md file using write_file action.
"""
```

## Action Reference

### Navigation Actions

#### `search_google(query: str)`
Search Google with natural language queries.
```python
# The agent will use this action when you say:
"Search Google for 'python web scraping tutorials'"
```

#### `go_to_url(url: str, new_tab: bool = False)`
Navigate to specific URLs.
```python
# Usage in prompts:
"Go to https://example.com"
"Open https://github.com in a new tab"
```

#### `go_back()`
Navigate back in browser history.
```python
# Usage in prompts:
"Go back to the previous page"
```

#### `wait(seconds: int = 3)`
Wait for page loading or elements to appear.
```python
# Usage in prompts:
"Wait 5 seconds for the page to load"
"Wait for elements to appear before continuing"
```

### Element Interaction

#### `click_element_by_index(index: int, while_holding_ctrl: bool = False)`
Click on interactive elements identified by index numbers.
```python
# Usage in prompts:
"Click the submit button"
"Click the login link while holding Ctrl to open in new tab"
```

#### `input_text(index: int, text: str, clear_existing: bool = True)`
Type text into input fields.
```python
# Usage in prompts:
"Enter 'john@example.com' in the email field"
"Type the message without clearing existing text"
```

#### `scroll(down: bool = True, num_pages: float = 1.0, frame_element_index: int = None)`
Scroll pages or specific elements.
```python
# Usage in prompts:
"Scroll down to see more content"
"Scroll up half a page"
"Scroll within the search results container"
```

### Content Extraction

#### `extract_structured_data(query: str, extract_links: bool = False)`
Extract specific information from web pages using AI.
```python
# Usage in prompts:
"Extract all product prices from this page"
"Get the article title, author, and publication date"
"Extract all links from the navigation menu" (with extract_links=True)
```

**Important Notes:**
- Use for specific information retrieval from page content
- Don't use for getting interactive elements (use browser state instead)
- One extraction per page state is sufficient
- If extraction fails due to anti-spam protection, use manual browsing instead

### File Operations

#### `write_file(file_name: str, content: str, append: bool = False)`
Create or write files. Supports .md, .txt, .json, .csv, .pdf formats.
```python
# Usage in prompts:
"Save the extracted data to results.csv"
"Create a summary report in summary.md"
"Append new findings to existing notes.txt"
```

#### `read_file(file_name: str)`
Read file contents from the file system.
```python
# Usage in prompts:
"Read the previous results from data.json"
"Check what's in the todo.md file"
```

## Custom Actions

When using custom actions (functions you've added with `@controller.action`), reference them explicitly in your prompts:

### Example: 2FA Integration
```python
# Custom action definition:
@controller.action('Get 2FA code when OTP is required')
async def get_2fa_code():
    # Implementation here
    pass

# Usage in prompts:
task = """
Steps:
1. Go to login page and enter credentials
2. If prompted for 2FA:
   2.1. Use the get_2fa_code action to retrieve the code
   2.2. Submit the code from get_2fa_code action

Constraints:
- ALWAYS use get_2fa_code action for 2FA codes
- NEVER extract codes from the page
- NEVER use any other method for 2FA
"""
```

### Example: Human-in-the-Loop
```python
# Custom action:
@controller.action('Ask human for help')
def ask_human(question: str):
    return ActionResult(extracted_content=input(f"{question} > "))

# Usage in prompts:
"If you encounter any unclear choices, use the ask_human action to get clarification"
```

## Error Handling

### Common Issues and Solutions

#### 1. Element Not Found
```python
# Good prompt structure:
"Wait for the page to fully load, then look for the submit button. If not visible, scroll down to find it."
```

#### 2. Page Loading Issues
```python
# Include wait instructions:
"After clicking submit, wait 3 seconds for the response page to load before extracting results."
```

#### 3. Alternative Paths
```python
# Provide fallback options:
"Try to find the 'Sign In' button. If not found, look for 'Login' or 'Account' links instead."
```

#### 4. Data Validation
```python
# Include validation steps:
"After adding items to cart, verify the total count matches the shopping list before proceeding to checkout."
```

## Advanced Techniques

### 1. Conditional Logic
```python
task = """
1. Check if user is already logged in
2. If not logged in:
   2.1. Click login button
   2.2. Enter credentials
   2.3. Handle 2FA if prompted
3. If already logged in, proceed directly to dashboard
4. Continue with main task...
"""
```

### 2. Data Aggregation
```python
task = """
Collect product information from multiple pages:

1. Start at category page
2. For each product (up to 10):
   2.1. Click product link
   2.2. Extract: name, price, rating, features
   2.3. Go back to category page
   2.4. Move to next product
3. Compile all data into structured table
4. Save results to products.csv using write_file action
"""
```

### 3. Dynamic Content Handling
```python
task = """
Handle infinite scroll content:

1. Go to social media feed
2. Scroll down repeatedly until no new content loads
3. After each scroll, wait 2 seconds for content to load
4. Extract all post titles and authors
5. Continue until reaching end or 50 posts collected
"""
```

### 4. Multi-Site Workflows
```python
task = """
Cross-platform price comparison:

1. Search for "laptop model XYZ" on Amazon
2. Note the price and availability
3. Open new tab for Best Buy
4. Search for same laptop model
5. Compare prices and shipping options
6. Repeat for 2-3 more retail sites
7. Create comparison table with all findings
"""
```

### 5. File-Based State Management
```python
task = """
Long-running research project:

1. Read existing progress from research_notes.md
2. Continue from where last session ended
3. For each new finding:
   3.1. Extract relevant data
   3.2. Append to research_notes.md using write_file with append=True
4. Update progress tracker in notes
5. Save final summary to completed_research.md
"""
```

## Tips for Effective Prompting

### 1. Use Clear Action Words
- "Navigate to..." instead of "Go to..."
- "Extract the following information..." instead of "Get data..."
- "Click the submit button" instead of "Submit the form"

### 2. Specify Element Identification
- "Click the blue 'Add to Cart' button"
- "Enter text in the search box at the top of the page"
- "Select 'Premium' from the pricing dropdown"

### 3. Include Validation Steps
- "Verify the item was added to cart before proceeding"
- "Check that the form submission was successful"
- "Confirm the page has loaded completely"

### 4. Handle Dynamic Content
- "Wait for search results to appear"
- "Scroll until all products are visible"
- "Let the page finish loading before extracting data"

### 5. Provide Context
- "This is an e-commerce site where..."
- "The form requires all fields to be filled..."
- "This site uses lazy loading for images..."

Remember: The more specific and structured your prompts, the better the agent will perform. Always test with simple tasks first, then gradually increase complexity as you become familiar with the agent's capabilities.