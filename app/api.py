import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import run_browser_task

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Browser Research Agent API",
    description="API for executing browser research tasks using Browser Use.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    task: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The browser research task to execute.",
    )


@app.get("/")
def root():
    return {"message": "Browser Research Agent API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/research")
def research(request: ResearchRequest):
    task = request.task.strip()

    if len(task) < 3:
        raise HTTPException(
            status_code=422,
            detail="Research task must contain at least 3 non-whitespace characters.",
        )

    try:
        result = run_browser_task(task)

        if not result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=result.get("error") or "Browser research failed.",
            )

        return result

    except HTTPException:
        raise

    except Exception:
        logger.exception("Unexpected error while executing research task")
        raise HTTPException(
            status_code=500,
            detail="An unexpected server error occurred. Please try again.",
        )