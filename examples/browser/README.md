# Browser Examples

This directory contains examples of how to use the browser-use library for various browser automation tasks.

## Anti-Fingerprinting Examples

The following examples demonstrate how to use the anti-fingerprinting capabilities of browser-use to avoid bot detection:

### 1. Basic Anti-Fingerprinting Example

```python
# anti_fingerprint.py
```

This example shows how to enable anti-fingerprinting in a browser and use it with an agent to navigate to a fingerprinting test site.

### 2. Anti-Fingerprinting Test

```python
# test_anti_fingerprint.py
```

This script creates a browser with anti-fingerprinting enabled and navigates to a fingerprinting test site to check if the browser is detected as a bot.

### 3. Real-World Anti-Fingerprinting Example

```python
# anti_fingerprint_example.py
```

This example demonstrates how to use anti-fingerprinting in a real-world scenario, navigating to a website that uses bot detection and performing actions without being detected.

### 4. Anti-Fingerprinting Comparison

```python
# anti_fingerprint_comparison.py
```

This example creates two browsers - one with anti-fingerprinting enabled and one without - and navigates both to a fingerprinting test site for comparison.

## Other Browser Examples

### 1. Using a Real Browser

```python
# real_browser.py
```

This example shows how to use a real Chrome browser instance for automation.

### 2. Using CDP

```python
# using_cdp.py
```

This example demonstrates how to connect to a running Chrome instance using the Chrome DevTools Protocol (CDP).

## How to Run the Examples

1. Make sure you have installed the browser-use library with the patchright dependency:
   ```
   pip install browser-use
   pip install patchright
   ```

2. Run any example using Python:
   ```
   python examples/browser/anti_fingerprint.py
   ```

## Anti-Fingerprinting Configuration

To enable anti-fingerprinting in your own code, use the following configuration:

```python
from browser_use.browser.browser import Browser, BrowserConfig

browser = Browser(
    config=BrowserConfig(
        headless=False,
        anti_fingerprint=True  # Enable anti-fingerprinting
    )
)
```

This will:
- Use Chrome as the browser channel
- Apply patches to modify browser behavior
- Prevent canvas and audio fingerprinting
- Modify WebGL parameters to mimic a real device
