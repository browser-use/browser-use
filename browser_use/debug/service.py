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
from browser_use.browser.context import BrowserContext, BrowserContextConfig, BrowserSession
from browser_use.dom.service import DomService
from browser_use.agent.message_manager.service import MessageManager
from browser_use.agent.prompts import SystemPrompt
from browser_use.browser.views import BrowserState, BrowserError, URLNotAllowedError
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
        
    async def process_page(self, include_attributes=None, highlight_elements=True, focus_element=-1):
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
            highlight_elements=highlight_elements,
            focus_element=focus_element,
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

    async def navigate_to(self, url: str):
        """Navigate to a URL using context's navigation handling"""
        try:
            await self.context.navigate_to(url)
            await self.context._wait_for_page_and_frames_load()
            return await self.process_page()
        except URLNotAllowedError as e:
            logger.warning(f"Navigation blocked to non-allowed URL: {url}")
            raise HTTPException(status_code=403, detail=str(e))
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def refresh_page(self):
        """Refresh the current page using context's handling"""
        try:
            await self.context.refresh_page()
            await self.context._wait_for_page_and_frames_load()
            return await self.process_page()
        except Exception as e:
            logger.error(f"Page refresh failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def go_back(self):
        """Navigate back using context's handling"""
        try:
            await self.context.go_back()
            await self.context._wait_for_page_and_frames_load()
            return await self.process_page()
        except Exception as e:
            logger.error(f"Navigation back failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def go_forward(self):
        """Navigate forward using context's handling"""
        try:
            await self.context.go_forward() 
            await self.context._wait_for_page_and_frames_load()
            return await self.process_page()
        except Exception as e:
            logger.error(f"Navigation forward failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

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
        self.app.get("/ui/debug/sessions")(self.get_sessions_overview)
        self.app.post("/api/debug/session/connect")(self.connect_to_url)
        self.app.post("/api/debug/session/{session_id}/navigate")(self.navigate_session)
        self.app.post("/api/debug/session/{session_id}/refresh")(self.refresh_session)
        self.app.post("/api/debug/session/{session_id}/back")(self.go_back_session)
        self.app.post("/api/debug/session/{session_id}/forward")(self.go_forward_session)

    async def create_debug_session(self, request: UrlRequest):
        """Create a new debug session for the current tab"""
        try:
            session_id = str(uuid.uuid4())
            
            # Initialize browser if needed
            if not self.browser.playwright_browser:
                await self.browser._init()
            
            # Create new context and connect to the existing page
            context = await self.browser.new_context()
            
            # Store session
            session = DebugSession(session_id, self.browser, context, request.url)
            self.active_sessions[session_id] = session
            
            # Process current page with highlighting enabled
            result = await session.process_page(
                request.include_attributes,
                highlight_elements=True,
                focus_element=-1
            )
            
            return JSONResponse(content={
                "session_id": session_id,
                "status": "success",
                "url": request.url,
                "redirect_url": f"/api/debug/session/{session_id}"
            })
            
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
        
        # Format HTML response with just the debug info
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Browser-Use Debug - {session_id}</title>
            <style>
                body {{ 
                    font-family: Arial, sans-serif; 
                    margin: 0; 
                    padding: 20px;
                    background: white;
                }}
                pre {{ 
                    white-space: pre-wrap; 
                    word-wrap: break-word;
                    background: #f5f5f5;
                    padding: 10px;
                    border-radius: 4px;
                }}
                .controls {{ 
                    padding: 10px; 
                    background: #f0f0f0;
                    margin: 10px 0;
                    border-radius: 4px;
                }}
                .url-info {{
                    padding: 10px;
                    border-bottom: 1px solid #eee;
                    word-break: break-all;
                    margin-bottom: 10px;
                }}
                .button {{
                    padding: 8px 12px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    margin-right: 8px;
                    background: #007bff;
                    color: white;
                }}
                .button:hover {{
                    background: #0056b3;
                }}
                #status {{
                    margin-top: 10px;
                    padding: 10px;
                    display: none;
                }}
                .success {{
                    background: #d4edda;
                    color: #155724;
                    border-radius: 4px;
                }}
                .error {{
                    background: #f8d7da;
                    color: #721c24;
                    border-radius: 4px;
                }}
            </style>
            <script>
                async function connectToTab() {{
                    const statusDiv = document.getElementById('status');
                    try {{
                        const response = await fetch('/api/debug/session/{session_id}/connect', {{
                            method: 'POST'
                        }});
                        const data = await response.json();
                        statusDiv.textContent = data.message;
                        statusDiv.className = data.success ? 'success' : 'error';
                        statusDiv.style.display = 'block';
                        if (data.success) {{
                            // Refresh the page after successful connection
                            setTimeout(() => location.reload(), 1000);
                        }}
                    }} catch (err) {{
                        statusDiv.textContent = 'Error connecting to tab: ' + err.message;
                        statusDiv.className = 'error';
                        statusDiv.style.display = 'block';
                    }}
                }}
            </script>
        </head>
        <body>
            <h2>Debug Information</h2>
            <div class="url-info">
                <strong>URL:</strong> {session.url}
            </div>
            <div class="controls">
                <button class="button" onclick="connectToTab()">Connect to Tab</button>
                <button class="button" onclick="location.reload()">Refresh</button>
                <button class="button" onclick="window.open('', '_self').close()">Close</button>
            </div>
            <div id="status"></div>
            <div class="message">
                <h3>Detected Elements:</h3>
                <pre>{session.message_content}</pre>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_content)

    async def connect_to_tab(self, session_id: str):
        """Connect to an existing Chrome tab with the matching URL"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        
        try:
            # Initialize browser if needed
            if not self.browser.playwright_browser:
                await self.browser._init()
            
            # Get all contexts and find the one with our URL
            contexts = self.browser.playwright_browser.contexts
            for context in contexts:
                for page in context.pages:
                    if page.url == session.url:
                        # Found matching page, update session with this context
                        browser_context = BrowserContext(
                            config=BrowserContextConfig(),
                            browser=self.browser,
                        )
                        session.context = browser_context
                        
                        # Process page with highlighting
                        await session.process_page(highlight_elements=True)
                        
                        return JSONResponse(content={
                            "success": True,
                            "message": "Successfully connected to existing tab"
                        })
            
            return JSONResponse(content={
                "success": False,
                "message": f"No open tab found with URL: {session.url}"
            })
            
        except Exception as e:
            logger.exception("Error connecting to tab")
            return JSONResponse(content={
                "success": False,
                "message": f"Error connecting to tab: {str(e)}"
            })

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
                if (data.redirect_url) {{
                    window.location.href = 'http://localhost:{PORT}' + data.redirect_url;
                }}
            }})
            .catch(err => console.error('Error creating debug session:', err));
        }})();
        """
        
        # The HTML page that shows the bookmarklet
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
                .nav-controls {{
                    margin: 10px 0;
                    padding: 10px;
                    background: #f5f5f5;
                    border-radius: 4px;
                }}
                .nav-button {{
                    padding: 5px 10px;
                    margin: 0 5px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    cursor: pointer;
                }}
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
                    <li>The page will be replaced with the browser-use debug view</li>
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

    async def get_sessions_overview(self):
        """Get an overview of all active debug sessions and URL input"""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Browser-Use Debug</title>
            <style>
                body { 
                    font-family: Arial, sans-serif; 
                    margin: 0; 
                    padding: 20px;
                    background: #f5f5f5;
                }
                .container {
                    max-width: 1200px;
                    margin: 0 auto;
                }
                .url-form {
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .url-input {
                    width: 100%;
                    padding: 8px;
                    margin-bottom: 10px;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    font-size: 16px;
                }
                .button {
                    padding: 8px 16px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    background: #007bff;
                    color: white;
                    font-size: 16px;
                }
                .button:hover {
                    background: #0056b3;
                }
                #status {
                    margin-top: 10px;
                    padding: 10px;
                    display: none;
                    border-radius: 4px;
                }
                .success {
                    background: #d4edda;
                    color: #155724;
                }
                .error {
                    background: #f8d7da;
                    color: #721c24;
                }
                .sessions-list {
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
            </style>
            <script>
                async function connectToUrl() {
                    const urlInput = document.getElementById('url-input');
                    const statusDiv = document.getElementById('status');
                    const url = urlInput.value.trim();
                    
                    if (!url) {
                        statusDiv.textContent = 'Please enter a URL';
                        statusDiv.className = 'error';
                        statusDiv.style.display = 'block';
                        return;
                    }
                    
                    try {
                        const response = await fetch('/api/debug/session/connect', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({ url: url })
                        });
                        
                        const data = await response.json();
                        if (data.success) {
                            // Redirect to debug view instead of opening popup
                            window.location.href = data.redirect_url;
                        } else {
                            statusDiv.textContent = data.message;
                            statusDiv.className = 'error';
                            statusDiv.style.display = 'block';
                        }
                    } catch (err) {
                        statusDiv.textContent = 'Error: ' + err.message;
                        statusDiv.className = 'error';
                        statusDiv.style.display = 'block';
                    }
                }
            </script>
        </head>
        <body>
            <div class="container">
                <h1>Browser-Use Debug</h1>
                
                <div class="url-form">
                    <h2>Connect to URL</h2>
                    <input type="text" id="url-input" class="url-input" 
                           placeholder="Enter URL to debug (e.g., https://example.com)">
                    <button onclick="connectToUrl()" class="button">Connect</button>
                    <div id="status"></div>
                </div>
                
                <div class="sessions-list">
                    <h2>Active Sessions</h2>
                    <!-- Existing sessions list code here -->
                </div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)

    async def connect_to_url(self, request: UrlRequest):
        """Connect to a URL using existing tab or creating new one"""
        try:
            # Get the browser instance first
            playwright_browser = await self.browser.get_playwright_browser()
            
            # Look for existing context/page with our URL
            target_page = None
            target_context = None
            
            # Search through existing contexts for our URL
            for context in playwright_browser.contexts:
                for page in context.pages:
                    if page.url == request.url:
                        target_page = page
                        target_context = context
                        break
                if target_page:
                    break

            if target_page:
                # Use existing page/context
                context = BrowserContext(
                    config=BrowserContextConfig(),
                    browser=self.browser,
                )
                # Initialize session with existing context/page
                context.session = BrowserSession(
                    context=target_context,
                    current_page=target_page,
                    cached_state=context._get_initial_state(target_page)
                )
            else:
                # If no existing page found, create new context
                context = await self.browser.new_context()
                await context.navigate_to(request.url)
                await context._wait_for_page_and_frames_load()
            
            # Create session ID
            session_id = str(uuid.uuid4())
            
            # Create new session
            session = DebugSession(session_id, self.browser, context, request.url)
            self.active_sessions[session_id] = session
            await session.process_page(highlight_elements=True)
            
            return JSONResponse(content={
                "success": True,
                "session_id": session_id,
                "redirect_url": f"/api/debug/session/{session_id}"
            })
            
        except Exception as e:
            logger.error(f"Failed to create new context or navigate to URL: {e}")
            raise

    async def navigate_session(self, session_id: str, request: UrlRequest):
        """Navigate the debug session to a new URL"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        try:
            result = await session.navigate_to(request.url)
            return {
                "status": "success",
                "url": request.url,
                "content": result
            }
        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def refresh_session(self, session_id: str):
        """Refresh the current page in the debug session"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        try:
            result = await session.refresh_page()
            return {
                "status": "success",
                "content": result
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def go_back_session(self, session_id: str):
        """Navigate back in the debug session"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        try:
            result = await session.go_back()
            return {
                "status": "success",
                "content": result
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def go_forward_session(self, session_id: str):
        """Navigate forward in the debug session"""
        if session_id not in self.active_sessions:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        try:
            result = await session.go_forward()
            return {
                "status": "success", 
                "content": result
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

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