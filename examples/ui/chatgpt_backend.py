"""
FastAPI backend para interface ChatGPT-style do browser-use.

Fornece endpoints REST e WebSocket para:
- Criar e gerenciar sessões de agente
- Streaming de eventos em tempo real
- Controle de execução (pause/resume/stop)
- Upload de áudio para transcrição
"""

import asyncio
import base64
import logging
import os
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from browser_use import Agent
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext

from session_manager import SessionManager
from voice_services import VoiceServices

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializar FastAPI
app = FastAPI(title="Browser-Use ChatGPT API", version="1.0.0")

# CORS para permitir frontend React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],  # Next.js default ports
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gerenciador de sessões global
session_manager = SessionManager()

# Serviços de voz
voice_services = VoiceServices()


# ==================== Models ====================

class ChatRequest(BaseModel):
    """Requisição para criar nova tarefa de chat"""
    message: str
    session_id: Optional[str] = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    max_steps: int = 10


class ChatResponse(BaseModel):
    """Resposta ao criar chat"""
    session_id: str
    message: str
    status: str


class ControlRequest(BaseModel):
    """Requisição para controlar execução do agente"""
    action: str  # 'pause', 'resume', 'stop'


class SessionStatus(BaseModel):
    """Status da sessão"""
    session_id: str
    active: bool
    paused: bool
    stopped: bool
    current_step: int
    max_steps: int
    task: str


# ==================== Endpoints REST ====================

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Browser-Use ChatGPT API",
        "active_sessions": len(session_manager.sessions)
    }


@app.post("/api/chat", response_model=ChatResponse)
async def create_chat(request: ChatRequest):
    """
    Cria uma nova sessão de chat ou adiciona mensagem a sessão existente.
    
    Args:
        request: ChatRequest com mensagem e configurações
        
    Returns:
        ChatResponse com session_id e status
    """
    try:
        # Criar ou recuperar sessão
        if request.session_id and request.session_id in session_manager.sessions:
            session_id = request.session_id
            logger.info(f"Adicionando tarefa à sessão existente: {session_id}")
        else:
            session_id = str(uuid.uuid4())
            logger.info(f"Criando nova sessão: {session_id}")
        
        # Criar agente em background
        asyncio.create_task(
            session_manager.create_agent_session(
                session_id=session_id,
                task=request.message,
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
                max_steps=request.max_steps
            )
        )
        
        return ChatResponse(
            session_id=session_id,
            message="Agente iniciado com sucesso",
            status="running"
        )
        
    except Exception as e:
        logger.error(f"Erro ao criar chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session/{session_id}/status", response_model=SessionStatus)
async def get_session_status(session_id: str):
    """
    Obtém status atual da sessão.
    
    Args:
        session_id: ID da sessão
        
    Returns:
        SessionStatus com informações da sessão
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    
    agent = session.get("agent")
    
    return SessionStatus(
        session_id=session_id,
        active=session.get("active", False),
        paused=agent.state.paused if agent else False,
        stopped=agent.state.stopped if agent else False,
        current_step=agent.state.n_steps if agent else 0,
        max_steps=session.get("max_steps", 10),
        task=session.get("task", "")
    )


@app.post("/api/session/{session_id}/control")
async def control_session(session_id: str, request: ControlRequest):
    """
    Controla execução do agente (pause/resume/stop).
    
    Args:
        session_id: ID da sessão
        request: ControlRequest com ação desejada
        
    Returns:
        Status da operação
    """
    try:
        result = await session_manager.control_agent(session_id, request.action)
        return {"status": "success", "action": request.action, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Erro ao controlar sessão: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session/{session_id}/history")
async def get_session_history(session_id: str):
    """
    Obtém histórico completo da sessão.
    
    Args:
        session_id: ID da sessão
        
    Returns:
        Lista de eventos/mensagens da sessão
    """
    history = session_manager.get_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    
    return {"session_id": session_id, "history": history}


@app.get("/api/session/{session_id}/screenshot/{step}")
async def get_screenshot(session_id: str, step: int):
    """
    Obtém screenshot de um step específico.
    
    Args:
        session_id: ID da sessão
        step: Número do step
        
    Returns:
        Imagem PNG do screenshot
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    
    # Buscar screenshot no diretório da sessão
    screenshot_dir = session.get("screenshot_dir")
    if not screenshot_dir:
        raise HTTPException(status_code=404, detail="Diretório de screenshots não encontrado")
    
    screenshot_path = Path(screenshot_dir) / f"step_{step}.png"
    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Screenshot não encontrado")
    
    return FileResponse(screenshot_path, media_type="image/png")


