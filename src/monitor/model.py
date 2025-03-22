import asyncio

class BaseMonitorAgent:
    """Base monitoring agent class"""
    def __init__(self):
        self.status_queue = asyncio.Queue()

    def get_status_queue_size(self):
        return self.status_queue.qsize()


class BrowserPluginMonitorAgent(BaseMonitorAgent):
    """Browser plugin monitoring agent implementation"""
    def __init__(self, browser_plugin_id: str, gpt_user_id: str):
        super().__init__()
        self.gpt_user_id = gpt_user_id
        self.browser_plugin_id = browser_plugin_id

    def set_gpt_user_id(self, gpt_user_id: str):
        self.gpt_user_id = gpt_user_id

    def get_gpt_user_id(self):
        """Get the GPT user ID associated with this agent"""
        return self.gpt_user_id