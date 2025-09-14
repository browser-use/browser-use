# Ad-Use

Automatically generate Instagram ads from any landing page using browser agents and Google's Nano Banana 🍌 image generation model.

> [!WARNING]
> This demo requires browser-use v0.7.7+.

https://github.com/user-attachments/assets/7fab54a9-b36b-4fba-ab98-a438f2b86b7e

## Features

1. Agent visits your target website
2. Captures brand name, tagline, and key selling points
3. Takes a clean screenshot for design reference
4. Creates a scroll-stopping Instagram ad with 🍌

## Setup

Make sure the newest version of browser-use is installed (with screenshot functionality):
```bash
pip install -U browser-use
```

Export your Gemini API key, get it from: [Google AI Studio](https://makersuite.google.com/app/apikey) 
```
export GOOGLE_API_KEY='your-google-api-key-here'
```

Clone the repo and cd into the app folder
```bash
git clone https://github.com/browser-use/browser-use.git
cd browser-use/examples/apps/ad-use
```

## Normal Usage

```bash
# Basic - Generate ad from any website
python ad_generator.py https://www.apple.com/iphone-17-pro/

# Debug Mode - See the browser in action
python ad_generator.py https://www.apple.com/iphone-17-pro/ --debug
```

## Programmatic Usage
```python
import asyncio
from ad_generator import create_ad_from_landing_page

async def main():
    results = await create_ad_from_landing_page(
        url="https://your-landing-page.com",
        debug=False
    )
    print(f"Generated ads: {results}")

asyncio.run(main())
```

## Output

Generated ads are saved in the `output/` directory with:
- **PNG image files** (ad_style_timestamp.png) - Actual generated ads from Gemini 2.5 Flash Image
- **Prompt files** (ad_style_timestamp_prompt.txt) - The prompts used for generation  
- **Landing page screenshots** for reference

## License

MIT
