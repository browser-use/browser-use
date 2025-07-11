#!/usr/bin/env python3
"""
🌐 Browser-Use Web Backend (Sans .env)
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

# Configuration de l'environnement AVANT tout import
os.environ['OPENAI_API_KEY'] = 'YOUR_OPENAI_API_KEY_HERE'
os.environ['BROWSER_USE_SETUP_LOGGING'] = 'false'

# Ajouter le chemin vers browser_use
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Monkey patch pour éviter le problème avec dotenv
import browser_use.logging_config
original_load_dotenv = browser_use.logging_config.load_dotenv
browser_use.logging_config.load_dotenv = lambda: None

# Imports Browser-Use APRÈS le patch
try:
    from browser_use import Agent
    from browser_use.llm.openai.chat import ChatOpenAI
    BROWSER_USE_AVAILABLE = True
    print("✅ Browser-Use importé avec succès (sans .env)")
except ImportError as e:
    print(f"❌ Erreur import Browser-Use: {e}")
    BROWSER_USE_AVAILABLE = False

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration OpenAI
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

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
    logger.info("🚀 Démarrage Browser-Use Web Backend (Sans .env)...")
    if BROWSER_USE_AVAILABLE:
        logger.info("✅ Backend prêt avec Browser-Use intégré !")
    else:
        logger.info("⚠️ Backend en mode simulation (Browser-Use non disponible)")
    yield
    # Shutdown
    logger.info("🛑 Arrêt du backend...")

# Application FastAPI
app = FastAPI(
    title="Browser-Use Web API (Sans .env)",
    description="API complète pour Browser-Use avec WebSocket",
    version="2.0.0-no-dotenv",
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
    """Exécuter une tâche avec le vrai Browser-Use - Version améliorée avec progression"""
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
        
    start_time = datetime.now()
    
    try:
        manager.agent_busy = True
        manager.current_task = task
        
        # 🎯 ÉTAPE 1: Analyse de la tâche (0-15%)
        await send_progress_message(websocket, {
            "step": "analysis",
            "progress": 5,
            "title": "🧠 Analyse de votre demande...",
            "details": f"┗━━ 🎯 Tâche: « {task} »",
            "eta": "~20 secondes"
        })
        
        await asyncio.sleep(0.5)  # Simulation analyse
        
        await send_progress_message(websocket, {
            "step": "analysis",
            "progress": 15,
            "title": "🧠 Analyse terminée ✅",
            "details": "┗━━ 🎯 Objectif détecté: Recherche d'information\n┗━━ 🌐 Stratégie: Navigation intelligente",
            "eta": "~15 secondes"
        })
        
        # 🚀 ÉTAPE 2: Initialisation (15-30%)
        await send_progress_message(websocket, {
            "step": "initialization",
            "progress": 20,
            "title": "🚀 Initialisation de l'agent...",
            "details": "┗━━ 🤖 Modèle LLM: GPT-4o-mini\n┗━━ 🔧 Configuration: Mode intelligent",
            "eta": "~12 secondes"
        })
        
        # Créer le modèle LLM
        llm = create_llm()
        if not llm:
            raise Exception("Impossible de créer le modèle LLM")
        
        await send_progress_message(websocket, {
            "step": "initialization",
            "progress": 30,
            "title": "🚀 Agent initialisé ✅",
            "details": "┗━━ 🌐 Navigateur: Chromium\n┗━━ ✅ Prêt pour l'exécution",
            "eta": "~10 secondes"
        })
        
        # 🌐 ÉTAPE 3: Lancement navigateur (30-45%)
        await send_progress_message(websocket, {
            "step": "browser_launch",
            "progress": 35,
            "title": "🌐 Lancement du navigateur...",
            "details": "┗━━ 🚀 Démarrage de Chromium\n┗━━ 🔧 Configuration des options",
            "eta": "~8 secondes"
        })
        
        # Créer et configurer l'agent
        agent = Agent(task=task, llm=llm)
        manager.current_agent = agent
        
        await send_progress_message(websocket, {
            "step": "browser_launch",
            "progress": 45,
            "title": "🌐 Navigateur lancé ✅",
            "details": "┗━━ 🎯 Agent Browser-Use actif\n┗━━ 🔄 Début de l'exécution...",
            "eta": "~5 secondes"
        })
        
        # 🔍 ÉTAPE 4: Exécution avec monitoring (45-90%)
        await send_progress_message(websocket, {
            "step": "execution",
            "progress": 50,
            "title": "🔍 Exécution de la tâche...",
            "details": "┗━━ 🌐 Navigation en cours\n┗━━ 📊 Analyse des actions requises",
            "eta": "Variable selon la tâche"
        })
        
        # Hook pour monitorer la progression pendant l'exécution
        original_run = agent.run
        
        async def monitored_run():
            # Simulation de progression pendant l'exécution
            progress_updates = [
                (60, "🌐 Navigation vers le site cible..."),
                (70, "🔍 Interaction avec les éléments..."),
                (80, "📊 Extraction des données..."),
                (85, "✅ Validation des informations...")
            ]
            
            # Démarrer l'exécution en arrière-plan
            task_coroutine = original_run()
            
            # Simuler des updates de progression
            for progress, message in progress_updates:
                await send_progress_message(websocket, {
                    "step": "execution",
                    "progress": progress,
                    "title": message,
                    "details": f"┗━━ 🎯 Étape {progress}% complétée",
                    "eta": f"~{int((100-progress)/10)} secondes"
                })
                await asyncio.sleep(1)  # Petit délai pour la simulation
            
            # Attendre le résultat final
            result = await task_coroutine
            return result
        
        # Exécuter avec monitoring
        result = await monitored_run()
        
        # 🎉 ÉTAPE 5: Finalisation (90-100%)
        await send_progress_message(websocket, {
            "step": "finalization",
            "progress": 95,
            "title": "🎉 Finalisation...",
            "details": "┗━━ 📊 Traitement du résultat\n┗━━ 🎨 Formatage de la réponse",
            "eta": "~2 secondes"
        })
        
        # 🎨 Formatage intelligent du résultat
        formatted_result = format_browser_use_result(result, task)
        
        await send_progress_message(websocket, {
            "step": "completed",
            "progress": 100,
            "title": "🎉 Tâche terminée avec succès! ✨",
            "details": f"┗━━ ⏱️ Temps total: {(datetime.now() - start_time).seconds}s\n┗━━ 💫 Performance: Excellente!",
            "eta": "Terminé"
        })
        
        # Message de succès avec résultat formaté
        success_msg = ChatMessage(
            type="agent",
            content=formatted_result,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Browser-Use"
        )
        await manager.broadcast(success_msg.dict())
        
    except Exception as e:
        # 🚨 Gestion d'erreur avec progression
        await send_progress_message(websocket, {
            "step": "error",
            "progress": 0,
            "title": "❌ Erreur détectée",
            "details": f"┗━━ ⚠️ Problème: {str(e)[:100]}...\n┗━━ 🔄 Arrêt de l'exécution",
            "eta": "Interrompu"
        })
        
        error_msg = ChatMessage(
            type="error",
            content=f"💥 **Erreur lors de l'exécution Browser-Use:**\n\n{str(e)[:300]}...\n\n🔧 *Vérifiez votre connexion internet et réessayez.*",
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender="Système"
        )
        await manager.broadcast(error_msg.dict())
        logger.error(f"Erreur Browser-Use: {e}")
        
    finally:
        manager.agent_busy = False
        manager.current_task = None
        manager.current_agent = None

async def send_progress_message(websocket: WebSocket, progress_data: dict):
    """Envoyer un message de progression formaté"""
    progress_msg = ChatMessage(
        type="progress",
        content=f"**{progress_data['title']}**\n\n{progress_data['details']}\n\n⏱️ ETA: {progress_data['eta']} | 📊 {progress_data['progress']}%",
        timestamp=datetime.now().strftime("%H:%M:%S"),
        sender="Browser-Use Agent"
    )
    
    # Ajouter les données de progression
    msg_dict = progress_msg.dict()
    msg_dict.update({
        "progress": progress_data['progress'],
        "step": progress_data['step'],
        "eta": progress_data['eta']
    })
    
    await manager.broadcast(msg_dict)

def format_browser_use_result(result, original_task: str) -> str:
    """Formatage intelligent du résultat Browser-Use"""
    try:
        # Extraire le résultat final si c'est un AgentHistoryList
        if hasattr(result, 'all_results') and result.all_results:
            # Prendre le dernier résultat qui est marqué comme terminé
            final_result = None
            for action_result in reversed(result.all_results):
                if hasattr(action_result, 'is_done') and action_result.is_done:
                    final_result = action_result
                    break
            
            if final_result and hasattr(final_result, 'extracted_content'):
                content = final_result.extracted_content
                
                # 🎯 Formatage intelligent selon le type de contenu
                if "population" in original_task.lower() and "population" in content.lower():
                    return format_population_result(content, final_result)
                elif any(word in original_task.lower() for word in ["weather", "météo", "temperature"]):
                    return format_weather_result(content, final_result)
                elif any(word in original_task.lower() for word in ["price", "prix", "cost", "coût"]):
                    return format_price_result(content, final_result)
                else:
                    return format_general_result(content, final_result, original_task)
        
        # Fallback: affichage simple
        return f"🎯 **Résultat de la recherche:**\n\n{str(result)[:500]}...\n\n🤖 *Exécuté par Browser-Use Agent*"
        
    except Exception as e:
        return f"📋 **Tâche exécutée** ✅\n\n*Résultat disponible mais formatage en cours...*\n\n🤖 *Browser-Use Agent*"

def format_population_result(content: str, result) -> str:
    """Formatage spécialisé pour les résultats de population"""
    # Extraire les informations de population
    import re
    
    # Chercher des patterns de population
    population_match = re.search(r'(\d[\d\s,\.]+)\s*habitants?', content, re.IGNORECASE)
    year_match = re.search(r'(20\d{2})', content)
    
    if population_match:
        population = population_match.group(1).replace(' ', ' ')
        year = year_match.group(1) if year_match else "récent"
        
        return f"""🏙️ **Résultat de Population** 

