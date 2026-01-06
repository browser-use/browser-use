# Code-Use Mode

Code-Use Mode is a Notebook-like code execution system for browser automation. Instead of the agent choosing from a predefined set of actions, the LLM writes Python code that gets executed in a persistent namespace with all browser control functions available.

## Problem Solved

**Code-Use Mode solves this** by giving the agent a Python execution environment where it can:
- Store extracted data in variables
- Loop through pages programmatically
- Combine results from multiple extractions
- Process and filter data before saving
- Use conditional logic to decide what to do next
- Output more tokens than the LLM writes

### Namespace
The namespace is initialized with:

**Browser Control Functions:**
- `navigate(url)` - Navigate to a URL
- `click(index)` - Click an element
- `input(index, text)` - Type text
- `scroll(down, pages)` - Scroll the page
- `upload_file(path)` - Upload a file
- `evaluate(code, variables={})` - Execute JavaScript
- `done(text, success, files_to_display=[])` - Mark task complete

**Custom evaluate() Function:**
```python
# Returns values directly, not wrapped in ActionResult
result = await evaluate('''
(function(){
  return Array.from(document.querySelectorAll('.product')).map(p => ({
    name: p.querySelector('.name').textContent,
    price: p.querySelector('.price').textContent
  }))
})()
''')
# result is now a list of dicts, ready to use!
```

**Utilities:**
The agent can just utilize packages like `requests`, `pandas`, `numpy`, `matplotlib`, `BeautifulSoup`, `tabulate`, `csv`, ...

The agent will write code like:

### Step 1: Navigate
```python
# Navigate to first page
await navigate(url='https://example.com/products?page=1')
```
### Step 2 analyse our DOM state and write code to extract the data we need.

```js extract_products
(function(){
    return Array.from(document.querySelectorAll('.product')).map(p => ({
        name: p.querySelector('.name')?.textContent || '',
        price: p.querySelector('.price')?.textContent || '',
        rating: p.querySelector('.rating')?.textContent || ''
    }))
})()
```

```python
# Extract products using JavaScript
all_products = []
for page in range(1, 6):
    if page > 1:
        await navigate(url=f'https://example.com/products?page={page}')

    products = await evaluate(extract_products)
    all_products.extend(products)
    print(f'Page {page}: Found {len(products)} products')
```

### Step 3: Analyse output & save the data to a file
```python
# Save to file
import json
with open('products.json', 'w') as f:
    json.dump(all_products, f, indent=2)

print(f'Total: {len(all_products)} products saved to products.json')
await done(text='Extracted all products', success=True, files_to_display=['products.json'])
```
