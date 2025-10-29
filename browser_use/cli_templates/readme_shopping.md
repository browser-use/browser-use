# Browser-Use Shopping Automation

E-commerce automation example using browser-use with structured output (Pydantic models).

## What This Does

This template demonstrates:
- **Structured Output** with Pydantic models (`GroceryItem`, `GroceryCart`)
- **E-commerce Automation** - adds items to Instacart shopping cart
- **Interactive Input** - prompts for shopping items
- **CDP Browser Connection** - uses Chrome with remote debugging

## Setup

### 1. Set Up API Key

Copy the example environment file and add your API key:

```bash
cp .env.example .env
```

Edit `.env` and add your Browser-Use API key:
```
BROWSER_USE_API_KEY=your-key-here
```

Get your key at: https://cloud.browser-use.com/dashboard/settings?tab=api-keys&new

### 2. Install Dependencies

```bash
uv sync
```

This installs `browser-use` and all required dependencies (including `pydantic`, `python-dotenv`).

### 3. Launch Chrome with Debugging

The script requires Chrome running with remote debugging enabled on port 9222.

**Run the launcher script:**
```bash
python launch_chrome_debug.py
```

This will:
- Close any existing Chrome instances
- Copy your Chrome profile to an automation directory (preserves logins)
- Launch Chrome with remote debugging on port 9222

**Keep this terminal window open!** Closing it will close Chrome.

## Usage

In a **separate terminal**, run the shopping script:

```bash
uv run browser_use_shopping.py
```

You'll be prompted to enter items to add to your cart (comma-separated):
```
What items would you like to add to cart (comma-separated)? milk, eggs, bread
```

The agent will:
1. Navigate to Instacart
2. Search for each item
3. Add matching items to cart
4. Return structured results with item details (name, price, brand, URL)

## How It Works

### Pydantic Models

The script uses Pydantic models to define structured output:

```python
class GroceryItem(BaseModel):
    name: str
    price: float
    brand: str | None
    size: str | None
    url: str

class GroceryCart(BaseModel):
    items: list[GroceryItem]
```

### Agent Configuration

The agent uses `output_model_schema` to return structured data:

```python
agent = Agent(
    browser=browser,
    llm=llm,
    task=task,
    output_model_schema=GroceryCart,  # Returns GroceryCart object
)
```

### Accessing Results

Results are accessed via `result.structured_output`:

```python
result = await agent.run()
if result and result.structured_output:
    cart = result.structured_output  # GroceryCart instance
    for item in cart.items:
        print(f'{item.name}: ${item.price}')
```

## Customization

### Change the Store

Edit the task prompt to use a different e-commerce site:
```python
task = """
Search for items on [YourStore]...
"""
```

### Modify the Data Model

Add or remove fields in the Pydantic models:
```python
class GroceryItem(BaseModel):
    name: str
    price: float
    rating: float | None = None  # Add rating
    # ... other fields
```

## Troubleshooting

**Chrome won't launch?**
- Make sure Google Chrome is installed
- Update the Chrome path in `launch_chrome_debug.py` if needed

**Can't connect to CDP?**
- Ensure `launch_chrome_debug.py` is running
- Check that port 9222 isn't in use by another process

**Agent can't find items?**
- The website structure may have changed
- Try adjusting the task prompt to be more specific

## Learn More

- [Browser-Use Documentation](https://docs.browser-use.com)
- [Structured Output Guide](https://docs.browser-use.com/customize/agent/output-format)
- [Pydantic Documentation](https://docs.pydantic.dev)
