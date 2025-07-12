#!/usr/bin/env python3
"""
🌐 Browser-Use Web Backend (Version Réelle Simplifiée)
API FastAPI avec WebSocket pour chat temps réel - Intégration Browser-Use complète
"""

import asyncio
import os
import json
import logging
import sys
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

# Ajouter le chemin vers browser_use
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Configuration de l'environnement
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY
os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'  # Éviter les problèmes de logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Imports Browser-Use
try:
    from browser_use import Agent
    from browser_use.llm.openai.chat import ChatOpenAI
    BROWSER_USE_AVAILABLE = True
    print("✅ Browser-Use importé avec succès")
except ImportError as e:
    print(f"❌ Erreur import Browser-Use: {e}")
    BROWSER_USE_AVAILABLE = False

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration OpenAI
# OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') # This line is now redundant as OPENAI_API_KEY is defined globally

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
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connecté. Total: {len(self.active_connections)}")
        
        # Message de bienvenue
        status = "🚀 Browser-Use Web Backend connecté ! Intégration Browser-Use complète active." if BROWSER_USE_AVAILABLE else "⚠️ Browser-Use non disponible - Mode simulation"
        welcome_msg = ChatMessage(
            type="system",
            content=status,
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

# Instance globale
manager = ConnectionManager()

# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Démarrage Browser-Use Web Backend (Version Réelle Simplifiée)...")
    if BROWSER_USE_AVAILABLE:
        logger.info("✅ Backend prêt avec Browser-Use intégré !")
    else:
        logger.info("⚠️ Backend en mode simulation (Browser-Use non disponible)")
    yield
    # Shutdown
    logger.info("🛑 Arrêt du backend...")

# Application FastAPI
app = FastAPI(
    title="Browser-Use Web API (Réelle Simplifiée)",
    description="API complète pour Browser-Use avec WebSocket",
    version="2.0.0-real-simple",
    lifespan=lifespan
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production: spécifier les domaines
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialiser le modèle LLM
def create_llm():
    """Créer une instance du modèle OpenAI"""
    if not BROWSER_USE_AVAILABLE:
        return None
    return ChatOpenAI(
        model='gpt-4o-mini',
        api_key=OPENAI_API_KEY
    )

# Routes API
@app.get("/")
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "🌐 Browser-Use Web API (Version Réelle Simplifiée)",
        "version": "2.0.0-real-simple",
        "status": "active",
        "frontend": "http://localhost:3001",
        "websocket": "ws://localhost:8000/ws/chat",
        "docs": "http://localhost:8000/docs",
        "browser_use": "Intégration complète activée" if BROWSER_USE_AVAILABLE else "Non disponible - Mode simulation"
    }

@app.get("/api/status")
async def get_status():
    """Status de l'agent"""
    return AgentStatus(
        status="busy" if manager.agent_busy else "idle",
        current_task=manager.current_task,
        uptime=datetime.now().strftime("%H:%M:%S")
    )

# WebSocket pour chat temps réel
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket pour communication temps réel avec Browser-Use"""
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
                
                # Exécuter avec Browser-Use
                await execute_browser_use_task(task, websocket)
                
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
                    await execute_browser_use_task(voice_text, websocket)
                    
            elif data.get("type") == "ping":
                # Heartbeat
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client WebSocket déconnecté")
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        manager.disconnect(websocket)

async def execute_browser_use_task(task: str, websocket: WebSocket):
    """Exécuter une tâche avec le vrai Browser-Use"""
    if manager.agent_busy:
        busy_msg = ChatMessage(
            type="system",
            content="⏳ Browser-Use occupé, veuillez patienter...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.send_personal_message(busy_msg.dict(), websocket)
        return
        
    if not BROWSER_USE_AVAILABLE:
        error_msg = ChatMessage(
            type="error",
            content="❌ Browser-Use non disponible. Vérifiez l'installation.",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        return
        
    try:
        manager.agent_busy = True
        manager.current_task = task
        
        # Message de démarrage
        start_msg = ChatMessage(
            type="system",
            content="🚀 Démarrage Browser-Use...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(start_msg.dict())
        
        # Créer le modèle LLM
        llm = create_llm()
        if not llm:
            raise Exception("Impossible de créer le modèle LLM")
        
        # Message de progression
        progress_msg = ChatMessage(
            type="system",
            content="🧠 Initialisation de l'agent Browser-Use...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(progress_msg.dict())
        
        # Créer et configurer l'agent
        agent = Agent(task=task, llm=llm)
        manager.current_agent = agent
        
        # Message de lancement
        launch_msg = ChatMessage(
            type="system",
            content="🌐 Lancement du navigateur et analyse de la tâche...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(launch_msg.dict())
        
        # Exécuter la tâche Browser-Use
        result = await agent.run()
        
        # Message de succès avec résultat
        success_msg = ChatMessage(
            type="agent",
            content=f"🎉 Tâche terminée avec succès !\n\n📋 **Résultat:**\n{result}\n\n🤖 Exécuté par Browser-Use",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(success_msg.dict())
        
    except Exception as e:
        error_msg = ChatMessage(
            type="error",
            content=f"💥 Erreur lors de l'exécution Browser-Use:\n{str(e)[:300]}...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        logger.error(f"Erreur Browser-Use: {e}")
        
    finally:
        manager.agent_busy = False
        manager.current_task = None
        manager.current_agent = None

# Route de santé
@app.get("/health")
async def health_check():
    """Vérification de santé du service"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "connections": len(manager.active_connections),
        "agent_busy": manager.agent_busy,
        "browser_use": "integrated" if BROWSER_USE_AVAILABLE else "not_available",
        "version": "real-simple"
    }

