import asyncio

from typing import AsyncGenerator, Dict, Any

from src.monitor.model import BrowserPluginMonitorAgent


class MonitorService:
    """Service for managing monitoring agents"""

    def __init__(self):
        self.agents: Dict[str, BrowserPluginMonitorAgent] = {}

    def get_agents(self) -> Dict[str, BrowserPluginMonitorAgent]:
        """Get all registered agents"""
        return self.agents

    async def get_agent_updates(self, agent_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Get updates generator for specific agent

        Args:
            agent_id: Agent identifier

        Yields:
            Dict containing agent status updates
        """
        if agent_id not in self.agents:
            return

        agent = self.agents[agent_id]
        while True:
            try:
                # 从代理的状态队列中获取更新
                status = await agent.status_queue.get()
                yield status
            except asyncio.CancelledError:
                break
            except Exception as e:
                yield {"status": "error", "message": str(e)}
                break

    def register_agent(self, agent_id: str, agent: BrowserPluginMonitorAgent):
        """注册一个新的代理实例"""
        self.agents[agent_id] = agent

    def unregister_agent(self, agent_id: str):
        """注销一个代理实例"""
        if agent_id in self.agents:
            del self.agents[agent_id]

    def get_agent(self, agent_id: str) -> BrowserPluginMonitorAgent:
        """
        Get agent instance by ID

        Args:
            agent_id: Agent identifier

        Returns:
            BrowserPluginMonitorAgent: Agent instance

        Raises:
            KeyError: When agent ID doesn't exist
        """
        if agent_id not in self.agents:
            raise KeyError(f"Agent not found: {agent_id}")
        return self.agents[agent_id]