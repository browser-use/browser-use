import os
import logging
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Body, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from pydantic import SecretStr
from api import router, collect_metrics_periodically
from database import engine, Base, get_db, init_db
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning

from browser_use import Agent, BrowserConfig, Browser

# Logging configuration
logger = logging.getLogger('browser-use.server')

# Load environment variables
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not defined in environment variables")

log_info(logger, f"Connecting to database at: {DATABASE_URL}")

# Initialize database
init_db()

# Initialize FastAPI application
app = FastAPI(
    title="Browser-use API",
    description="API to control Browser-use"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Data models
class BrowserConfigModel(BaseModel):
    headless: bool = True
    disable_security: bool = True
    extra_chromium_args: List[str] = []

class ModelConfig(BaseModel):
    provider: str = Field(..., description="Model provider: openai, azure")
    model_name: str = Field(..., description="Model name to be used")
    api_key: Optional[str] = Field(None, description="API key for the provider (if needed)")
    azure_endpoint: Optional[str] = Field(None, description="Endpoint for Azure OpenAI (if provider=azure)")
    azure_api_version: Optional[str] = Field(None, description="Azure OpenAI API version (if provider=azure)")
    temperature: float = Field(0.0, description="Generation temperature (0.0 to 1.0)")

class TaskRequest(BaseModel):
    task: str
    llm_config: ModelConfig
    browser_config: Optional[BrowserConfigModel] = None
    max_steps: int = 20
    use_vision: bool = True
    generate_gif: bool = True
    max_failures: int = 3

class AgentResponse(BaseModel):
    task: str
    result: str
    success: bool
    steps_executed: int
    error: Optional[str] = None

# Function to get LLM based on configuration
def get_llm(model_config: ModelConfig):
    try:
        provider = model_config.provider.lower()
        log_info(logger, "Initializing LLM", {
            "provider": provider,
            "model": model_config.model_name
        })
        
        if provider == "openai":
            return ChatOpenAI(
                model=model_config.model_name,
                temperature=model_config.temperature,
                api_key=model_config.api_key or os.getenv("OPENAI_API_KEY")
            )
        elif provider == "deepseek":
            return ChatOpenAI(
                base_url='https://api.deepseek.com/v1',
                model=model_config.model_name or 'deepseek-chat',
                api_key=model_config.api_key or os.getenv("DEEPSEEK_API_KEY"),
            )
        elif provider == "azure":
            return AzureChatOpenAI(
                model=model_config.model_name,
                temperature=model_config.temperature,
                api_key=SecretStr(model_config.api_key or os.getenv("AZURE_OPENAI_KEY", "")),
                azure_endpoint=model_config.azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                api_version=model_config.azure_api_version or "2024-10-21"
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    except Exception as e:
        log_error(logger, "Error initializing LLM", {
            "provider": model_config.provider,
            "model": model_config.model_name,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error initializing LLM: {str(e)}")

@app.post("/run", response_model=AgentResponse)
async def run_agent(
    request: TaskRequest = Body(...),
    db = Depends(get_db)
):
    log_info(logger, "Starting agent execution", {
        "task": request.task,
        "provider": request.llm_config.provider,
        "model": request.llm_config.model_name
    })
    
    try:
        # Configure LLM model
        llm = get_llm(request.llm_config)
        
        # Configure browser
        browser_config = BrowserConfig(
            headless=request.browser_config.headless if request.browser_config else True,
            disable_security=request.browser_config.disable_security if request.browser_config else True,
            extra_chromium_args=request.browser_config.extra_chromium_args if request.browser_config else []
        )
        
        log_debug(logger, "Browser configuration", {
            "headless": browser_config.headless,
            "disable_security": browser_config.disable_security
        })
        
        # Initialize browser
        browser = Browser(config=browser_config)
        
        # Initialize and run agent
        agent = Agent(
            task=request.task, 
            llm=llm, 
            browser=browser,
            use_vision=request.use_vision,
            generate_gif=request.generate_gif,
            max_failures=request.max_failures
        )
        
        result = await agent.run(max_steps=request.max_steps)
        
        # Extract result
        success = False
        content = "Task not completed"
        
        if result and result.history and len(result.history) > 0:
            last_item = result.history[-1]
            if last_item.result and len(last_item.result) > 0:
                last_result = last_item.result[-1]
                content = last_result.extracted_content or "No content extracted"
                success = last_result.is_done
        
        # Close browser after use
        await browser.close()
        
        return AgentResponse(
            task=request.task,
            result=content,
            success=success,
            steps_executed=len(result.history) if result and result.history else 0
        )
        
    except Exception as e:
        log_error(logger, "Error during agent execution", {
            "task": request.task,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Endpoint to check API health"""
    log_debug(logger, "Checking API health")
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or use 8000 as default
    port = int(os.getenv("PORT", 8000))
    
    log_info(logger, "Starting FastAPI server", {
        "host": "0.0.0.0",
        "port": port
    })
    
    # Start server
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")