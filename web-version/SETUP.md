# 🔐 API Configuration

## Before starting

1. **Create** a `.env` file in the `backend/` directory
2. **Copy** the template: `cp config.env.template .env`
3. **Edit** the `.env` file and replace `YOUR_API_KEY_HERE` with your real OpenAI key
4. **Never** commit the `.env` file to version control

## Environment Variables Setup

```bash
# In backend/.env
OPENAI_API_KEY=your_actual_api_key_here
OPENAI_MODEL=gpt-4o-mini
BROWSER_USE_SETUP_LOGGING=false
HOST=0.0.0.0
PORT=8000
```

## Then start normally

```bash
cd backend
python main.py
```

**🔒 Security Note**: Never hardcode API keys in source code. Always use environment variables or secure configuration management.

**That's it! 🚀** 