import aiohttp
import logging
from typing import Dict, Any
from datetime import datetime
import json
import os

logger = logging.getLogger(__name__)

class WebhookManager:
    def __init__(self):
        self.notify_run_url = os.getenv("NOTIFY_WEBHOOK_URL","https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/notify-run")
        self.error_handler_url = os.getenv("ERROR_WEBHOOK_URL","https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/browser-use-vra-handler")
        self.status_url = os.getenv("STATUS_WEBHOOK_URL","https://vrautomatize-n8n.snrhk1.easypanel.host/webhook/status")
        self.session = None

    async def init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def notify_run(self, task_id: int, task_data: Dict[str, Any]):
        """Notifica sobre uma nova execução de tarefa"""
        try:
            await self.init_session()
            payload = {
                "task_id": task_id,
                "task_data": task_data,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with self.session.post(self.notify_run_url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Erro ao notificar run: {await response.text()}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de run: {str(e)}")

    async def notify_error(self, task_id: int, error: str, task_data: Dict[str, Any]):
        """Notifica sobre um erro na execução"""
        try:
            await self.init_session()
            payload = {
                "task_id": task_id,
                "error": error,
                "task_data": task_data,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with self.session.post(self.error_handler_url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Erro ao notificar erro: {await response.text()}")
        except Exception as e:
            logger.error(f"Erro ao enviar notificação de erro: {str(e)}")

    async def send_status(self, metrics: Dict[str, Any]):
        """Envia status e métricas do sistema"""
        try:
            await self.init_session()
            payload = {
                "metrics": metrics,
                "timestamp": datetime.utcnow().isoformat()
            }
            async with self.session.post(self.status_url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Erro ao enviar status: {await response.text()}")
        except Exception as e:
            logger.error(f"Erro ao enviar status: {str(e)}")

# Instância global do WebhookManager
webhook_manager = WebhookManager() 