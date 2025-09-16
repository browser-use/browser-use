# Ad-Use

Automatically generate Instagram image ads and TikTok video ads from any landing page using browser agents, Google's Nano Banana 🍌, and Veo3.

> [!WARNING]
> This demo requires browser-use v0.7.7+.

https://github.com/user-attachments/assets/7fab54a9-b36b-4fba-ab98-a438f2b86b7e

## Features

1. Agent visits your target website
2. Captures brand name, tagline, and key selling points
3. Takes a clean screenshot for design reference
4. Creates scroll-stopping Instagram image ads with 🍌
5. Generates viral TikTok video ads with Veo3
6. Supports parallel generation of multiple ads

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
# Basic - Generate Instagram image ad (default)
python ad_generator.py --url https://www.apple.com/iphone-17-pro/

# Generate TikTok video ad with Veo3
python ad_generator.py --tiktok --url https://www.apple.com/iphone-17-pro/

# Generate multiple ads in parallel
python ad_generator.py --instagram --count 3 --url https://www.apple.com/iphone-17-pro/
python ad_generator.py --tiktok --count 2 --url https://www.apple.com/iphone-17-pro/

# Debug Mode - See the browser in action
python ad_generator.py --url https://www.apple.com/iphone-17-pro/ --debug
```

## Command Line Options

- `--url`: Landing page URL to analyze
- `--instagram`: Generate Instagram image ad (default if no flag specified)
- `--tiktok`: Generate TikTok video ad using Veo3
- `--count N`: Generate N ads in parallel (default: 1)
- `--debug`: Show browser window and enable verbose logging

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
- **PNG image files** (ad_timestamp.png) - Instagram ads generated with Gemini 2.5 Flash Image
- **MP4 video files** (ad_timestamp.mp4) - TikTok ads generated with Veo3
- **Analysis files** (analysis_timestamp.txt) - Browser agent analysis and prompts used
- **Landing page screenshots** (landing_page_timestamp.png) - Reference screenshots

## License

MIT
