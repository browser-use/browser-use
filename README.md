# Browser Research Agent

An AI-powered web research application that turns natural-language research requests into automated browser tasks and returns the research results through a web interface.

## What It Does

The user enters a research task in natural language. The application sends the task to a FastAPI backend, which creates and monitors a Browser Use hosted browser run. Once the task is completed, the research result is returned and displayed in the frontend.

### Core Flow

User → Next.js Frontend → FastAPI Backend → Browser Use Hosted Agent → Research Result

## Features

- Natural-language web research
- Automated browser-based research
- Browser Use hosted Web Agent API integration
- Run status polling
- Automatic timeout handling and cancellation
- Markdown result rendering
- Research history
- Input validation
- API error handling
- Responsive frontend
- Separate frontend and backend architecture

## Tech Stack

### Frontend
- Next.js 16
- React 19
- TypeScript
- Tailwind CSS
- React Markdown

### Backend
- Python
- FastAPI
- Requests
- Pydantic

### Browser Automation
- Browser Use Hosted Web Agent API

## Project Structure

```text
Browser-Automation-Agent/
├── app/
│   ├── agent.py
│   ├── api.py
│   └── main.py
├── frontend/
│   ├── src/
│   │   └── app/
│   ├── package.json
│   └── package-lock.json
├── .env.example
└── README.md

Requirements
Python 3.11+
Node.js 20+
Browser Use API key

Browser research runs use the hosted Browser Use service and may consume account credits.

Setup
1. Clone the Repository
git clone https://github.com/Tg289/Browser-Automation-Agent.git
cd Browser-Automation-Agent
2. Create Python Environment

Windows PowerShell:

python -m venv .venv
.\.venv\Scripts\Activate.ps1
3. Install Backend Dependencies
pip install -e .
4. Configure API Key

Create a .env file in the project root:

BROWSER_USE_API_KEY=your_browser_use_api_key

Never commit API keys or other secrets.

5. Start Backend
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000

Backend:

http://127.0.0.1:8000
6. Install Frontend Dependencies

Open another terminal:

cd frontend
npm install
7. Configure Frontend

Create:

frontend/.env.local

Add:

NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
8. Start Frontend
npm run dev

Open:

http://localhost:3000
API Endpoints
GET /

Returns the API status.

GET /health

Health-check endpoint.

POST /research

Starts a browser research task.

Example:

{
  "task": "Research the latest developments in renewable energy."
}
Architecture
┌─────────────────────┐
│   Next.js Frontend  │
│   React + TypeScript│
└──────────┬──────────┘
           │
           │ POST /research
           ▼
┌─────────────────────┐
│    FastAPI Backend  │
│ Validation + API    │
└──────────┬──────────┘
           │
           │ Browser Use API
           ▼
┌─────────────────────┐
│ Browser Use Hosted  │
│     Web Agent       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   Research Result   │
└─────────────────────┘
Development
Frontend Lint
cd frontend
npm run lint
Production Build
npm run build
Start Production Build
npm run start
Backend Syntax Check

From the project root:

python -m py_compile app\agent.py app\api.py app\main.py
Security

This application is intended for local development.

The backend should be bound to 127.0.0.1 rather than exposed publicly because research requests can consume Browser Use API credits.

Keep API credentials in environment variables and never commit .env files.

Attribution

This project is an application built around Browser Use browser automation infrastructure and its hosted Web Agent API. The application-specific frontend, backend integration, task handling, and user interface are maintained in this repository.

Author

Tanishka Goel

B.Tech Computer Science & Engineering

GitHub: https://github.com/Tg289