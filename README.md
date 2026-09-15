<p align="center">
  <img
    src="assets/banner.svg"
    alt="Browser Research Agent — AI-powered web research through automated browser workflows."
    width="100%"
  />
</p>

# Browser Research Agent

**AI-powered web research through automated browser workflows.**

A full-stack application that turns a natural-language research task into a hosted Browser Use browser run, monitors its lifecycle, and presents the completed result in a responsive Next.js interface.

[![Repository](https://img.shields.io/badge/GitHub-Repository-18181b?style=flat\&logo=github)](https://github.com/Tg289/Browser-Automation-Agent)
[![Frontend](https://img.shields.io/badge/Frontend-Next.js%2016-18181b?style=flat\&logo=next.js)](https://nextjs.org/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-18181b?style=flat\&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Language](https://img.shields.io/badge/Backend-Python-18181b?style=flat\&logo=python)](https://www.python.org/)

</div>

> **Note:** Browser research is executed through the hosted Browser Use service. Runs may consume Browser Use account credits, so this repository is configured and documented for controlled/local development rather than unrestricted public use.

---

## Overview

Browser Research Agent is a web application for delegating multi-step web research to a browser automation agent. Instead of manually opening sites, navigating pages, and collecting findings, a user submits a research task in natural language and receives the resulting research through the application's UI.

The repository contains the application layer around the hosted Browser Use Web Agent API: a **FastAPI backend** validates requests, creates and monitors hosted runs, handles terminal states and timeouts, and returns a normalized result to a **Next.js + React frontend**. The frontend manages the research interaction, loading/error states, Markdown result rendering, and an in-memory list of recent research tasks.

This makes the project primarily an **AI application engineering and full-stack integration project**: the browser automation infrastructure is provided by Browser Use, while the application-specific orchestration, API boundary, UI, and failure handling live in this repository.

## Why This Project?

Web research is often repetitive even when the question itself is simple. A person may need to:

* Open multiple websites and navigate through them.
* Find and extract information relevant to a specific question.
* Consolidate the findings into a usable answer.

Browser Research Agent moves that workflow behind a single natural-language interface. The application submits the task to a hosted browser agent and waits for the agent to complete the research before presenting the returned result.

The engineering challenge isn't training a model here. It's integrating an external AI/browser-automation service into a usable application and handling the lifecycle around a potentially long-running remote operation.

## Key Features

Natural-language research tasks — submit a research request through a text-based interface.
Hosted browser automation — delegates web navigation and research execution to the Browser Use hosted Web Agent API.
Run lifecycle monitoring— creates a run, polls its status, and retrieves the completed run result.
Timeout protection — stops waiting after the configured maximum wait period and attempts to cancel the hosted run.
Failure-state handling — handles completed, failed, cancelled, and stopped run states.
Input validation — validates task length with Pydantic and rejects empty/whitespace-only tasks at the API boundary.
API error handling — converts upstream request failures and invalid responses into application-level errors.
Markdown result rendering — displays returned research as rendered Markdown, with links opening in a new tab.
Recent research history — keeps the latest 20 completed research items in frontend state and lets the user restore a previous task/result.
Responsive dark UI — provides a focused research interface built with Next.js, React, TypeScript, and Tailwind CSS.

---

## Architecture
flowchart LR
    U[User] --> FE[Next.js Frontend<br/>React + TypeScript + Tailwind]
    FE -->|POST /research| BE[FastAPI Backend<br/>Validation + Orchestration]
    BE -->|Create run| BU[Browser Use Hosted<br/>Web Agent API]
    BU -->|Browser automation| WEB[Web Research]
    WEB --> BU
    BU -->|Run status + result| BE
    BE -->|Research response| FE
    FE --> R[Rendered Markdown Result]

    style U fill:#18181b,stroke:#52525b,color:#fff
    style FE fill:#18181b,stroke:#52525b,color:#fff
    style BE fill:#18181b,stroke:#52525b,color:#fff
    style BU fill:#27272a,stroke:#71717a,color:#fff
    style WEB fill:#27272a,stroke:#71717a,color:#fff
    style R fill:#18181b,stroke:#52525b,color:#fff

### Component responsibilities

| Component                  | Responsibility                                                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Next.js frontend**       | Research task input, client-side interaction, loading/error states, result rendering, and recent-history state.                   |
| **FastAPI backend**        | Request validation, CORS configuration, Browser Use API calls, run polling, timeout/cancellation handling, and error translation. |
| **Browser Use hosted API** | Executes the browser-based research task and exposes the remote run lifecycle/result.                                             |

---

## How It Works

1. The user enters a research task in the Next.js interface.
2. The frontend trims the task and avoids submitting an empty value.
3. The frontend sends `POST /research` to the FastAPI backend.
4. FastAPI validates the task with a Pydantic `ResearchRequest` model. Tasks must contain at least 3 and at most 2,000 characters.
5. The backend reads `BROWSER_USE_API_KEY` from the environment and creates a hosted Browser Use run with the submitted task.
6. The backend polls the run status every **3 seconds** while the local **180-second maximum wait window** has not elapsed.
7. For `completed`, `failed`, `cancelled`, or `stopped` runs, the backend retrieves the final run payload.
8. A completed run returns its `result`; failed terminal states return an error derived from the hosted run when available.
9. If the 180-second wait window expires, the backend attempts to cancel the hosted run and returns a timeout error to the frontend.
10. The frontend displays the successful result as Markdown and records the task, result, and execution time in its in-memory recent-history list.

---

## Technical Implementation

### Backend

The backend is intentionally small and focused on the integration boundary.

* **FastAPI** defines the application and REST endpoints.
* **Pydantic** validates the incoming research task.
* **Requests** handles synchronous HTTP communication with the hosted Browser Use API.
* The Browser Use API key is loaded with `python-dotenv` and sent through the `X-Browser-Use-API-Key` request header.
* Run creation, status polling, final-result retrieval, and cancellation are kept in `app/agent.py`.
* The polling loop recognizes the terminal states `completed`, `failed`, `cancelled`, and `stopped`.
* Each upstream HTTP request has a 30-second request timeout, while the overall research workflow has a separate 180-second maximum wait window.
* Request failures, malformed upstream responses, missing configuration, and unexpected failures are converted into structured application results or HTTP errors.
* CORS is explicitly configured for the local frontend origins `localhost:3000` and `127.0.0.1:3000`.

### Frontend

The frontend is implemented as a Next.js App Router application.

* **React state** manages the active task, result, loading state, execution time, errors, and recent research history.
* **TypeScript** defines the local `ResearchItem` shape used by the history UI.
* The frontend calls the backend using the browser `fetch` API.
* `NEXT_PUBLIC_API_URL` controls the backend URL, with `http://127.0.0.1:8000` as the local fallback.
* **React Markdown** renders the research result returned by the backend.
* The UI exposes example tasks, a character counter, progress feedback, error feedback, result timing, and a clear-history action.
* Recent history is maintained in client-side React state; it is not persisted to a database.

### External API integration

The application integrates with the **Browser Use Hosted Web Agent API** rather than implementing its own browser automation engine or AI model.

The backend uses the Browser Use v4 API base URL and follows this application-level lifecycle:

POST /runs
      ↓
GET /runs/{run_id}/status   ← poll every 3s
      ↓
terminal state?
  ├─ completed → GET /runs/{run_id} → return result
  ├─ failed/cancelled/stopped → GET /runs/{run_id} → return error/result
  └─ timeout → POST /runs/{run_id}/cancel → return timeout error

No Browser Use credentials are hard-coded in the repository.
---

## Tech Stack

| Layer              | Technology                       | Role                                |
| ------------------ | -------------------------------- | ----------------------------------- |
| Frontend           | Next.js 16                       | Web application framework           |
| Frontend           | React 19                         | UI and client-side state            |
| Frontend           | TypeScript                       | Static typing                       |
| Styling            | Tailwind CSS 4                   | Interface styling                   |
| Rendering          | React Markdown 10                | Research result rendering           |
| Backend            | Python 3.11+                     | Application backend                 |
| API                | FastAPI                          | REST API and request handling       |
| Validation         | Pydantic 2                       | Research request validation         |
| HTTP               | Requests                         | Browser Use API communication       |
| Configuration      | python-dotenv                    | Environment variable loading        |
| Browser automation | Browser Use Hosted Web Agent API | Remote browser-based task execution |

---

## Project Structure
Browser-Automation-Agent/
├── app/
│   ├── __init__.py
│   ├── agent.py          # Browser Use API integration and run lifecycle
│   ├── api.py            # FastAPI application and REST endpoints
│   └── main.py           # Simple CLI entry point for a browser task
├── frontend/
│   ├── src/
│   │   └── app/
│   │       ├── globals.css
│   │       ├── layout.tsx # Application metadata/layout
│   │       └── page.tsx  # Research UI and client-side workflow
│   ├── public/            # Next.js public assets
│   ├── eslint.config.mjs
│   ├── next.config.ts
│   ├── package.json
│   ├── package-lock.json
│   └── postcss.config.mjs
├── .env.example           # Backend environment template
├── .gitignore
├── LICENSE
├── pyproject.toml          # Python package/dependency configuration
└── README.md
The repository also retains the upstream Browser Use source tree and its project-level development configuration. The application-specific integration described above lives under `app/` and `frontend/`.

---

## Local Setup

### Prerequisites

Python 3.11+
Node.js compatible with the Next.js 16 frontend
A Browser Use API key with access to the hosted Web Agent API

### 1. Clone the repository

git clone https://github.com/Tg289/Browser-Automation-Agent.git

cd Browser-Automation-Agent

### 2. Create and activate the Python environment

python -m venv .venv
.\.venv\Scripts\Activate.ps1

If PowerShell blocks script execution, activate the environment using another supported shell rather than changing system policy solely for this project.

### 3. Install backend dependencies

The repository's Python project configuration defines the backend dependencies, so install the local project in editable mode:

pip install -e .

### 4. Configure the Browser Use API key

Create .env in the repository root:

env
BROWSER_USE_API_KEY=your_browser_use_api_key

Keep this file local. Do **not** commit API keys or other credentials.

### 5. Start the FastAPI backend

uvicorn app.api:app --reload --host 127.0.0.1 --port 8000

The API will be available at:
http://127.0.0.1:8000

### 6. Install frontend dependencies

Open a second terminal:
cd frontend
npm install

### 7. Configure the frontend API URL

Create:
frontend/.env.local


Add:
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
### 8. Start the frontend

From frontend:

npm run dev
Open:
http://localhost:3000

### Cross-platform command summary

The same setup works from macOS/Linux with the equivalent virtual-environment activation command:


python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000

In a second terminal:

cd frontend
npm install
npm run dev

The frontend environment variable remains:

NEXT_PUBLIC_API_URL=http://127.0.0.1:8000

> **Usage cost:** research runs are executed by the hosted Browser Use service and may consume account credits. Treat the endpoint as a controlled development interface rather than an unrestricted public API.

---

## Environment Variables

### Backend — `.env`

| Variable              | Required | Purpose                                                         |
| --------------------- | -------- | --------------------------------------------------------------- |
| `BROWSER_USE_API_KEY` | Yes      | Authenticates requests to the Browser Use Hosted Web Agent API. |

Template:

BROWSER_USE_API_KEY=your_browser_use_api_key

### Frontend — `frontend/.env.local`

| Variable              | Required | Purpose                                                                                  |
| --------------------- | -------- | ---------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | No       | URL of the FastAPI backend. The frontend defaults to `http://127.0.0.1:8000` when unset. |

Template:
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000

Never place the Browser Use API key in a `NEXT_PUBLIC_` variable or expose it to the browser.

---

## API

The FastAPI application exposes three routes.

### `GET /`

Basic API status response:


{
  "message": "Browser Research Agent API is running"
}

### `GET /health`

Health-check response:

{
  "status": "healthy"
}

### `POST /research`

Executes a browser research task.

Request:


{
  "task": "Research the latest developments in renewable energy."
}

The `task` field must contain between 3 and 2,000 characters after Pydantic validation, and the backend also rejects values that become shorter than 3 characters after trimming whitespace.

Successful response:

{
  "success": true,
  "task": "Research the latest developments in renewable energy.",
  "result": "...",
  "execution_time": 42.31,
  "error": null
}

The `result` contains the completed research returned by the hosted Browser Use run, while `execution_time` records the application's measured run duration.

Error behavior:

  422 — invalid request/task input.
  502 — Browser Use configuration failure, upstream API failure, invalid hosted response, or an unsuccessful browser run.
  500 — unexpected server-side failure while executing the research request.

---

## Engineering Highlights

This project demonstrates several practical concerns involved in building an AI-powered application around an external agent service:

  External AI/browser automation integration — connects a web application to a hosted browser agent rather than treating the model/service as a black-box UI dependency.
  Remote run lifecycle management — separates run creation, status polling, terminal-state handling, and final-result retrieval.
  Timeout and cancellation control— protects the API request from waiting indefinitely and attempts to cancel the remote run after the local deadline.
  Failure isolation— distinguishes upstream HTTP failures, malformed responses, unsuccessful run states, missing API configuration, and unexpected exceptions.
  Frontend/backend separation** — keeps the Browser Use credential and integration logic on the backend while the browser client communicates with the application API.
  Environment-based configuration — uses environment variables for service credentials and the frontend API endpoint.
  Input validation at the API boundary — rejects invalid research tasks before sending them to the hosted service.
  User-facing result handling— presents long-form research as Markdown and retains recent completed work for quick reuse.
  Controlled local operation — the default backend binding and CORS configuration are oriented around the local frontend rather than an openly exposed service.

---

## Validation & Quality Checks

The repository includes configuration for frontend linting and Python-side validation tooling.

### Frontend lint

From `frontend/`:


npm run lint

The frontend script invokes ESLint with the Next.js Core Web Vitals and TypeScript configurations.

### Frontend production build

From `frontend/`:

npm run build

A production build can then be started with:

npm run start


### Backend syntax validation

From the repository root:


python -m py_compile app\agent.py app\api.py app\main.py

### Automated tests

The application-specific `app/` and `frontend/` changes do **not** currently include a dedicated project test suite. The repository contains upstream Browser Use test infrastructure, but those tests should not be represented as application-level coverage for this project.

---

## Security & Operational Considerations

API credentials stay server-side.`BROWSER_USE_API_KEY` is loaded by the Python backend and is not part of the frontend configuration.
Do not commit `.env`.The repository's `.gitignore` excludes `.env`; use `.env.example` as the safe configuration template.
Local binding by default. The documented backend command binds to `127.0.0.1`, matching the project's controlled-development intent.
Credit-consuming operations. Every submitted research task can invoke a hosted Browser Use run and may consume account credits.
Public deployment needs additional controls.Before exposing `/research` to untrusted users, the application would need an appropriate authentication and rate-limiting strategy, along with stronger operational controls around credit usage.

These are operational considerations for the current architecture, not claims that those controls are already implemented.

---

## Screenshots / Demo

No repository screenshots or live deployment are currently included with the application-specific implementation.

For a recruiter-facing portfolio, the most useful screenshots to add would be:

1. Research interface — task input and example prompts.
2. Completed research result — a real result rendered in Markdown.
3. Recent Research — the client-side history UI after multiple runs.

Recommended repository location:

assets/
├── research-interface.png
├── research-result.png
└── research-history.png

Once real screenshots are added, reference them with relative paths such as:

![Research interface](assets/research-interface.png)

No live demo link is listed because the repository does not currently provide one.

---

## What I Built

This repository should be understood as the **application layer around Browser Use's hosted browser automation infrastructure**.

The Browser Use service provides the underlying hosted browser-agent capability. The application-specific engineering in this repository includes:

* Next.js/React research interface
* FastAPI REST API
* Browser Use Hosted Web Agent API integration
* Research task validation and handling
* Remote run creation and status monitoring
* Timeout protection and cancellation requests
* Upstream error handling
* Frontend loading/error states
* Markdown result presentation
* Client-side recent research history
* Environment-based configuration and local CORS setup

The project does **not** claim ownership of or authorship of the underlying Browser Use browser automation platform.

---

## Future Improvements

The following are intentionally **not current features**. They are reasonable next steps for the application:

* Move long-running research execution to an asynchronous background-job model so the HTTP request does not remain open for the full research lifecycle.
* Persist research history in a database instead of keeping it only in browser memory.
* Add authentication and per-user research history.
* Add rate limiting and usage controls before any public deployment.
* Add automated application-level unit and integration tests for API behavior and Browser Use lifecycle handling.
* Return richer structured research data alongside Markdown when the hosted service supports a suitable contract.
* Add a deployment configuration after the operational controls above are addressed.

---

## License & Attribution

This repository retains the **MIT License** and the original copyright notice from the Browser Use project. The application is built around Browser Use infrastructure and its hosted Web Agent API.

For the exact license terms, see [`LICENSE`](LICENSE).

Browser Use is the underlying browser automation project used by this application. This repository's application-specific frontend and integration code should not be confused with the upstream Browser Use project itself.

---

## Author

Tanishka Goel
B.Tech Computer Science & Engineering

GitHub: [@Tg289](https://github.com/Tg289)

---

<div align="center">

Browser Research Agent
AI application engineering through browser automation and full-stack API integration.*

</div>
