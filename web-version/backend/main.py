#!/usr/bin/env python3
"""
🌐 Browser-Use Web Backend
API FastAPI avec WebSocket pour chat temps réel et intégration Browser-Use
"""

import asyncio
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uvicorn

# Browser-Use integration
from browser_use import Agent
from browser_use.llm import ChatOpenAI

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration environnement
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

# Models Pydantic
class ChatMessage(BaseModel):
    type: str  # "user", "agent", "system", "error"
    content: str
    timestamp: Optional[str] = None
    sender: Optional[str] = None

class TaskRequest(BaseModel):
    task: str
    model: str = "gpt-4o-mini"
    temperature: float = 0.7

class AgentStatus(BaseModel):
    status: str  # "idle", "busy", "error"
    current_task: Optional[str] = None
    uptime: Optional[str] = None

# Gestionnaire de connexions WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.agent_busy = False
        self.current_task = None
        self.current_agent = None
        self._lock = asyncio.Lock()
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connecté. Total: {len(self.active_connections)}")
        
        # Message de bienvenue
        welcome_msg = ChatMessage(
            type="system",
            content="🚀 Browser-Use Web Backend connecté !",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await self.send_personal_message(welcome_msg.dict(), websocket)
        
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Client déconnecté. Total: {len(self.active_connections)}")
        
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Erreur envoi message: {e}")
            self.disconnect(websocket)
            
    async def broadcast(self, message: dict):
        for connection in self.active_connections.copy():
            await self.send_personal_message(message, connection)
            
    async def acquire_agent_lock(self):
        """Acquire lock for agent execution"""
        await self._lock.acquire()
        if self.agent_busy:
            self._lock.release()
            return False
        self.agent_busy = True
        return True
        
    async def release_agent_lock(self):
        """Release lock for agent execution"""
        self.agent_busy = False
        self.current_task = None
        self.current_agent = None
        self._lock.release()

# Instance globale
manager = ConnectionManager()

# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Démarrage Browser-Use Web Backend...")
    logger.info("✅ Backend prêt !")
    yield
    # Shutdown
    logger.info("🛑 Arrêt du backend...")

# Application FastAPI
app = FastAPI(
    title="Browser-Use Web API",
    description="API moderne pour Browser-Use avec WebSocket",
    version="2.0.0",
    lifespan=lifespan
)

# Configuration CORS sécurisée
allowed_origins = os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:3001').split(',')
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Origines configurables depuis l'environnement
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Routes API

@app.get("/")
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "🌐 Browser-Use Web API",
        "version": "2.0.0",
        "status": "active",
        "frontend": "http://localhost:3000",
        "websocket": "ws://localhost:8000/ws/chat",
        "docs": "http://localhost:8000/docs"
    }

@app.get("/api/status")
async def get_status():
    """Status de l'agent"""
    return AgentStatus(
        status="busy" if manager.agent_busy else "idle",
        current_task=manager.current_task,
        uptime=datetime.now().strftime("%H:%M:%S")
    )

@app.post("/api/execute")
async def execute_task(request: TaskRequest):
    """Exécuter une tâche Browser-Use (alternative REST)"""
    if not await manager.acquire_agent_lock():
        raise HTTPException(status_code=409, detail="Agent occupé")
        
    try:
        manager.current_task = request.task
        
        # Broadcast début de tâche
        start_msg = ChatMessage(
            type="system",
            content=f"🎯 Démarrage de la tâche: {request.task}",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(start_msg.dict())
        
        # Exécution Browser-Use
        agent = Agent(
            task=request.task,
            llm=ChatOpenAI(model=request.model, temperature=request.temperature),
        )
        
        # Exécution asynchrone
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: asyncio.run(agent.run()))
        
        # Broadcast succès
        success_msg = ChatMessage(
            type="agent",
            content="✅ Tâche accomplie avec succès !",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(success_msg.dict())
        
        return {"status": "success", "message": "Tâche exécutée"}
        
    except Exception as e:
        error_msg = ChatMessage(
            type="error",
            content=f"❌ Erreur: {str(e)[:100]}...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        await manager.release_agent_lock()

# WebSocket pour chat temps réel
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket pour communication temps réel"""
    await manager.connect(websocket)
    
    try:
        while True:
            # Recevoir message du client
            data = await websocket.receive_json()
            logger.info(f"Message reçu: {data}")
            
            if data.get("type") == "user_message":
                task = data.get("content", "").strip()
                
                if not task:
                    continue
                    
                # Broadcast message utilisateur
                user_msg = ChatMessage(
                    type="user",
                    content=task,
                    timestamp=datetime.now().strftime("%H:%M:%S"),
                    sender="Vous"
                )
                await manager.broadcast(user_msg.dict())
                
                # Traitement avec Browser-Use
                await process_task_websocket(task, websocket)
                
            elif data.get("type") == "voice_input":
                # Traitement vocal
                voice_text = data.get("content", "")
                voice_msg = ChatMessage(
                    type="user",
                    content=f"🎤 Vocal: « {voice_text} »",
                    timestamp=datetime.now().strftime("%H:%M:%S"),
                    sender="Vocal"
                )
                await manager.broadcast(voice_msg.dict())
                
                # Exécuter si c'est une commande
                if voice_text.strip():
                    await process_task_websocket(voice_text, websocket)
                    
            elif data.get("type") == "ping":
                # Heartbeat
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client WebSocket déconnecté")
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        manager.disconnect(websocket)

async def process_task_websocket(task: str, websocket: WebSocket):
    """Traiter une tâche Browser-Use via WebSocket"""
    if manager.agent_busy:
        busy_msg = ChatMessage(
            type="system",
            content="⏳ Agent occupé, veuillez patienter...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.send_personal_message(busy_msg.dict(), websocket)
        return
        
    try:
        manager.agent_busy = True
        manager.current_task = task
        
        # Message de démarrage
        start_msg = ChatMessage(
            type="system",
            content="🔄 Traitement en cours...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(start_msg.dict())
        
        # Simulation de progression (optionnel)
        progress_messages = [
            "🧠 Analyse de la demande...",
            "🎯 Planification des actions...",
            "⚡ Exécution en cours...",
            "✨ Finalisation..."
        ]
        
        for i, msg in enumerate(progress_messages):
            await asyncio.sleep(0.5)  # Délai pour l'effet visuel
            progress_msg = ChatMessage(
                type="system",
                content=msg,
                timestamp=datetime.now().strftime("%H:%M:%S"),
                sender="Agent"
            )
            await manager.broadcast(progress_msg.dict())
            
        # Exécution Browser-Use
        agent = Agent(
            task=task,
            llm=ChatOpenAI(model="gpt-4o-mini", temperature=0.7),
        )
        
        # Exécution dans un thread séparé
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: asyncio.run(agent.run()))
        
        # Message de succès
        success_msg = ChatMessage(
            type="agent",
            content="🎉 Tâche accomplie avec succès ! L'agent a terminé toutes les actions requises.",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(success_msg.dict())
        
    except Exception as e:
        error_msg = ChatMessage(
            type="error",
            content=f"💥 Erreur lors de l'exécution: {str(e)[:80]}...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        logger.error(f"Erreur traitement tâche: {e}")
        
    finally:
        manager.agent_busy = False
        manager.current_task = None

# Route de santé
@app.get("/health")
async def health_check():
    """Vérification de santé du service"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "connections": len(manager.active_connections),
        "agent_busy": manager.agent_busy
    }

# Point d'entrée principal
if __name__ == "__main__":
    logger.info("🚀 Démarrage du serveur Browser-Use Web Backend...")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        access_log=True
    ) 