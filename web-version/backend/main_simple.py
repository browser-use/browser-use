#!/usr/bin/env python3
"""
🌐 Browser-Use Web Backend (Version Simple)
API FastAPI avec WebSocket pour chat temps réel - Version de test
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
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration environnement
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
# Note: In this simple version, the API key is not actually used
# This allows for local execution and automated tests
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set - running in test mode only")

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
        self._lock = asyncio.Lock()
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connecté. Total: {len(self.active_connections)}")
        
        # Message de bienvenue
        welcome_msg = ChatMessage(
            type="system",
            content="🚀 Browser-Use Web Backend connecté ! Version de test active.",
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
        self._lock.release()

# Instance globale
manager = ConnectionManager()

# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Démarrage Browser-Use Web Backend (Version Simple)...")
    logger.info("✅ Backend prêt !")
    yield
    # Shutdown
    logger.info("🛑 Arrêt du backend...")

# Application FastAPI
app = FastAPI(
    title="Browser-Use Web API (Simple)",
    description="API de test pour Browser-Use avec WebSocket",
    version="2.0.0-simple",
    lifespan=lifespan
)

# Configuration CORS
allowed_origins = os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:3001').split(',')
allowed_origins = [origin.strip() for origin in allowed_origins if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Origines configurables depuis l'environnement
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes API

@app.get("/")
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "🌐 Browser-Use Web API (Version Simple)",
        "version": "2.0.0-simple",
        "status": "active",
        "frontend": "http://localhost:3000",
        "websocket": "ws://localhost:8000/ws/chat",
        "docs": "http://localhost:8000/docs",
        "note": "Version de test sans browser-use complet"
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
    """Exécuter une tâche (simulation pour tests)"""
    if not await manager.acquire_agent_lock():
        raise HTTPException(status_code=409, detail="Agent occupé")
        
    try:
        manager.current_task = request.task
        
        # Broadcast début de tâche
        start_msg = ChatMessage(
            type="system",
            content=f"🎯 Simulation de tâche: {request.task}",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(start_msg.dict())
        
        # Simulation d'exécution
        await asyncio.sleep(2)  # Simule le traitement
        
        # Broadcast succès
        success_msg = ChatMessage(
            type="agent",
            content="✅ Simulation terminée ! (Version de test)",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(success_msg.dict())
        
        return {"status": "success", "message": "Simulation exécutée"}
        
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
                
                # Traitement simulé
                await process_task_simulation(task, websocket)
                
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
                    await process_task_simulation(voice_text, websocket)
                    
            elif data.get("type") == "ping":
                # Heartbeat
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client WebSocket déconnecté")
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        manager.disconnect(websocket)

async def process_task_simulation(task: str, websocket: WebSocket):
    """Simulation de traitement de tâche"""
    if not await manager.acquire_agent_lock():
        busy_msg = ChatMessage(
            type="system",
            content="⏳ Agent occupé, veuillez patienter...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.send_personal_message(busy_msg.dict(), websocket)
        return
        
    try:
        manager.current_task = task
        
        # Message de démarrage
        start_msg = ChatMessage(
            type="system",
            content="🔄 Simulation de traitement...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(start_msg.dict())
        
        # Simulation de progression
        progress_messages = [
            "🧠 Analyse simulée...",
            "🎯 Planification simulée...",
            "⚡ Exécution simulée...",
            "✨ Finalisation simulée..."
        ]
        
        for i, msg in enumerate(progress_messages):
            await asyncio.sleep(0.8)  # Délai pour l'effet visuel
            progress_msg = ChatMessage(
                type="system",
                content=msg,
                timestamp=datetime.now().strftime("%H:%M:%S"),
                sender="Agent"
            )
            await manager.broadcast(progress_msg.dict())
            
        # Message de succès
        success_msg = ChatMessage(
            type="agent",
            content=f"🎉 Simulation terminée ! Tâche: '{task}' (Version de test - Browser-Use sera intégré dans la version finale)",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Agent"
        )
        await manager.broadcast(success_msg.dict())
        
    except Exception as e:
        error_msg = ChatMessage(
            type="error",
            content=f"💥 Erreur lors de la simulation: {str(e)[:80]}...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        logger.error(f"Erreur simulation tâche: {e}")
        
    finally:
        await manager.release_agent_lock()

# Route de santé
@app.get("/health")
async def health_check():
    """Vérification de santé du service"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "connections": len(manager.active_connections),
        "agent_busy": manager.agent_busy,
        "version": "simple-test"
    }

# Page de test simple
@app.get("/test", response_class=HTMLResponse)
async def test_page():
    """Page de test simple pour vérifier le WebSocket"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🤖 Browser-Use Web Test</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #0f0f0f; color: white; }
            .container { max-width: 600px; margin: 0 auto; }
            .messages { height: 300px; border: 1px solid #333; padding: 10px; overflow-y: scroll; background: #1a1a1a; margin: 20px 0; }
            input { width: 70%; padding: 10px; background: #2a2a2a; border: 1px solid #444; color: white; }
            button { padding: 10px 20px; background: #4a9eff; border: none; color: white; cursor: pointer; margin-left: 10px; }
            .status { padding: 10px; background: #2a2a2a; margin: 10px 0; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Browser-Use Web Test</h1>
            <div class="status" id="status">🔴 Déconnecté</div>
            <div class="messages" id="messages"></div>
            <input type="text" id="messageInput" placeholder="Tapez votre message...">
            <button onclick="sendMessage()">Envoyer</button>
            <button onclick="sendVoice()">🎤 Vocal Test</button>
        </div>
        
        <script>
            let ws = null;
            
            function connect() {
                ws = new WebSocket('ws://localhost:8000/ws/chat');
                
                ws.onopen = function() {
                    document.getElementById('status').innerHTML = '🟢 Connecté';
                    addMessage('system', 'Connexion WebSocket établie');
                };
                
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    addMessage(data.type, data.content, data.sender);
                };
                
                ws.onclose = function() {
                    document.getElementById('status').innerHTML = '🔴 Déconnecté';
                    addMessage('system', 'Connexion fermée');
                };
            }
            
            function addMessage(type, content, sender) {
                const messages = document.getElementById('messages');
                const div = document.createElement('div');
                div.innerHTML = `<strong>${sender || type}:</strong> ${content}`;
                messages.appendChild(div);
                messages.scrollTop = messages.scrollHeight;
            }
            
            function sendMessage() {
                const input = document.getElementById('messageInput');
                if (input.value.trim() && ws) {
                    ws.send(JSON.stringify({
                        type: 'user_message',
                        content: input.value
                    }));
                    input.value = '';
                }
            }
            
            function sendVoice() {
                if (ws) {
                    ws.send(JSON.stringify({
                        type: 'voice_input',
                        content: 'Test vocal simulé'
                    }));
                }
            }
            
            document.getElementById('messageInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
            
            // Auto-connect
            connect();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# Point d'entrée principal
if __name__ == "__main__":
    logger.info("🚀 Démarrage du serveur Browser-Use Web Backend (Version Simple)...")
    
    uvicorn.run(
        "main_simple:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Désactiver auto-reload
        log_level="info",
        access_log=True
    ) 