@app.post("/api/voice/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Transcreve áudio para texto usando Whisper API.
    
    Args:
        file: Arquivo de áudio (mp3, wav, webm, etc)
        
    Returns:
        Texto transcrito
    """
    try:
        # Ler conteúdo do arquivo
        audio_bytes = await file.read()
        
        # Transcrever usando Whisper
        text = await voice_services.transcribe_audio(audio_bytes, filename=file.filename)
        
        return {"text": text, "status": "success"}
        
    except Exception as e:
        logger.error(f"Erro ao transcrever áudio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/voice/synthesize")
async def synthesize_speech(request: dict):
    """
    Converte texto em fala usando TTS API.
    
    Args:
        request: Dict com 'text' a ser sintetizado
        
    Returns:
        Áudio base64 encoded
    """
    try:
        text = request.get("text")
        if not text:
            raise HTTPException(status_code=400, detail="Texto não fornecido")
        
        # Sintetizar usando TTS
        audio_bytes = await voice_services.synthesize_speech(text)
        
        # Converter para base64
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        return {"audio": audio_b64, "format": "mp3", "status": "success"}
        
    except Exception as e:
        logger.error(f"Erro ao sintetizar fala: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== WebSocket ====================

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket para streaming de eventos em tempo real.
    
    Envia eventos:
    - step_start: Início de um novo step
    - step_end: Fim de um step com screenshot
    - action: Ação executada pelo agente
    - thought: Pensamento do modelo
    - error: Erro ocorrido
    - done: Tarefa concluída
    
    Args:
        websocket: Conexão WebSocket
        session_id: ID da sessão para conectar
    """
    await websocket.accept()
    logger.info(f"WebSocket conectado para sessão: {session_id}")
    
    try:
        # Registrar WebSocket na sessão
        await session_manager.register_websocket(session_id, websocket)
        
        # Enviar mensagem de confirmação
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "WebSocket conectado com sucesso"
        })
        
        # Manter conexão aberta e processar mensagens do cliente
        while True:
            try:
                # Receber mensagens do cliente (ex: comandos de controle)
                data = await websocket.receive_json()
                
                # Processar comandos
                if data.get("type") == "control":
                    action = data.get("action")
                    await session_manager.control_agent(session_id, action)
                    await websocket.send_json({
                        "type": "control_response",
                        "action": action,
                        "status": "success"
                    })
                    
            except WebSocketDisconnect:
                logger.info(f"WebSocket desconectado: {session_id}")
                break
            except Exception as e:
                logger.error(f"Erro no WebSocket: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
                
    except Exception as e:
        logger.error(f"Erro fatal no WebSocket: {e}")
    finally:
        # Remover WebSocket da sessão
        await session_manager.unregister_websocket(session_id, websocket)


# ==================== Startup/Shutdown ====================

@app.on_event("startup")
async def startup_event():
    """Inicialização da aplicação"""
    logger.info("🚀 Browser-Use ChatGPT API iniciada")
    logger.info("📡 WebSocket endpoint: ws://localhost:8000/ws/{session_id}")
    logger.info("🌐 REST API: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event():
    """Limpeza ao encerrar aplicação"""
    logger.info("🛑 Encerrando Browser-Use ChatGPT API...")
    await session_manager.cleanup_all_sessions()


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "chatgpt_backend:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
