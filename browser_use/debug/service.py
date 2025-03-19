"""
Debug service for browser-use.

This service allows previewing how browser-use processes DOM elements without using an LLM.
It creates a lightweight API that:
1. Takes a URL and creates a session with Playwright
2. Processes the page using browser-use components
3. Returns the formatted message that would be sent to an LLM
"""

import asyncio
import logging
import uuid
import time
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use.dom.service import DomService
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import SystemPrompt
from browser_use.browser.views import BrowserState
from langchain_core.language_models.chat_models import BaseChatModel

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Store active debug sessions
active_sessions: Dict[str, Dict] = {}

# Session cleanup settings
SESSION_TIMEOUT = 600  # 10 minutes
CLEANUP_INTERVAL = 60  # Check for expired sessions every minute

PORT = 9000

class UrlRequest(BaseModel):
    """Request model for creating a debug session with a URL"""
    url: str
    include_attributes: Optional[List[str]] = None

class DummyLLM(BaseChatModel):
    """Dummy LLM for debug service that doesn't make any real calls"""
    def _generate(self, messages, stop=None, **kwargs):
        return {"generations": [{"text": "Debug mode - no LLM calls"}]}
    
    def _llm_type(self):
        return "dummy"

    async def _agenerate(self, messages, stop=None, **kwargs):
        return {"generations": [{"text": "Debug mode - no LLM calls"}]}

    @property
    def _identifying_params(self):
        return {"name": "DummyLLM"}

    @property
    def _llm_type(self):
        return "dummy"

class DebugSession:
    """Represents a debug session with a browser instance"""
    def __init__(self, session_id: str, browser: Browser, context: BrowserContext, url: str):
        self.session_id = session_id
        self.browser = browser
        self.context = context
        self.url = url
        self.state: Optional[BrowserState] = None
        self.message_content: Optional[str] = None
        self.last_accessed = time.time()
        self.screenshot = None
        
    async def process_page(self, include_attributes=None):
        """Process the page using browser-use components and store results"""
        if include_attributes is None:
            include_attributes = [
                'title', 'type', 'name', 'role', 'tabindex', 
                'aria-label', 'placeholder', 'value', 'alt', 
                'aria-expanded', 'class', 'data-view-classes',
                'data-chart-section-id', 'data-metric-location'
            ]
            
        # Get current page and process using DomService
        page = await self.context.get_current_page()
        dom_service = DomService(page)
        
        # Get clickable elements with highlights
        content = await dom_service.get_clickable_elements(
            highlight_elements=True,
            focus_element=-1,
            viewport_expansion=0
        )
        
        # Store state
        self.state = await self.context._update_state()
        self.screenshot = self.state.screenshot
        
        # Create message manager with required arguments including dummy LLM
        message_manager = MessageManager(
            llm=DummyLLM(),
            task="Debug preview of browser-use DOM processing",
            action_descriptions={},  # Empty dict since we're just viewing
            system_prompt_class=SystemPrompt,
            max_input_tokens=100000,
            include_attributes=include_attributes
        )
        
        # Add state message to get formatted content
        message_manager.add_state_message(self.state)
        
        # Get the formatted message from the last message added
        self.message_content = message_manager.history.messages[-1].message.content
        self.last_accessed = time.time()
        
        return {
            "url": self.url,
            "title": await page.title(),
            "message": self.message_content,
        }
    
    async def release(self):
        """Close browser and clean up resources"""
        await self.context.close()
        await self.browser.close()