# Page de test Browser-Use
@app.get("/test", response_class=HTMLResponse)
async def test_page():
    """Page de test pour Browser-Use"""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>🤖 Browser-Use Web Test (Version Réelle)</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #ffffff; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .messages {{ height: 400px; border: 1px solid #ddd; padding: 15px; overflow-y: scroll; background: #f9f9f9; margin: 20px 0; border-radius: 8px; }}
            input {{ width: 70%; padding: 12px; background: #fff; border: 1px solid #ddd; color: #333; border-radius: 6px; }}
            button {{ padding: 12px 20px; background: #3b82f6; border: none; color: white; cursor: pointer; margin-left: 10px; border-radius: 6px; }}
            button:hover {{ background: #2563eb; }}
            .status {{ padding: 12px; background: #f0f9ff; margin: 10px 0; border-radius: 6px; border-left: 4px solid #3b82f6; }}
            .success {{ background: #f0fdf4; border-left-color: #10b981; }}
            .error {{ background: #fef2f2; border-left-color: #ef4444; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Browser-Use Web Test (Version Réelle)</h1>
            <div class="status" id="status">🔴 Déconnecté</div>
            <div class="messages" id="messages"></div>
            <input type="text" id="messageInput" placeholder="Tapez votre tâche Browser-Use...">
            <button onclick="sendMessage()">Exécuter</button>
            <button onclick="sendVoice()">🎤 Vocal</button>
            
            <div style="margin-top: 20px; padding: 15px; background: #f8fafc; border-radius: 8px;">
                <h3>💡 Exemples de tâches:</h3>
                <ul>
                    <li><button onclick="setTask('Recherche les cours d\\'informatique au Collège Boréal')">Collège Boréal</button></li>
                    <li><button onclick="setTask('Trouve les dernières nouvelles sur l\\'IA')">Nouvelles IA</button></li>
                    <li><button onclick="setTask('Vérifie la météo à Sudbury')">Météo Sudbury</button></li>
                </ul>
                <p><strong>Status Browser-Use:</strong> {'✅ Intégré' if BROWSER_USE_AVAILABLE else '❌ Non disponible'}</p>
            </div>
        </div>
        
        <script>
            let ws = null;
            
            function connect() {{
                ws = new WebSocket('ws://localhost:8000/ws/chat');
                
                ws.onopen = function() {{
                    document.getElementById('status').innerHTML = '🟢 Connecté - Browser-Use {'Intégré' if BROWSER_USE_AVAILABLE else 'Non Disponible'}';
                    document.getElementById('status').className = 'status success';
                    addMessage('system', 'Connexion WebSocket Browser-Use établie');
                }};
                
                ws.onmessage = function(event) {{
                    const data = JSON.parse(event.data);
                    addMessage(data.type, data.content, data.sender);
                }};
                
                ws.onclose = function() {{
                    document.getElementById('status').innerHTML = '🔴 Déconnecté';
                    document.getElementById('status').className = 'status error';
                    addMessage('system', 'Connexion fermée');
                }};
            }}
            
            function addMessage(type, content, sender) {{
                const messages = document.getElementById('messages');
                const div = document.createElement('div');
                const time = new Date().toLocaleTimeString();
                // Fix XSS vulnerability by using textContent instead of innerHTML
                const timeSpan = document.createElement('strong');
                timeSpan.textContent = `[${time}] ${sender || type}:`;
                div.appendChild(timeSpan);
                div.appendChild(document.createTextNode(` ${content}`));
                if (type === 'error') div.style.color = 'red';
                if (type === 'agent') div.style.color = 'green';
                if (type === 'user') div.style.color = 'blue';
                messages.appendChild(div);
                messages.scrollTop = messages.scrollHeight;
            }}
            
            function sendMessage() {{
                const input = document.getElementById('messageInput');
                if (input.value.trim() && ws) {{
                    ws.send(JSON.stringify({{
                        type: 'user_message',
                        content: input.value
                    }}));
                    input.value = '';
                }}
            }}
            
            function sendVoice() {{
                if (ws) {{
                    ws.send(JSON.stringify({{
                        type: 'voice_input',
                        content: 'Test vocal avec Browser-Use'
                    }}));
                }}
            }}
            
            function setTask(task) {{
                document.getElementById('messageInput').value = task;
            }}
            
            document.getElementById('messageInput').addEventListener('keypress', function(e) {{
                if (e.key === 'Enter') {{
                    sendMessage();
                }}
            }});
            
            // Auto-connect
            connect();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# Point d'entrée principal
if __name__ == "__main__":
    logger.info("🚀 Démarrage du serveur Browser-Use Web Backend (Version Réelle Simplifiée)...")
    
    uvicorn.run(
        "main_real_simple:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        access_log=True
    ) 