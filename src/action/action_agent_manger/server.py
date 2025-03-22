from typing import Optional
from langchain_openai import ChatOpenAI

from src.action.models import ActionAgentConfig
from src.action.server import ActionAgentService
from src.prompt import EXTEND_SYSTEM_MESSAGE

class ActionAgentManager:

    def __init__(self):
        self.action_agents = {}

    def register(self, agent_id: str, action_agent: ActionAgentService):
        self.action_agents[agent_id] = action_agent

    def get_agent(self, agent_id: str, action_agent_conf: ActionAgentConfig) -> Optional[ActionAgentService]:
        if agent_id not in self.action_agents:
            action_agent = ActionAgentService(
                task=action_agent_conf.task or '',
                llm=action_agent_conf.llm or ChatOpenAI(model_name="gpt-4o"),
                extend_system_message=EXTEND_SYSTEM_MESSAGE
            )
            self.register(agent_id, action_agent)
        return self.action_agents[agent_id]

    def unregister(self, agent_id: str):
        del self.action_agents[agent_id]