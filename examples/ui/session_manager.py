"""
Gerenciador de sessões para múltiplos agentes browser-use.

Responsabilidades:
- Criar e gerenciar agentes ativos
- Conectar callbacks aos WebSockets
- Controlar execução (pause/resume/stop)
- Manter histórico de eventos
"""

import asyncio
import base64
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import WebSocket

from browser_use import Agent
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext

logger = logging.getLogger(__name__)


class SessionManager:
    """Gerencia múltiplas sessões de agentes browser-use"""
    
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.websockets: Dict[str, List[WebSocket]] = {}
        
    async def create_agent_session(
        self,
        session_id: str,
        task: str,
        llm_provider: str = "openai",
        llm_model: str = "gpt-4o-mini",
        max_steps: int = 10
    ):
        """
        Cria uma nova sessão de agente e inicia execução.
        
        Args:
            session_id: ID único da sessão
            task: Tarefa a ser executada
            llm_provider: Provedor do LLM (openai, anthropic, google, etc)
            llm_model: Modelo específico
            max_steps: Número máximo de steps
        """
        try:
            logger.info(f"Criando sessão {session_id} com tarefa: {task}")
            
            # Criar diretório para screenshots
            screenshot_dir = Path(f"/tmp/browser-use-sessions/{session_id}/screenshots")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            
            # Inicializar sessão
            self.sessions[session_id] = {
                "task": task,
                "active": True,
                "max_steps": max_steps,
                "screenshot_dir": str(screenshot_dir),
                "history": [],
                "agent": None,
                "created_at": datetime.now().isoformat()
            }
            
            # Criar LLM baseado no provider
            llm = self._create_llm(llm_provider, llm_model)
            
            # Criar browser context
            browser = Browser()
            context = await browser.new_context()
            
            # Callbacks para streaming
            async def on_step_callback(browser_state, model_output, step_number):
                """Callback chamado a cada step do agente"""
                await self._handle_step(session_id, browser_state, model_output, step_number)
            
            async def on_done_callback(history):
                """Callback chamado quando agente termina"""
                await self._handle_done(session_id, history)
            
            # Criar agente
            agent = Agent(
                task=task,
                llm=llm,
                browser_context=context,
                register_new_step_callback=on_step_callback,
                register_done_callback=on_done_callback
            )
            
            self.sessions[session_id]["agent"] = agent
            self.sessions[session_id]["browser"] = browser
            self.sessions[session_id]["context"] = context
            
            # Enviar evento de início
            await self._broadcast_to_session(session_id, {
                "type": "agent_started",
                "session_id": session_id,
                "task": task,
                "max_steps": max_steps,
                "timestamp": datetime.now().isoformat()
            })
            
            # Executar agente
            logger.info(f"Iniciando execução do agente {session_id}")
            history = await agent.run(max_steps=max_steps)
            
            logger.info(f"Agente {session_id} concluído")
            
        except Exception as e:
            logger.error(f"Erro ao criar sessão {session_id}: {e}")
            await self._broadcast_to_session(session_id, {
                "type": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            self.sessions[session_id]["active"] = False
    
    def _create_llm(self, provider: str, model: str):
        """Cria instância do LLM baseado no provider"""
        
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=model)
        
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model)
        
        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(model=model)
        
        elif provider == "groq":
            from langchain_groq import ChatGroq
            return ChatGroq(model=model)
        
        else:
            # Default para OpenAI
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model="gpt-4o-mini")
    
    async def _handle_step(self, session_id: str, browser_state, model_output, step_number: int):
        """
        Processa e transmite dados de cada step do agente.
        
        Args:
            session_id: ID da sessão
            browser_state: Estado atual do browser
            model_output: Output do modelo LLM
            step_number: Número do step atual
        """
        try:
            session = self.sessions.get(session_id)
            if not session:
                return
            
            # Capturar screenshot
            screenshot_b64 = None
            if browser_state and hasattr(browser_state, 'screenshot'):
                screenshot = browser_state.screenshot
                if screenshot:
                    # Salvar screenshot em arquivo
                    screenshot_path = Path(session["screenshot_dir"]) / f"step_{step_number}.png"
                    screenshot_path.write_bytes(screenshot)
                    
                    # Converter para base64 para enviar via WebSocket
                    screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
            
            # Extrair informações do model_output
            action_name = None
            thought = None
            extracted_content = None
            
            if model_output:
                if hasattr(model_output, 'action'):
                    action = model_output.action
                    if action:
                        action_name = action.__class__.__name__ if hasattr(action, '__class__') else str(action)
                
                if hasattr(model_output, 'current_state') and model_output.current_state:
                    thought = model_output.current_state.get('evaluation_previous_goal')
                
                if hasattr(model_output, 'extracted_content'):
                    extracted_content = model_output.extracted_content
            
            # Dados do step
            step_data = {
                "type": "step",
                "step_number": step_number,
                "url": browser_state.url if browser_state and hasattr(browser_state, 'url') else None,
                "title": browser_state.title if browser_state and hasattr(browser_state, 'title') else None,
                "screenshot": screenshot_b64,
                "action": action_name,
                "thought": thought,
                "extracted_content": extracted_content,
                "timestamp": datetime.now().isoformat()
            }
            
            # Adicionar ao histórico
            session["history"].append(step_data)
            
            # Broadcast para todos os WebSockets conectados
            await self._broadcast_to_session(session_id, step_data)
            
            logger.info(f"Step {step_number} processado para sessão {session_id}")
            
        except Exception as e:
            logger.error(f"Erro ao processar step {step_number} da sessão {session_id}: {e}")
    
    async def _handle_done(self, session_id: str, history):
        """
        Processa finalização do agente.
        
        Args:
            session_id: ID da sessão
            history: Histórico completo da execução
        """
        try:
            session = self.sessions.get(session_id)
            if not session:
                return
            
            # Marcar sessão como inativa
            session["active"] = False
            
            # Extrair resultado final
            final_result = None
            if history and hasattr(history, 'final_result'):
                final_result = history.final_result()
            
            # Enviar evento de conclusão
            done_data = {
                "type": "done",
                "session_id": session_id,
                "final_result": final_result,
                "total_steps": len(session["history"]),
                "timestamp": datetime.now().isoformat()
            }
            
            await self._broadcast_to_session(session_id, done_data)
            
            logger.info(f"Sessão {session_id} finalizada com sucesso")
            
        except Exception as e:
            logger.error(f"Erro ao finalizar sessão {session_id}: {e}")
    
    async def _broadcast_to_session(self, session_id: str, data: dict):
        """
        Envia dados para todos os WebSockets conectados a uma sessão.
        
        Args:
            session_id: ID da sessão
            data: Dados a serem enviados
        """
        if session_id not in self.websockets:
            return
        
        # Lista de WebSockets a remover (desconectados)
        to_remove = []
        
        for ws in self.websockets[session_id]:
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.warning(f"Erro ao enviar para WebSocket: {e}")
                to_remove.append(ws)
        
        # Remover WebSockets desconectados
        for ws in to_remove:
            self.websockets[session_id].remove(ws)
    
    async def register_websocket(self, session_id: str, websocket: WebSocket):
        """
        Registra um WebSocket para receber eventos de uma sessão.
        
        Args:
            session_id: ID da sessão
            websocket: Conexão WebSocket
        """
        if session_id not in self.websockets:
            self.websockets[session_id] = []
        
        self.websockets[session_id].append(websocket)
        logger.info(f"WebSocket registrado para sessão {session_id}")
        
        # Enviar histórico existente para novo cliente
        session = self.sessions.get(session_id)
        if session and session.get("history"):
            for event in session["history"]:
                try:
                    await websocket.send_json(event)
                except Exception as e:
                    logger.warning(f"Erro ao enviar histórico: {e}")
    
    async def unregister_websocket(self, session_id: str, websocket: WebSocket):
        """
        Remove um WebSocket de uma sessão.
        
        Args:
            session_id: ID da sessão
            websocket: Conexão WebSocket
        """
        if session_id in self.websockets and websocket in self.websockets[session_id]:
            self.websockets[session_id].remove(websocket)
            logger.info(f"WebSocket removido da sessão {session_id}")
    
    async def control_agent(self, session_id: str, action: str):
        """
        Controla execução do agente (pause/resume/stop).
        
        Args:
            session_id: ID da sessão
            action: Ação a executar ('pause', 'resume', 'stop')
            
        Returns:
            Resultado da operação
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Sessão {session_id} não encontrada")
        
        agent = session.get("agent")
        if not agent:
            raise ValueError(f"Agente não encontrado para sessão {session_id}")
        
        if action == "pause":
            agent.pause()
            logger.info(f"Agente {session_id} pausado")
            await self._broadcast_to_session(session_id, {
                "type": "control",
                "action": "paused",
                "timestamp": datetime.now().isoformat()
            })
            return "paused"
        
        elif action == "resume":
            agent.resume()
            logger.info(f"Agente {session_id} resumido")
            await self._broadcast_to_session(session_id, {
                "type": "control",
                "action": "resumed",
                "timestamp": datetime.now().isoformat()
            })
            return "resumed"
        
        elif action == "stop":
            agent.stop()
            session["active"] = False
            logger.info(f"Agente {session_id} parado")
            await self._broadcast_to_session(session_id, {
                "type": "control",
                "action": "stopped",
                "timestamp": datetime.now().isoformat()
            })
            return "stopped"
        
        else:
            raise ValueError(f"Ação inválida: {action}")
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtém dados de uma sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Dicionário com dados da sessão ou None
        """
        return self.sessions.get(session_id)
    
    def get_history(self, session_id: str) -> Optional[List[dict]]:
        """
        Obtém histórico de eventos de uma sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Lista de eventos ou None
        """
        session = self.sessions.get(session_id)
        if session:
            return session.get("history", [])
        return None
    
    async def cleanup_session(self, session_id: str):
        """
        Remove uma sessão e libera recursos.
        
        Args:
            session_id: ID da sessão
        """
        session = self.sessions.get(session_id)
        if not session:
            return
        
        try:
            # Fechar browser context
            context = session.get("context")
            if context:
                await context.close()
            
            # Fechar browser
            browser = session.get("browser")
            if browser:
                await browser.close()
            
            # Remover sessão
            del self.sessions[session_id]
            
            # Remover WebSockets
            if session_id in self.websockets:
                del self.websockets[session_id]
            
            logger.info(f"Sessão {session_id} removida e recursos liberados")
            
        except Exception as e:
            logger.error(f"Erro ao limpar sessão {session_id}: {e}")
    
    async def cleanup_all_sessions(self):
        """Remove todas as sessões e libera recursos"""
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            await self.cleanup_session(session_id)
        
        logger.info("Todas as sessões foram limpas")
