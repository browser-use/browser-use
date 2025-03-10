# Supatest - Custom Browser Automation Extension

This package extends the base functionality of `browser-use` to provide enhanced browser automation capabilities with websocket support and custom action handling.

## Features

- **Websocket Integration**: Send and receive actions through websocket connections
- **Enhanced DOM Manipulation**: Advanced element finding and state tracking
- **Custom Action Handling**: Register and handle custom browser actions
- **Anti-Detection**: Built-in browser anti-detection mechanisms
- **Cookie Management**: Advanced cookie handling and state management
- **Screenshot Capabilities**: Easy screenshot capture functionality

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```python
from supatest import CustomController

# Initialize controller with websocket support
controller = CustomController(headless=False)

# Execute actions
await controller.execute_action({
    "type": "go_to_url",
    "params": {"url": "https://example.com"}
})

# Get enhanced state
state = controller.get_current_state()
```

### Websocket Integration

```python
import asyncio
from supatest import CustomController

async def main():
    # Initialize with websocket
    controller = CustomController(websocket=ws)

    # Handle incoming message
    await controller.handle_ws_message(message)

    # State will be automatically sent through websocket
    await controller.execute_action(action)

asyncio.run(main())
```

### Custom Actions

```python
from supatest import CustomAgent

agent = CustomAgent()

# Register custom action
def handle_custom_action(action):
    # Custom action logic here
    pass

agent.register_custom_action("custom_action", handle_custom_action)
```

### Enhanced DOM Manipulation

```python
from supatest import CustomDOMManager

dom_manager = CustomDOMManager(driver)

# Find element using multiple identifiers
element = dom_manager.find_element_by_multiple({
    "id": "submit-btn",
    "class": "btn-primary",
    "xpath": "//button[contains(text(), 'Submit')]"
})

# Get detailed element state
state = dom_manager.get_element_state(element)
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
