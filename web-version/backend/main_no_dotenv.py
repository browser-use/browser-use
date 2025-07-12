#!/usr/bin/env python3
"""
🌐 Browser-Use Web Backend (Avec configuration .env)
API FastAPI avec WebSocket pour chat temps réel - Intégration Browser-Use complète
"""

import asyncio
import os
import logging
import sys
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager

# Charger les variables d'environnement depuis config.env
def load_env_config():
    """Charger les variables d'environnement depuis config.env"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.env')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print(f"✅ Configuration chargée depuis {config_path}")
    else:
        print(f"⚠️ Fichier de configuration non trouvé: {config_path}")

# Charger la configuration
load_env_config()

# Configuration pour éviter les problèmes de logging
os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'

# Ajouter le chemin vers browser_use
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Imports Browser-Use avec gestion d'erreurs
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

# Configuration depuis les variables d'environnement
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 8000))

# Vérifier que la clé API est configurée
if not OPENAI_API_KEY or OPENAI_API_KEY == 'sk-proj-VOTRE_CLE_API_ICI':
    print("🔑 ATTENTION: Clé API OpenAI non configurée dans config.env")
    print("📝 Éditez le fichier config.env pour ajouter votre clé API")
else:
    print(f"🔑 Clé API OpenAI configurée (se termine par: ...{OPENAI_API_KEY[-6:]})")

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
    logger.info(f"🔧 Configuration: {OPENAI_MODEL} sur {HOST}:{PORT}")
    
    if not OPENAI_API_KEY or OPENAI_API_KEY == 'sk-proj-VOTRE_CLE_API_ICI':
        logger.warning("⚠️ Clé API OpenAI non configurée - Fonctionnalité limitée")
        logger.info("📝 Éditez config.env pour ajouter votre clé API")
    elif BROWSER_USE_AVAILABLE:
        logger.info("✅ Backend prêt avec Browser-Use intégré !")
    else:
        logger.info("⚠️ Backend en mode simulation (Browser-Use non disponible)")
    yield
    # Shutdown
    logger.info("🛑 Arrêt du backend...")

# Application FastAPI
app = FastAPI(
    title="Browser-Use Web API",
    description="API complète pour Browser-Use avec WebSocket et configuration .env",
    version="3.0.0-with-env",
    lifespan=lifespan
)

# Configuration CORS sécurisée
allowed_origins = os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:3001').split(',')
# Fix CORS origins parsing by trimming whitespace and filtering empty strings
allowed_origins = [origin.strip() for origin in allowed_origins if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Origines spécifiques seulement
    allow_credentials=False,  # Sécurité renforcée
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Initialiser le modèle LLM
def create_llm(model: str = None, temperature: float = None):
    """Créer une instance du modèle OpenAI avec paramètres configurables"""
    if not BROWSER_USE_AVAILABLE:
        return None
    return ChatOpenAI(
        model=model or OPENAI_MODEL,
        temperature=temperature or 0.7,
        api_key=OPENAI_API_KEY
    )

# Routes API
@app.get("/")
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "🌐 Browser-Use Web API (Sans .env)",
        "version": "2.0.0-no-dotenv",
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

@app.post("/api/execute")
async def execute_task(request: TaskRequest):
    """Exécuter une tâche avec Browser-Use"""
    if not await manager.acquire_agent_lock():
        raise HTTPException(status_code=409, detail="Agent occupé")
        
    try:
        manager.current_task = request.task
        
        # Broadcast début de tâche
        start_msg = ChatMessage(
            type="system",
            content=f"🎯 Exécution avec Browser-Use: {request.task}",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(start_msg.dict())
        
        # Créer et exécuter l'agent Browser-Use avec les paramètres du request
        llm = create_llm(model=request.model, temperature=request.temperature)
        if not llm:
            raise Exception("Browser-Use non disponible")
        agent = Agent(task=request.task, llm=llm)
        
        # Exécuter la tâche
        result = await agent.run()
        
        # Broadcast succès avec résultat
        success_msg = ChatMessage(
            type="agent",
            content=f"✅ Tâche terminée avec succès !\n\nRésultat: {result}",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(success_msg.dict())
        
        return {"status": "success", "result": str(result)}
        
    except Exception as e:
        error_msg = ChatMessage(
            type="error",
            content=f"❌ Erreur Browser-Use: {str(e)[:200]}...",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        logger.error(f"Erreur Browser-Use: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        await manager.release_agent_lock()

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
    if not await manager.acquire_agent_lock():
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
        await manager.release_agent_lock()
        return
        
    try:
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
        
        # Vérifier s'il y a des erreurs dans le résultat
        has_errors = False
        error_messages = []
        
        if hasattr(result, 'all_results'):
            for action_result in result.all_results:
                if hasattr(action_result, 'error') and action_result.error:
                    has_errors = True
                    error_messages.append(str(action_result.error))
        
        if has_errors:
            # Il y a des erreurs - traiter comme un échec
            error_summary = "\n".join(error_messages[:3])  # Limiter à 3 erreurs
            
            if "Incorrect API key" in error_summary:
                error_msg = ChatMessage(
                    type="error",
                    content="🔑 **ERREUR CLEF API OPENAI**\n\n❌ Votre clé API OpenAI n'est pas valide ou a expiré.\n\n🔧 **Solutions:**\n1. Vérifiez votre clé sur https://platform.openai.com/account/api-keys\n2. Générez une nouvelle clé si nécessaire\n3. Vérifiez que vous avez du crédit sur votre compte\n4. Mettez à jour la clé dans config.env",
                    timestamp=datetime.now().strftime("%H:%M:%S"),
                    sender="Système"
                )
            else:
                error_msg = ChatMessage(
                    type="error",
                    content=f"💥 **ERREUR BROWSER-USE**\n\n{error_summary[:500]}...",
                    timestamp=datetime.now().strftime("%H:%M:%S"),
                    sender="Browser-Use"
                )
            
            await manager.broadcast(error_msg.dict())
        else:
            # Succès réel
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
        "browser_use": "integrated" if BROWSER_USE_AVAILABLE else "not_available",
        "version": "no-dotenv"
    }

# Point d'entrée principal
if __name__ == "__main__":
    logger.info("🚀 Démarrage du serveur Browser-Use Web Backend...")
    logger.info(f"🌐 Serveur disponible sur http://{HOST}:{PORT}")
    logger.info("📚 Documentation API: http://localhost:8000/docs")
    logger.info("🔧 Configuration chargée depuis config.env")
    
    uvicorn.run(
        "main_no_dotenv:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
        access_log=True
    ) 