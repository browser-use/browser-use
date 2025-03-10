import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class AutomationSetup:
    connection_url: str
    task: str
    test_case_id: str
    request_id: str
    sensitive_data: Optional[dict]
    active_page_id: str    
class SessionManager:
    def __init__(self):
        self._automation_setups: Dict[str, AutomationSetup] = {}
        self.connection_environments: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        
    @asynccontextmanager
    async def goal_session(self, goal_id: str):
        async with self._lock:
            try:
                yield self._automation_setups.get(goal_id)
            finally:
                if goal_id in self._automation_setups:
                    del self._automation_setups[goal_id]
                    
    async def store_automation_setup(self, goal_id: str, setup_data: dict):
        async with self._lock:
            self._automation_setups[goal_id] = AutomationSetup(
                connection_url=setup_data.get("connectionUrl"),
                task=setup_data.get("task"),
                test_case_id=setup_data.get("testCaseId"),
                request_id=setup_data.get("requestId"),
                sensitive_data=setup_data.get("sensitiveData"),
                active_page_id=setup_data.get("activeBrowserTabId")
            )
            
    async def get_automation_setup(self, goal_id: str) -> Optional[AutomationSetup]:
        async with self._lock:
            return self._automation_setups.get(goal_id)
            
    async def store_connection_environment(self, sid: str, environ: dict):
        async with self._lock:
            self.connection_environments[sid] = environ
            
    async def get_connection_environment(self, sid: str) -> Optional[dict]:
        async with self._lock:
            return self.connection_environments.get(sid)
            
    async def remove_connection_environment(self, sid: str):
        async with self._lock:
            if sid in self.connection_environments:
                del self.connection_environments[sid] 