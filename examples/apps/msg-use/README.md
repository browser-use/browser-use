# Msg-Use

AI-powered message scheduler using browser agents and Gemini. Schedule personalized messages in natural language and let AI compose them intelligently.

[!WARNING]
This demo requires browser-use v0.7.7+.

https://browser-use.github.io/media/demos/msg_use.mp4

## Features

1. Agent logs into WhatsApp Web automatically
2. Parses natural language scheduling instructions
3. Composes personalized messages using AI
4. Schedules messages for future delivery or sends immediately
5. Persistent session (no repeated QR scanning)

## Setup

Make sure the newest version of browser-use is installed:
```bash
pip install -U browser-use
```

Export your Gemini API key, get it from: [Google AI Studio](https://makersuite.google.com/app/apikey)
```
export GOOGLE_API_KEY='your-gemini-api-key-here'
```

Clone the repo and cd into the app folder
```bash
git clone https://github.com/browser-use/browser-use.git
cd browser-use/examples/apps/msg-use
```

## Initial Login

First-time setup requires QR code scanning:
```bash
python login.py
```
- Scan QR code when browser opens
- Session will be saved for future use

## Normal Usage

1. **Edit your schedule** in `messages.txt`:
```
- Send "Hi" to Magnus on the 09.09 at 18:15
- Tell hinge date (Camila) at 20:00 that I miss her
- Remind mom to pick up the car next tuesday
```

2. **Test mode** - See what will be sent:
```bash
python scheduler.py --test
```

3. **Run scheduler**:
```bash
python scheduler.py

# Debug Mode - See the browser in action
python scheduler.py --debug

# Auto Mode - Respond to unread messages every ~30 minutes
python scheduler.py --auto
```

## Programmatic Usage

```python
import asyncio
from scheduler import schedule_messages

async def main():
    messages = [
        "Send hello to John at 15:30",
        "Remind Sarah about meeting tomorrow at 9am"
    ]
    await schedule_messages(messages, debug=False)

asyncio.run(main())
```

## Output

Example scheduling output:
```json
[
  {
    "contact": "Magnus",
    "original_message": "Hi",
    "composed_message": "Hi",
    "scheduled_time": "2025-06-13 18:15"
  },
  {
    "contact": "Camila",
    "original_message": "I miss her",
    "composed_message": "I miss you ❤️",
    "scheduled_time": "2025-06-14 20:00"
  }
]
```

## Files

- `scheduler.py` - Main scheduler script
- `login.py` - One-time login setup  
- `messages.txt` - Your message schedule in natural language

## License

MIT