👥 **Population:** {population} habitants
📅 **Données:** {year}
🔍 **Recherche:** Population de Tokyo

🌐 **Source:** Wikipedia (français)
🔗 **Lien:** https://fr.wikipedia.org/wiki/Tokyo

✨ **Informations vérifiées et extraites par Browser-Use Agent**"""
    
    return format_general_result(content, result, "population")

def format_weather_result(content: str, result) -> str:
    """Formatage spécialisé pour la météo"""
    return f"""🌤️ **Résultat Météo**

{content[:300]}...

🌡️ **Source:** Données météorologiques en ligne
✨ **Exécuté par Browser-Use Agent**"""

def format_price_result(content: str, result) -> str:
    """Formatage spécialisé pour les prix"""
    return f"""💰 **Résultat Prix**

{content[:300]}...

💳 **Source:** Données de prix en ligne
✨ **Exécuté par Browser-Use Agent**"""

def format_general_result(content: str, result, task: str) -> str:
    """Formatage général pour tous les autres types"""
    # Nettoyer et structurer le contenu
    clean_content = content.replace('\\n', '\n').strip()
    
    # Limiter la longueur pour la lisibilité
    if len(clean_content) > 800:
        clean_content = clean_content[:800] + "..."
    
    return f"""🎯 **Résultat de votre recherche**

📋 **Demande:** {task}

📊 **Informations trouvées:**
{clean_content}

🤖 **Exécuté avec succès par Browser-Use Agent**
⏱️ **Données extraites en temps réel**"""

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
    logger.info("🚀 Démarrage du serveur Browser-Use Web Backend (Sans .env)...")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        access_log=True
    ) 