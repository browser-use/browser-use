import json
import logging
import os
from typing import Optional, Any
import asyncio

import socketio
from langchain_openai import AzureChatOpenAI
from browser_use.browser.browser import BrowserConfig

from supatest.agent.service import SupatestAgent
from supatest.controller.service import SupatestController
from supatest.browser.browser import SupatestBrowser

logger = logging.getLogger("py_ws_server")


class Executor:
    def __init__(self, handler):
        self.handler = handler
        # We'll hold references to the agent and its background task
        self.agent = None
        self.agent_task = None
        # We'll store the Socket.IO client so we can disconnect later
        self.sio = None
        # Add a flag to track intentional disconnects
        self.is_stopping = False
        # Add connection state tracking
        self.reconnection_in_progress = False
        self.retry_count = 0
        self.MAX_RETRIES = 3

    def _build_automation_uri(self, goal_id: str, setup_data) -> str:
        base_url = os.getenv("AUTOMATION_BASE_URL", "http://localhost:8877")
        return (
            f"{base_url}?type=agent&goalId={goal_id}"
            f"&testCaseId={setup_data.test_case_id}"
        )

    async def stop_agent(self):
        """
        Stop the agent by calling `agent.stop()` and canceling the task if it exists.
        """
        if self.agent:
            try:
                await self.agent.stop()
            except Exception as e:
                logger.error(f"Error stopping agent: {str(e)}")
        if self.agent_task:
            try:
                self.agent_task.cancel()
                await asyncio.sleep(0.5)  # Give a small window for cleanup
            except Exception as e:
                logger.error(f"Error canceling agent task: {str(e)}")

    async def _handle_reconnection(self, error_msg=None):
        """Centralized reconnection logic"""
        if self.is_stopping or self.reconnection_in_progress:
            return False

        self.reconnection_in_progress = True
        try:
            if self.retry_count < self.MAX_RETRIES:
                self.retry_count += 1
                logger.info(f"Attempting to reconnect... (Attempt {self.retry_count}/{self.MAX_RETRIES})")
                
                if self.sio.connected:
                    await self.sio.disconnect()
                
                await asyncio.sleep(2 ** self.retry_count)  # Exponential backoff
                
                await self.sio.connect(
                    self._current_automation_uri,
                    transports=["websocket"],
                    namespaces=["/"]
                )
                logger.info("Reconnection successful")
                self.retry_count = 0  # Reset retry count on success
                self.reconnection_in_progress = False
                return True
            else:
                logger.error("Max reconnection attempts reached")
                if error_msg:
                    await self.handler.emit_automation_error(
                        None, self._current_goal_id, error_msg,
                        self._current_request_id, self._current_test_case_id
                    )
                self.is_stopping = True
                await self.stop_agent()
                return False
        except Exception as e:
            logger.error(f"Reconnection attempt failed: {str(e)}")
            self.reconnection_in_progress = False
            return False

    async def execute_automation(
        self,
        automation_uri: str,
        connection_url: str,
        task: str,
        goal_id: str,
        requestId: str,
        testCaseId: str,
        active_page_id: str,
        sensitiveData: Optional[dict] = None,
    ):
        """
        Connects to the automation server, sets up the agent, and starts the agent in the background.
        The agent will run until completion, or until we receive a stop message via Socket.IO.
        """
        self.sio = socketio.AsyncClient()
        # Store current execution parameters for reconnection
        self._current_automation_uri = automation_uri
        self._current_goal_id = goal_id
        self._current_request_id = requestId
        self._current_test_case_id = testCaseId
        self._current_active_page_id = active_page_id
        @self.sio.event
        async def disconnect(reason=None):
            logger.info(f"Disconnected from automation server: {reason}")
            if not self.is_stopping:
                await self._handle_reconnection()

        @self.sio.on("connect_error")
        async def on_connect_error(error):
            if not self.is_stopping:
                await self._handle_reconnection(f"WebSocket connection error: {str(error)}")

        try:
            # Initial connection with timeout
            await asyncio.wait_for(
                self.sio.connect(
                    automation_uri, 
                    transports=["websocket"], 
                    namespaces=["/"]
                ),
                timeout=30.0  # 30 seconds timeout
            )
            
            logger.info(f"Connected to automation server at {automation_uri}")

            async def send_message(msg: dict) -> bool:
                """
                Helper for sending messages via Socket.IO.
                """
                if self.sio.connected:
                        await self.sio.emit("message", json.dumps(msg), namespace="/", callback=True)
                        return True
                else:
                    logger.error("Socket.IO client is not connected. Cannot send message.")



            @self.sio.on("message", namespace="/")
            async def handle_incoming_message(msg_str):
                """
                If we receive a stop request from the server, stop the agent.
                """
                try:
                    msg = json.loads(msg_str)
                except Exception as ex:
                    logger.error(f"Error parsing incoming message: {str(ex)}")
                    return

                msg_type = msg.get("type")
                if msg_type == "AGENT_GOAL_STOP_REQ":
                    logger.info(
                        f"Received stop request from server for goal {goal_id}, "
                        f"requestId {requestId}, testCaseId {testCaseId}"
                    )
                    await self.stop_agent()

            # Prepare the browser
            browser = SupatestBrowser(
                config=BrowserConfig(
                    headless=False,
                    cdp_url=connection_url,
                )
            )

            controller = SupatestController(exclude_actions=['search_google', 'extract_content', 'scroll_to_text'])
            
            # Initialize agent with modified AzureChatOpenAI settings
            model = AzureChatOpenAI(
                model="gpt-4o",
                api_version="2024-10-21",
                model_kwargs={
                    "extra_headers": {
                        "Azure-Content-Safety-Action": "warn",
                        "Azure-Content-Safety-Policy-Version": "2024-01-01",
                    }
                },
                temperature=0.7,
            )

            # Build the agent
            self.agent = SupatestAgent(
                task=task,
                llm=model,
                browser=browser,
                controller=controller,
                send_message=send_message,
                goal_step_id=goal_id,
                requestId=requestId,
                testCaseId=testCaseId,
                sensitive_data=sensitiveData,
                active_page_id=active_page_id,
            )

            # Start the agent in the background
            logger.info("🤖 Starting the Supatest Agent task...")
            self.agent_task = asyncio.create_task(self.agent.run())

            # Wait for the agent to finish (either completes its task or is stopped)
            await self.agent_task

            logger.info("Agent run completed or was stopped.")

            # Small delay for final messages
            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Automation failed: {str(e)}", exc_info=True)
            # Notify the handler about the error
            await self.handler.emit_automation_error(self.sio, goal_id, str(e), requestId, testCaseId)
            await asyncio.sleep(1)
        finally:
            logger.info("Disconnecting from automation")
            if self.sio.connected:
                try:
                    await self.sio.disconnect()
                except Exception as e:
                    logger.error(f"Error during disconnect: {str(e)}")

    async def run_automation(self, goal_id: str, setup_data):
        """
        Called externally to start the entire flow.
        """
        try:
            if not setup_data:
                raise ValueError("Setup data not found")

            automation_uri = self._build_automation_uri(goal_id, setup_data)

            await self.execute_automation(
                automation_uri=automation_uri,
                connection_url=setup_data.connection_url,
                task=setup_data.task,
                goal_id=goal_id,
                requestId=setup_data.request_id,
                testCaseId=setup_data.test_case_id,
                sensitiveData=setup_data.sensitive_data,
                active_page_id=setup_data.active_page_id,
            )
        except Exception as e:
            logger.error(f"Automation failed: {str(e)}", exc_info=True)
            await self.handler.emit_automation_error(
                None, goal_id, str(e), setup_data.request_id, setup_data.test_case_id
            )

