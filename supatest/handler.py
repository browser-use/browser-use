import json
import logging

import socketio
from aiohttp import web

logger = logging.getLogger("py_ws_server")

class Handler:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.sio = socketio.AsyncServer(
            async_mode='aiohttp',
            cors_allowed_origins="*"
        )
        self.app = web.Application()
        self.sio.attach(self.app)
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        @self.sio.on('connect', namespace='/')
        async def connect(sid, environ, auth):
            logger.info(f"Client connected: {sid}")
            await self.session_manager.store_connection_environment(sid, environ)
        
        @self.sio.on('disconnect', namespace='/')
        async def disconnect(sid):
            logger.info(f"Client disconnected: {sid}")
            await self.session_manager.remove_connection_environment(sid)

    async def emit_setup_error(self, sid: str, error: str):
        await self.sio.emit("setup_error", {"ERROR": error}, to=sid)
        await self.sio.disconnect(sid)

    async def emit_setup_success(self, sid: str, requestId: str):
        await self.sio.emit(
            "setup_success",
            {
                "type": "AGENT_GOAL_START_RES",
                "requestId": requestId
            },
            to=sid
        )
        await self.sio.disconnect(sid)

    async def emit_automation_error(self, sio, goal_id: str, error_msg: str, requestId: str, testCaseId: str):
        try:
            if sio:
                error_message = {
                    "type": "AGENT_GOAL_STOP_RES",
                    "goalId": goal_id,
                    "requestId": requestId,
                    "testCaseId": testCaseId,
                    "error": error_msg,
                    "success": False
                }
                await sio.emit("message", json.dumps(error_message), namespace='/', callback=True)
                logger.info("Error message sent successfully")
        except Exception as e:
            logger.error(f"Failed to send error message: {str(e)}", exc_info=True) 