# News-Use

Automatically monitor news websites and extract the latest articles with sentiment analysis using browser agents and Google Gemini.

> [!CAUTION]
> This demo requires browser-use v0.7.7+.

https://github.com/user-attachments/assets/650843ee-0b4d-431a-983f-6c1af3d0ffd8

## Features

1. Agent visits any news website
2. Finds and clicks the most recent headline article
3. Extracts title, URL, posting time, and content
4. Generates short/long summaries with sentiment analysis
5. Persistent deduplication across restarts

## Setup

Make sure the newest version of browser-use is installed:
```bash
pip install -U browser-use
```

Export your Gemini API key, get it from: [Google AI Studio](https://makersuite.google.com/app/apikey) 
```
export GEMINI_API_KEY='your-google-api-key-here'
```

## Usage

```bash
# One-time extraction - Get the latest article and exit
python news_monitor.py --once

# Continuous monitoring - Check every 5 minutes (default)
python news_monitor.py

# Custom interval - Check every 60 seconds
python news_monitor.py --interval 60

# Different news site
python news_monitor.py --url https://techcrunch.com

# Debug mode - See browser in action with verbose output
python news_monitor.py --once --debug
```

## Output Format

Articles are displayed with timestamp, sentiment emoji, and summary:
```
[2025-09-11 02:49:21] - 🟢 - Klarna's IPO raises $1.4B, benefiting existing investors
```

Sentiment indicators:
- 🟢 Positive
- 🟡 Neutral  
- 🔴 Negative

## Data Persistence

Extracted articles are saved to `news_data.json` with:
- Article metadata (title, URL, posting time)
- Short summary (10 words)
- Long summary (100 words)
- Sentiment classification
- Deduplication hash to avoid re-processing

## Programmatic Usage

```python
import asyncio
from news_monitor import extract_latest_article

async def main():
    result = await extract_latest_article(
        site_url="https://techcrunch.com",
        debug=False
    )
    if result["status"] == "success":
        article = result["data"]
        print(f"Latest: {article['title']}")

asyncio.run(main())
```

## License

MIT
