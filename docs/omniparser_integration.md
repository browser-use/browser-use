# OmniParser Integration

This document describes the integration of Microsoft's OmniParser 2.0 with BrowseUse for enhanced UI element detection.

## Overview

OmniParser is a vision-based UI element detection system that helps identify interactive elements in web pages, especially when traditional DOM-based extraction may miss elements like CAPTCHAs, complex JavaScript widgets, and other challenging UI components.

The integration provides:

- Enhanced detection of CAPTCHA elements
- Better handling of complex UI elements
- A hybrid approach combining DOM-based and vision-based parsing

## When to Use OmniParser

OmniParser is particularly valuable in the following scenarios:

1. **Accessing websites with CAPTCHA protection**: When your agent needs to identify and potentially handle CAPTCHA challenges
2. **Working with complex JavaScript-heavy applications**: When traditional DOM extraction struggles with dynamically generated content
3. **Parsing visually distinct elements**: When important elements are rendered via canvas or other non-standard methods
4. **Handling shadow DOM or iframes**: When important content is hidden in shadow DOM or nested frames
5. **Extracting structured visual information**: When you need to analyze tables, charts, or other visual data structures

## Configuration

The OmniParser integration can be configured using the `BrowserExtractionConfig` class:

```python
from browser_use.browser.config import BrowserExtractionConfig
from browser_use.omniparser.views import OmniParserSettings

# Create configuration
extraction_config = BrowserExtractionConfig(
    omniparser=OmniParserSettings(
        enabled=True,                # Enable OmniParser
        confidence_threshold=0.5,    # Minimum confidence for detection
        captcha_detection=True,      # Enable specialized CAPTCHA detection
        merge_with_dom=True,         # Combine DOM and OmniParser results
        prefer_over_dom=False        # Whether to prefer OmniParser over DOM
    ),
    use_hybrid_extraction=True       # Enable hybrid extraction approach
)

# Use with browser context
browser_context = await browser.create_context(
    config=BrowserContextConfig(
        extraction_config=extraction_config
    )
)
```

## OmniParser Settings

The `OmniParserSettings` class provides the following configuration options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `False` | Enable/disable OmniParser integration |
| `confidence_threshold` | float | `0.5` | Minimum confidence threshold for element detection |
| `weights_dir` | str | `None` | Custom model weights directory (if None, uses default) |
| `prefer_over_dom` | bool | `False` | Whether to prefer OmniParser results over DOM-based results |
| `captcha_detection` | bool | `True` | Enable specialized CAPTCHA detection |
| `merge_with_dom` | bool | `True` | Merge OmniParser results with DOM-based results |
| `use_api` | bool | `False` | Whether to use the hosted API if local installation is not available |

## Usage

The OmniParser integration works automatically when enabled. When browsing with a properly configured browser context, the system will:

1. Extract elements using the traditional DOM-based approach
2. If OmniParser is enabled, process the current screenshot for visual element detection
3. Depending on settings, either merge the results, prefer OmniParser results, or use specialized detection for CAPTCHAs

### Example: Basic Usage

```python
from browser_use.browser import Browser
from browser_use.browser.config import BrowserContextConfig, BrowserExtractionConfig
from browser_use.omniparser.views import OmniParserSettings

# Create browser
browser = await Browser.create()

# Configure with OmniParser enabled
context = await browser.create_context(
    config=BrowserContextConfig(
        extraction_config=BrowserExtractionConfig(
            omniparser=OmniParserSettings(enabled=True),
            use_hybrid_extraction=True
        )
    )
)

# Navigate to a page with CAPTCHAs
await context.goto("https://example.com/login")

# The system will automatically detect CAPTCHAs and other complex UI elements
```

### Example: CAPTCHA Handling

When a CAPTCHA is detected, it will be added to the DOM state with special attributes:

```python
# Elements detected as CAPTCHAs will have these attributes:
# - data-captcha: "true"
# - data-captcha-confidence: "0.95" (confidence score)
# - class: "captcha-element" (added to existing classes)
```

### Example: Extracting Visual Information from GitHub

This example demonstrates how to use OmniParser to extract structured information from GitHub's trending page:

```python
async def extract_visual_information(context):
    """Extract structured information from a visually complex page."""
    # Navigate to GitHub's trending page
    await context.goto("https://github.com/trending")
    
    # OmniParser will automatically enhance the state with visual elements
    state = await context.get_state()
    
    # You can now extract repository information from the state
    # This works even with complex UI elements that might be challenging
    # with traditional DOM extraction
    
    # The extracted information can be saved or processed further
    repositories = extract_repositories_from_state(state)
    
    # Save the extracted data
    with open("trending_repos.json", "w") as f:
        json.dump(
            {
                "extraction_date": datetime.now().isoformat(),
                "repositories": repositories
            },
            f, 
            indent=2
        )
```

