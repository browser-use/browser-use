# Browser Research Agent — Frontend

Frontend for the Browser Research Agent, an AI-powered web research application.

## What it does

The application lets users enter a research task in natural language. The frontend sends the task to a FastAPI backend, which executes the research through the Browser Use hosted browser agent and returns the result.

## Tech Stack

- Next.js 16
- React 19
- TypeScript
- Tailwind CSS
- React Markdown

## Local Setup

### Start the Backend

From the project root:

powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000

Start the Frontend

From the frontend directory:

npm install
npm run dev

Open:

http://localhost:3000

Environment Variables

Create frontend/.env.local:

NEXT_PUBLIC_API_URL=http://127.0.0.1:8000

The frontend also defaults to http://127.0.0.1:8000 when this variable is not provided.

The backend requires:

BROWSER_USE_API_KEY=your_browser_use_api_key

Keep API keys private and never commit them.

Application Flow
User
  ↓
Next.js Frontend
  ↓
FastAPI Backend
  ↓
Browser Use Hosted Agent
  ↓
Research Result
  ↓
Frontend
Development

Run linting:

npm run lint

Create a production build:

npm run build

Run the production build:

npm run start
Backend API

The frontend communicates with:

POST /research
GET /health

Example research request:

{
  "task": "Research the latest developments in renewable energy."
}
Note

Browser Use provides the underlying browser automation infrastructure. This repository contains the application-specific frontend and backend integration built around that service.

Author
Tanishka Goel
B.Tech Computer Science & Engineering