class DebugService:
    def __init__(self, browser: Optional[Browser] = None):
        self.browser = browser
        self.active_sessions: Dict[str, DebugSession] = {}
        self.app = FastAPI(title="Browser-Use Debug Service")
        self._setup_routes()
        
    def _setup_routes(self):
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Add routes
        self.app.post("/api/debug/session/create")(self.create_debug_session)
        self.app.get("/api/debug/session/{session_id}")(self.get_debug_results)
        self.app.post("/api/debug/session/{session_id}/refresh")(self.refresh_debug_session)
        self.app.delete("/api/debug/session/{session_id}")(self.delete_debug_session)
        self.app.get("/ui/debug/bookmarklet")(self.get_bookmarklet)

    async def create_debug_session(self, request: UrlRequest):
        """Create a new debug session for the current tab"""
        try:
            session_id = str(uuid.uuid4())
            
            # Use provided browser or create new one
            browser = self.browser or Browser(config=BrowserConfig(
                chrome_instance_path=get_chrome_path(),
                connect_to_running_chrome=True  # Connect to existing Chrome
            ))
            
            # Create new context using browser-use's pattern
            context = await browser.new_context()
            
            # Get current page using browser-use's method
            page = await context.get_current_page()
            
            # Store session
            session = DebugSession(session_id, browser, context, request.url)
            self.active_sessions[session_id] = session
            
            # Process current page
            result = await session.process_page(request.include_attributes)
            
            return {
                "session_id": session_id,
                "status": "success",
                "url": page.url
            }
        
        except Exception as e:
            logger.exception("Error creating debug session")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_debug_results(self, session_id: str, format: str = "html"):
        """Get debug results for a session in HTML or JSON format"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        session.last_accessed = time.time()
        
        if format == "json":
            return JSONResponse(content={
                "url": session.url,
                "message_content": session.message_content,
                "screenshot": session.screenshot
            })
        
        # Format HTML response with correct API paths
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Browser-Use Debug - {session_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; }}
                .container {{ display: flex; height: 100vh; }}
                .sidebar {{ width: 40%; overflow: auto; padding: 20px; border-right: 1px solid #ccc; }}
                .main {{ flex-grow: 1; overflow: auto; }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; background: #f5f5f5; padding: 10px; }}
                h1 {{ font-size: 1.5em; }}
                h2 {{ font-size: 1.2em; color: #333; }}
                .controls {{ padding: 10px; background: #f0f0f0; border-bottom: 1px solid #ccc; }}
                .message {{ padding: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="sidebar">
                    <h1>Browser-Use Debug</h1>
                    <p>Session ID: {session_id}</p>
                    <p>URL: <a href="{session.url}" target="_blank">{session.url}</a></p>
                    
                    <h2>LLM Message Content</h2>
                    <pre>{session.message_content}</pre>
                    
                    <h2>Controls</h2>
                    <button onclick="fetch('/api/debug/session/{session_id}/refresh', {{ method: 'POST' }}).then(() => location.reload())">
                        Refresh Page
                    </button>
                    <button onclick="fetch('/api/debug/session/{session_id}', {{ method: 'DELETE' }}).then(() => window.close())">
                        End Session
                    </button>
                </div>
                <div class="main">
                    <iframe src="{session.url}" width="100%" height="100%" frameborder="0"></iframe>
                </div>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)

    async def refresh_debug_session(self, session_id: str):
        """Refresh the page and update the debug information"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        try:
            # Get current page
            page = await session.context.get_current_page()
            # Reload the page
            await page.reload()
            # Process page again
            await session.process_page()
            return {"status": "refreshed"}
        except Exception as e:
            logger.exception("Error refreshing session")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_debug_session(self, session_id: str):
        """Release a debug session and clean up resources"""
        if session_id not in self.active_sessions:
            return {"status": "session not found"}
        
        try:
            session = self.active_sessions.pop(session_id)
            await session.release()
            return {"status": "session released"}
        except Exception as e:
            logger.exception("Error releasing session")
            raise HTTPException(status_code=500, detail=str(e))

    def get_bookmarklet(self):
        """Get a bookmarklet for creating debug sessions from the browser"""
        bookmarklet = f"""
        javascript:(function(){{
            const url = window.location.href;
            fetch('http://localhost:{PORT}/api/debug/session/create', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{url: url}})
            }})
            .then(response => response.json())
            .then(data => {{
                console.log('Browser-Use Debug Session:', data.session_id);
                window.open('http://localhost:{PORT}/api/debug/session/' + data.session_id, '_blank');
            }})
            .catch(err => console.error('Error creating debug session:', err));
        }})();
        """
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Browser-Use Debug Bookmarklet</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; }}
                .bookmarklet {{ margin: 20px 0; }}
                .instructions {{ margin: 20px 0; }}
                pre {{ background: #f5f5f5; padding: 10px; }}
            </style>
        </head>
        <body>
            <h1>Browser-Use Debug Bookmarklet</h1>
            
            <div class="bookmarklet">
                <p>Drag this to your bookmarks bar:</p>
                <a href="{bookmarklet}" style="padding: 10px; background: #f0f0f0; border: 1px solid #ccc; text-decoration: none; color: black;">
                    Browser-Use Debug
                </a>
            </div>
            
            <div class="instructions">
                <h2>Instructions</h2>
                <ol>
                    <li>Make sure the debug service is running (<code>uvicorn browser_use.debug.service:app</code>)</li>
                    <li>Drag the bookmarklet to your bookmarks bar</li>
                    <li>Navigate to any web page you want to analyze</li>
                    <li>Click the bookmarklet</li>
                    <li>A new tab will open showing how browser-use would process the page</li>
                </ol>
            </div>
            
            <div class="code">
                <h2>Bookmarklet Code</h2>
                <pre>{bookmarklet}</pre>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)

# Create service instance
def create_debug_service(browser: Optional[Browser] = None) -> FastAPI:
    service = DebugService(browser)
    return service.app

# Default app instance

def get_chrome_path():
    return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    # """Get the Chrome executable path based on the platform"""
    # if platform.system() == "Darwin":  # macOS
    #     paths = [
            
    #         '/Applications/Chromium.app/Contents/MacOS/Chromium'
    #     ]
    # else:  # Linux/Unix
    #     paths = [
    #         '/usr/bin/google-chrome',
    #         '/usr/bin/chromium',
    #         '/usr/bin/chromium-browser'
    #     ]
    
    # for path in paths:
    #     if os.path.exists(path):
    #         return path
    
    # raise Exception("Chrome/Chromium not found in standard locations")

browser = Browser(
                config=BrowserConfig(
                    chrome_instance_path=get_chrome_path(),
                    # launch_args=launch_args
                )
            )
app = create_debug_service(browser)

@app.on_event("startup")
async def start_session_cleanup():
    """Start background task to clean up expired sessions"""
    asyncio.create_task(cleanup_sessions())

async def cleanup_sessions():
    """Periodically check and clean up expired sessions"""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            current_time = time.time()
            expired_sessions = []
            
            for session_id, session in active_sessions.items():
                if current_time - session.last_accessed > SESSION_TIMEOUT:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                session = active_sessions.pop(session_id)
                await session.release()
                logger.info(f"Cleaned up expired session: {session_id}")
        except Exception as e:
            logger.exception("Error in cleanup task")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT) 