## Performance Considerations

OmniParser adds computational overhead to the extraction process. Consider the following to optimize performance:

1. **Selective Enabling**: Only enable OmniParser when needed for specific pages or elements
2. **Confidence Threshold**: Adjust the confidence threshold based on your needs (higher = fewer false positives but might miss elements)
3. **Caching**: Consider caching extraction results for pages that don't change frequently

## Troubleshooting

### Common Issues and Solutions

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| OmniParser not detecting elements | Confidence threshold too high | Lower the `confidence_threshold` value |
| OmniParser detecting too many false positives | Confidence threshold too low | Increase the `confidence_threshold` value |
| CAPTCHA detection not working | CAPTCHA detection disabled | Ensure `captcha_detection=True` |
| Slow performance | Processing overhead | Only enable OmniParser when needed |
| Missing dependencies | Missing OmniParser package | Install required dependencies |

### Debugging Tips

1. **Enable Logging**: Set logging level to DEBUG to see detailed OmniParser processing information

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

2. **Inspect Screenshots**: Save screenshots to analyze what OmniParser is seeing

```python
screenshot_base64 = await context.take_screenshot(full_page=True)
with open("debug_screenshot.png", "wb") as f:
    f.write(base64.b64decode(screenshot_base64))
```

3. **Examine State**: Print the DOM state with OmniParser additions to debug element detection

```python
state = await context.get_state()
print(state.json(indent=2))
```

## Requirements

OmniParser can be used in two ways:

1. **Local Server (Recommended)**:
   
   First, set up OmniParser locally:
   ```bash
   # Clone the repository
   git clone https://github.com/microsoft/OmniParser
   cd OmniParser
   
   # Create and activate conda environment
   conda create -n "omni" python==3.12
   conda activate omni
   
   # Install requirements
   pip install -r requirements.txt
   
   # Download model weights
   for f in icon_detect/{train_args.yaml,model.pt,model.yaml} icon_caption/{config.json,generation_config.json,model.safetensors}; do huggingface-cli download microsoft/OmniParser-v2.0 "$f" --local-dir weights; done
   mv weights/icon_caption weights/icon_caption_florence
   ```

   Then run the FastAPI server (see examples/omniparser/fastapi_server.py):
   ```bash
   python examples/omniparser/fastapi_server.py
   ```

   Configure your agent to use the local server:
   ```python
   from browser_use.browser.config import BrowserExtractionConfig
   from browser_use.omniparser.views import OmniParserSettings

   # Configure browser with local OmniParser server (default)
   context_config = BrowserContextConfig(
       extraction_config=BrowserExtractionConfig(
           use_hybrid_extraction=True,
           omniparser=OmniParserSettings(
               enabled=True,
               use_api=False,  # Use local server
               endpoint="http://localhost:8000/screen/parse",  # Optional: specify custom endpoint
               captcha_detection=True,
               merge_with_dom=True
           )
       )
   )
   ```

2. **Hosted API Service**:
   
   Alternatively, you can use the hosted API service:
   ```python
   context_config = BrowserContextConfig(
       extraction_config=BrowserExtractionConfig(
           use_hybrid_extraction=True,
           omniparser=OmniParserSettings(
               enabled=True,
               use_api=True,  # Use hosted API service
               endpoint=None,  # Optional: will use default API endpoint
               captcha_detection=True,
               merge_with_dom=True
           )
       )
   )
   ```

   Or specify a custom API endpoint:
   ```python
   context_config = BrowserContextConfig(
       extraction_config=BrowserExtractionConfig(
           use_hybrid_extraction=True,
           omniparser=OmniParserSettings(
               enabled=True,
               use_api=True,
               endpoint="https://custom-api.example.com/v1/screen/parse",
               captcha_detection=True,
               merge_with_dom=True
           )
       )
   )
   ```

## Limitations

- Local server requires GPU for optimal performance
- Hosted API service requires an active internet connection
- Currently focused on CAPTCHA detection, with more specialized detection planned for future versions

## Future Improvements

- Better heuristics for merging DOM and OmniParser results
- More specialized detectors for different UI patterns
- Performance optimization for real-time use
- Support for tracking dynamic UI changes
