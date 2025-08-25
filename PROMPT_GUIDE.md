# 🎯 Browser-Use Prompt Guide: How to Get Maximum Accuracy

This guide teaches you how to write effective prompts for browser-use agents to achieve high accuracy and reliable automation.

## 📋 Table of Contents

1. [Quick Start: The 5-Step Prompt Formula](#quick-start-the-5-step-prompt-formula)
2. [Step-by-Step Prompting for High Accuracy](#step-by-step-prompting-for-high-accuracy)
3. [Troubleshooting: When Your Agent Gets Stuck](#troubleshooting-when-your-agent-gets-stuck)
4. [Available Tools Reference](#available-tools-reference)
5. [Advanced Examples](#advanced-examples)

---

## 🚀 Quick Start: The 5-Step Prompt Formula

For maximum accuracy, structure your prompts using this proven formula:

```
1. **Clear Objective**: What you want to accomplish
2. **Step-by-Step Instructions**: Detailed sequence of actions
3. **Success Criteria**: How to know when done
4. **Error Handling**: What to do if things go wrong
5. **Output Format**: How to present results
```

### ✅ Good Example:
```python
task = """
**Objective**: Find and save information about the top 5 AI companies

**Steps**:
1. Go to Google and search for "top AI companies 2024"
2. Click on the first reliable source (avoid ads)
3. Extract company names, founding year, and key products
4. Save results to a file called "ai_companies.md"

**Success Criteria**: File contains 5 companies with complete information

**If Problems Occur**:
- If a page doesn't load, wait 5 seconds and refresh
- If results are incomplete, try a different search term
- If no good sources appear, try "leading artificial intelligence companies"

**Output**: Confirm completion with total companies found and file location
"""
```

---

## 📈 Step-by-Step Prompting for High Accuracy

### Step 1: Define Your Objective Clearly

❌ **Vague**: "Help me with shopping"
✅ **Clear**: "Add specific grocery items to cart on Migros.ch and complete checkout with TWINT payment"

### Step 2: Break Down Into Specific Actions

❌ **Too General**: "Find some information about companies"
✅ **Specific Steps**:
```
1. Navigate to LinkedIn.com
2. Search for "AI startup companies"
3. Click on the Companies tab
4. Extract the first 10 company names and descriptions
5. Save to companies.json file
```

### Step 3: Specify Data Requirements

When you need structured data, be explicit about the format:

```python
task = """
Extract product information from Amazon search results:

**Required Fields for Each Product**:
- Product name
- Price (in USD)
- Rating (out of 5 stars)
- Number of reviews
- Prime eligible (yes/no)

**Format**: Save as JSON array with these exact field names
**Quantity**: Extract data for first 10 products only
"""
```

### Step 4: Handle Authentication & Credentials

```python
task = """
**Login Required**: Use these credentials if login is needed:
- Username: user@example.com
- Password: SecurePass123

**Important**: Only login if absolutely necessary for the task
"""
```

### Step 5: Specify Error Recovery

```python
task = """
**Error Handling**:
- If page takes >10 seconds to load: refresh and try again
- If element not found: scroll down to load more content
- If captcha appears: try to solve it, or skip to next item
- If login fails: continue with public access only
"""
```

---

## 🔧 Troubleshooting: When Your Agent Gets Stuck

### Problem: Agent Waits Too Long or Gets Stuck

**Solution**: Tell the agent explicitly to wait and move on:

```python
task = """
If any page takes more than 10 seconds to load:
1. Use the wait action for 5 seconds
2. Refresh the page
3. If still not loaded, skip to the next step

**Explicit Wait Command**: Use `wait(seconds=5)` between actions if pages are slow
"""
```

### Problem: Agent Doesn't Use the Right Tools

**Solution**: Explicitly specify which tools to use:

```python
task = """
**Required Tools to Use**:
- Use `send_keys` for keyboard shortcuts (e.g., Ctrl+A to select all)
- Use `extract_structured_data` to get all product information from listings
- Use `scroll` to load more content before extracting data
- Use `input_text` for form fields, then `send_keys("Enter")` to submit

**Example**: When filling a search form:
1. Use `input_text(index=1, text="search query")`
2. Use `send_keys("Enter")` or click the search button
"""
```

### Problem: Incomplete Data Extraction

**Solution**: Use the extract_structured_data tool properly:

```python
task = """
**Data Extraction Strategy**:
1. First, scroll to the bottom of the page to load ALL content
2. Then use `extract_structured_data` with query: "all product names, prices, and ratings"
3. Set `extract_links=True` if you need URLs
4. Don't call extract_structured_data multiple times on the same page state

**Example Query**: "Extract all job listings with title, company, location, salary, and application link"
"""
```

---

## 🛠️ Available Tools Reference

Here are the key tools available in the [Controller Service](browser_use/controller/service.py):

### Navigation Tools
- `go_to_url(url, new_tab=False)` - Navigate to a webpage
- `go_back()` - Go back in browser history
- `search_google(query)` - Search Google with a query
- `switch_tab(url/tab_id)` - Switch between browser tabs
- `close_tab(tab_id)` - Close a specific tab

### Interaction Tools
- `click_element_by_index(index, while_holding_ctrl=False)` - Click on elements
- `input_text(index, text, clear_existing=True)` - Type into input fields
- `send_keys(keys)` - Send keyboard shortcuts (e.g., "Control+a", "Enter", "Escape")
- `scroll(down=True, num_pages=1.0, frame_element_index=None)` - Scroll pages
- `upload_file_to_element(index, path)` - Upload files

### Data Tools
- `extract_structured_data(query, extract_links=False)` - Extract semantic data from pages
- `get_dropdown_options(index)` - Get dropdown menu options
- `select_dropdown_option(index, text)` - Select from dropdown menus

### Utility Tools
- `wait(seconds=3)` - Wait for pages to load (max 10 seconds)
- `write_file(file_name, content)` - Save data to files (.md, .txt, .json, .csv, .pdf)
- `read_file(file_name)` - Read saved files

---

## 💡 Advanced Examples

### Example 1: E-commerce Product Research

```python
task = """
**Objective**: Research laptop prices on Amazon and create a comparison report

**Detailed Steps**:
1. Go to Amazon.com
2. Search for "gaming laptops under $1500"
3. Scroll down 3 times to load at least 30 products
4. Use extract_structured_data with query: "laptop name, price, rating, number of reviews, key specifications"
5. Save results to "laptop_comparison.json"

**Data Requirements**:
- Extract exactly: name, price, star rating, review count, RAM, storage, GPU
- Format as JSON array with consistent field names
- Include at least 20 products

**Error Handling**:
- If Amazon blocks: try Best Buy or Newegg
- If search returns few results: modify search to "gaming laptop" only
- If page loads slowly: use wait(5) between scroll actions

**Success Criteria**: JSON file with 20+ laptops, all required fields populated
"""
```

### Example 2: Form Automation with Structured Data

```python
task = """
**Objective**: Fill out job application forms for software engineer positions

**Step-by-Step Process**:
1. Go to company careers page: https://company.com/careers
2. Search for "software engineer" positions
3. For each relevant position:
   a. Click "Apply Now"
   b. Fill personal information using these details:
      - Name: John Smith
      - Email: john.smith@email.com
      - Phone: +1-555-0123
   c. Upload resume file: "resume.pdf"
   d. Use send_keys("Tab") to navigate between fields efficiently
   e. Submit application

**Required Tools Usage**:
- `input_text()` for text fields
- `send_keys("Tab")` for field navigation
- `upload_file_to_element()` for resume upload
- `click_element_by_index()` for buttons
- `extract_structured_data()` to verify application was submitted

**Error Recovery**:
- If upload fails: ensure file path is correct, try different file input
- If form validation errors: read error messages and correct fields
- If page redirects unexpectedly: use go_back() and retry

**Output**: List of companies applied to with application status
"""
```

### Example 3: Data Extraction with Pagination

```python
task = """
**Objective**: Extract all customer reviews from a product page

**Methodology**:
1. Navigate to product page
2. Scroll to reviews section
3. Load ALL reviews by:
   a. Scrolling to bottom of reviews
   b. Clicking "Load More" or "Next Page" buttons
   c. Repeat until no more reviews load
4. Extract structured data: "reviewer name, rating, review text, review date"
5. Save to "reviews.csv"

**Critical Instructions**:
- MUST scroll until ALL reviews are loaded before extraction
- Use extract_structured_data only ONCE after all content is loaded
- If pagination buttons exist, click them until disabled
- Wait 3 seconds between page loads

**Data Quality**:
- Minimum 50 reviews required
- Include review dates for recency analysis
- Filter out promotional/fake-looking reviews

**Tools Sequence**:
1. scroll(down=True, num_pages=2)
2. click_element_by_index() on "Load More" buttons
3. wait(3) between loads
4. extract_structured_data() at the end only
"""
```

### Example 4: Multi-Tab Workflow

```python
task = """
**Objective**: Compare prices across multiple shopping sites

**Multi-Tab Strategy**:
1. Open Amazon.com in tab 1
2. Open Best Buy in new tab (use while_holding_ctrl=True when clicking)
3. Open Newegg in new tab
4. For each tab:
   a. Switch to tab using switch_tab()
   b. Search for "RTX 4080 graphics card"
   c. Extract top 5 results with prices
   d. Save tab-specific results

**Tab Management**:
- Use switch_tab(url="amazon.com") to switch by URL
- Or switch_tab(tab_id="1234") if you know the tab ID
- Keep track of which tab contains which site
- Use close_tab() for unused tabs to save memory

**Final Step**: Combine all results into price_comparison.json
"""
```

---

## 🎯 Mental Model: How Browser-Use Works

Think of browser-use as a human assistant who:

1. **Sees the page** through browser_state (like looking at a screen)
2. **Interacts** using mouse clicks and keyboard input
3. **Remembers** what happened in previous steps
4. **Extracts information** by reading the entire page content
5. **Saves work** to files for later use

### Key Principles:

- **Only interact with visible elements** - if you don't see it in browser_state, scroll first
- **Wait for pages to load** - use wait() action when content is loading
- **Extract data efficiently** - scroll to load everything, then extract once
- **Handle dynamic content** - pages change after interactions, adapt accordingly

---

## 🔍 Common Patterns That Work Well

### Pattern 1: Search → Filter → Extract
```python
"""
1. Search for broad term
2. Apply filters to narrow results
3. Scroll to load all filtered content
4. Extract structured data once
"""
```

### Pattern 2: Navigate → Interact → Verify
```python
"""
1. Navigate to target page
2. Perform required interactions
3. Verify success by checking page state or extracting confirmation
"""
```

### Pattern 3: Loop Through Items
```python
"""
For each item in a list:
1. Click on item to open details
2. Extract required information
3. Go back to list
4. Continue to next item
"""
```

---

## ⚠️ Common Pitfalls to Avoid

### ❌ Don't Do This:
- **Vague objectives**: "Help me shop online"
- **Missing error handling**: No plan for when things go wrong
- **Assuming page state**: Not checking if elements are visible
- **Over-extracting**: Calling extract_structured_data multiple times on same page
- **Ignoring timing**: Not waiting for dynamic content to load

### ✅ Do This Instead:
- **Specific goals**: "Add these 10 items to cart and checkout with PayPal"
- **Robust error handling**: "If item not found, try alternative search terms"
- **Check visibility**: "Scroll down if needed elements are not visible"
- **Efficient extraction**: "Scroll to load all content, then extract once"
- **Proper timing**: "Wait 3 seconds after each page load"

---

## 🎓 Pro Tips for Advanced Users

### 1. Use Keyboard Shortcuts Efficiently
```python
# Instead of multiple clicks, use keyboard shortcuts
task = """
Use send_keys for efficiency:
- send_keys("Control+a") to select all text
- send_keys("Control+c") to copy
- send_keys("Control+v") to paste
- send_keys("Tab") to navigate between fields
- send_keys("Enter") to submit forms
"""
```

### 2. Optimize Data Extraction
```python
# Load everything first, then extract
task = """
Data extraction strategy:
1. Scroll to bottom: scroll(down=True, num_pages=10)
2. Wait for content: wait(3)
3. Extract everything: extract_structured_data("all product details")
4. Set extract_links=True only if you need URLs
"""
```

### 3. Handle Dynamic Content
```python
task = """
For dynamic/infinite scroll pages:
1. Scroll gradually: scroll(down=True, num_pages=0.5)
2. Wait for new content: wait(2)
3. Repeat until no new content loads
4. Then extract all data at once
"""
```

### 4. File Operations
```python
task = """
Working with files:
- Save structured data: write_file("results.json", json_content)
- Upload files: upload_file_to_element(index=5, path="document.pdf")
- Supported formats: .md, .txt, .json, .csv, .pdf
- PDF files: write content in markdown format, auto-converts to PDF
"""
```

---

## 🆘 Troubleshooting Guide

### Issue: Agent Waits Forever

**Problem**: Agent seems stuck or waiting indefinitely

**Solutions**:
1. **Add explicit wait commands**:
   ```python
   "If page is loading, use wait(5) then continue"
   ```

2. **Set timeouts**:
   ```python
   "If any action takes >10 seconds, move to next step"
   ```

3. **Use refresh strategy**:
   ```python
   "If page doesn't respond, refresh and retry once"
   ```

### Issue: Wrong Tools Being Used

**Problem**: Agent chooses inefficient or wrong tools

**Solution**: **Explicitly specify tools**:
```python
task = """
**Required Tool Usage**:
- Use `send_keys("Enter")` after typing in search boxes
- Use `extract_structured_data()` for getting page content, not clicking
- Use `scroll()` before extraction to load all content
- Use `click_element_by_index()` only for buttons and links
- Use `input_text()` for typing into form fields

**Example Tool Sequence**:
1. input_text(index=2, text="search term")
2. send_keys("Enter")
3. wait(3)
4. scroll(down=True, num_pages=3)
5. extract_structured_data("product names and prices")
"""
```

### Issue: Incomplete Data Extraction

**Problem**: Missing information or partial results

**Solution**: **Comprehensive extraction strategy**:
```python
task = """
**Complete Data Extraction Process**:
1. First scroll to load ALL content:
   - scroll(down=True, num_pages=5)
   - wait(2) between scrolls
   - Continue until page bottom reached

2. Then extract with detailed query:
   - Query: "all visible product names, exact prices, star ratings, review counts, availability status"
   - Set extract_links=True if URLs needed
   - Extract only ONCE per page state

3. Verify completeness:
   - Check if extracted count matches visible count
   - If missing data, scroll more and re-extract
"""
```

### Issue: Authentication Problems

**Problem**: Can't access protected content

**Solution**: **Smart authentication approach**:
```python
task = """
**Authentication Strategy**:
1. Try accessing content without login first
2. If login required, use provided credentials:
   - Username: [your-username]
   - Password: [your-password]
3. If login fails, continue with publicly available content
4. Never attempt login without explicit credentials
"""
```

---

## 🧰 Available Tools Reference

For complete tool documentation, see the [Controller Service](browser_use/controller/service.py).

### Core Navigation
| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `go_to_url` | Navigate to webpage | `url`, `new_tab=False` |
| `search_google` | Google search | `query` (be specific, not vague) |
| `go_back` | Browser back button | None |
| `wait` | Pause execution | `seconds` (max 10) |

### Element Interaction
| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `click_element_by_index` | Click elements | `index`, `while_holding_ctrl=False` |
| `input_text` | Type into fields | `index`, `text`, `clear_existing=True` |
| `send_keys` | Keyboard shortcuts | `keys` (e.g., "Control+a", "Enter") |
| `scroll` | Scroll pages | `down=True`, `num_pages=1.0` |

### Data Extraction
| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `extract_structured_data` | Get page content | `query`, `extract_links=False` |
| `get_dropdown_options` | List dropdown choices | `index` |
| `select_dropdown_option` | Choose from dropdown | `index`, `text` |

### File Operations
| Tool | Purpose | Supported Formats |
|------|---------|-------------------|
| `write_file` | Save content | .md, .txt, .json, .csv, .pdf |
| `read_file` | Load saved files | All text formats |
| `upload_file_to_element` | Upload to forms | Any file type |

---

## 🎯 Real-World Example: Complete E-commerce Workflow

Here's a comprehensive example that demonstrates all best practices:

```python
import asyncio
from browser_use import Agent, ChatOpenAI

task = """
**Objective**: Research and compare wireless headphones, then save top 5 recommendations

**Detailed Step-by-Step Process**:

### Phase 1: Data Collection
1. **Amazon Research**:
   - Go to Amazon.com
   - Search for "wireless bluetooth headphones"
   - Apply filters: $50-$200 price range, 4+ stars
   - Scroll down 5 times to load at least 50 products
   - Use extract_structured_data with query: "headphone name, exact price, star rating, number of reviews, key features, brand"

2. **Best Buy Research**:
   - Open Best Buy in new tab (use while_holding_ctrl=True)
   - Switch to Best Buy tab
   - Search for same term
   - Apply similar filters
   - Extract same data structure

### Phase 2: Data Processing
3. **Create Comparison**:
   - Combine data from both sources
   - Find products that appear on both sites
   - Calculate average ratings and price differences
   - Save to "headphone_comparison.json"

4. **Generate Report**:
   - Create "headphone_report.md" with:
     * Top 5 recommendations
     * Price comparison table
     * Pros/cons for each
     * Best value pick

### Tools to Use Explicitly:
- `scroll(down=True, num_pages=0.5)` for gradual loading
- `extract_structured_data(query="detailed product info", extract_links=False)`
- `send_keys("Control+t")` for new tabs if needed
- `wait(3)` between major page changes
- `write_file()` for saving results

### Error Handling:
- If Amazon blocks: try incognito mode approach or skip to Best Buy only
- If extraction incomplete: scroll more and re-extract
- If products don't match between sites: use brand + model name matching
- If file save fails: try different filename

### Success Criteria:
- JSON file with 20+ products from each site
- Markdown report with clear recommendations
- At least 5 products found on both sites for comparison

### Expected Output:
"Successfully created headphone comparison with X products from Amazon and Y products from Best Buy. Top recommendation: [Product Name] at $[Price] based on [criteria]. Files saved: headphone_comparison.json, headphone_report.md"
"""

agent = Agent(task=task, llm=ChatOpenAI(model="gpt-4.1-mini"))
await agent.run()
```

---

## 🎪 Quick Reference Cheat Sheet

### ✅ High-Accuracy Prompt Checklist:
- [ ] Clear, specific objective stated
- [ ] Step-by-step instructions provided
- [ ] Required data fields specified
- [ ] Error handling included
- [ ] Tool usage explicitly mentioned
- [ ] Success criteria defined
- [ ] Output format specified

### 🛠️ Essential Tool Patterns:
```python
# Search and extract pattern
"1. search_google('specific query')"
"2. scroll(down=True, num_pages=3)"  
"3. extract_structured_data('what you want')"

# Form filling pattern
"1. input_text(index=X, text='data')"
"2. send_keys('Tab')"  # Move to next field
"3. send_keys('Enter')"  # Submit form

# Data loading pattern
"1. scroll(down=True, num_pages=5)"  # Load content
"2. wait(3)"  # Let it settle
"3. extract_structured_data()"  # Get everything once
```

### 🚨 When Agent Gets Stuck:
1. Add `wait(5)` commands
2. Specify exact tools to use
3. Add refresh/retry logic
4. Break complex tasks into smaller steps

---

## 📚 Additional Resources

- **Examples**: Check the [examples](examples/) folder for more use cases
- **Discord Community**: Join our [Discord](https://link.browser-use.com/discord) for help and inspiration
- **Documentation**: Full docs at [docs.browser-use.com](https://docs.browser-use.com)
- **Awesome Prompts**: See [awesome-prompts](https://github.com/browser-use/awesome-prompts) repo for more examples

---

*Made with ❤️ by the Browser-Use team. Happy automating! 🤖*