from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import json
import time
import psutil
from datetime import datetime, timedelta
import asyncio
from queue import PriorityQueue
import threading
import logging
import uvicorn
from logging_config import setup_logging, log_info, log_error, log_debug, log_warning

from config import settings
from database import get_db
from models import Task, Metric, Base, BrowserSession
from browser import BrowserManager
from schemas import TaskCreate, TaskResponse, TaskUpdate, BrowserSessionCreate, BrowserSessionResponse
from crud import (
    create_task, get_tasks, get_task, update_task, delete_task,
    create_browser_session, get_browser_sessions, get_browser_session,
    get_browser_sessions_by_task
)
from notifications import webhook_manager
from api import collect_metrics_periodically, router as api_router

# Configuração de logging
logger = logging.getLogger('browser-use.main')

app = FastAPI(
    title="Browser Automation API",
    description="API para automação de navegador com gerenciamento de sessões",
    version="1.0.0"
)

# Configuração CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir router da API
app.include_router(api_router)

# Inicialização do banco de dados
Base.metadata.create_all(bind=settings.engine)

# Instância global do BrowserManager
browser_manager = BrowserManager()

# Fila de prioridade para tarefas
task_queue = PriorityQueue()
task_lock = threading.Lock()

# Tarefas em execução
active_tasks = {}

async def process_task_queue():
    """Processa a fila de tarefas em ordem de prioridade"""
    while True:
        try:
            with task_lock:
                if not task_queue.empty():
                    priority, task_id = task_queue.get()
                    task = await get_task_from_db(task_id)
                    
                    if task and task.status == "pending":
                        await execute_task(task)
                        
        except Exception as e:
            log_error(logger, "Erro ao processar fila de tarefas", {
                "error": str(e)
            }, exc_info=True)
            
        await asyncio.sleep(1)

async def get_task_from_db(task_id: int) -> Optional[Task]:
    """Obtém uma tarefa do banco de dados"""
    async with get_db() as db:
        return await db.query(Task).filter(Task.id == task_id).first()

async def execute_task(task: Task):
    """Executa uma tarefa"""
    try:
        # Atualiza status para running
        async with get_db() as db:
            task.status = "running"
            task.started_at = datetime.utcnow()
            await db.commit()
        
        # Notifica início da execução
        await webhook_manager.notify_run(
            task_id=task.id,
            task_data={
                "task": task.task,
                "config": task.config,
                "priority": task.priority
            }
        )
        
        # Executa a tarefa com timeout
        try:
            result = await asyncio.wait_for(
                browser_manager.execute_task(task.task, task.config or {}),
                timeout=task.timeout
            )
            
            # Atualiza resultado
            async with get_db() as db:
                task.status = "completed"
                task.result = json.dumps(result)
                task.completed_at = datetime.utcnow()
                await db.commit()
                
        except asyncio.TimeoutError:
            error_msg = "Task timeout"
            async with get_db() as db:
                task.status = "failed"
                task.error = error_msg
                task.completed_at = datetime.utcnow()
                await db.commit()
            
            # Notifica erro
            await webhook_manager.notify_error(
                task_id=task.id,
                error=error_msg,
                task_data={
                    "task": task.task,
                    "config": task.config,
                    "priority": task.priority
                }
            )
            
    except Exception as e:
        log_error(logger, "Erro ao executar tarefa", {
            "task_id": task.id,
            "error": str(e)
        }, exc_info=True)
        async with get_db() as db:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = datetime.utcnow()
            await db.commit()
            
        # Notifica erro
        await webhook_manager.notify_error(
            task_id=task.id,
            error=str(e),
            task_data={
                "task": task.task,
                "config": task.config,
                "priority": task.priority
            }
        )

async def collect_metrics():
    """Coleta e envia métricas periodicamente"""
    while True:
        try:
            # Coleta métricas do sistema
            metrics = {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage('/').percent,
                "active_tasks": len(active_tasks),
                "browser_metrics": browser_manager.get_metrics()
            }
            
            # Envia métricas via webhook
            await webhook_manager.send_status(metrics)
            
        except Exception as e:
            log_error(logger, "Erro ao coletar métricas", {
                "error": str(e)
            }, exc_info=True)
            
        await asyncio.sleep(3600)  # Coleta a cada hora

@app.on_event("startup")
async def startup_event():
    """Inicializa o gerenciador de navegador na inicialização da aplicação"""
    try:
        await browser_manager.initialize()
        log_info(logger, "BrowserManager inicializado com sucesso")
    except Exception as e:
        log_error(logger, "Erro ao inicializar BrowserManager", {
            "error": str(e)
        }, exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Fecha o gerenciador de navegador no encerramento da aplicação"""
    try:
        await browser_manager.close()
        log_info(logger, "BrowserManager encerrado com sucesso")
    except Exception as e:
        log_error(logger, "Erro ao encerrar BrowserManager", {
            "error": str(e)
        }, exc_info=True)

@app.post("/run")
async def run_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Executa uma nova tarefa de automação"""
    try:
        # Cria a tarefa no banco de dados
        db_task = await create_task(db, task)
        log_info(logger, "Tarefa criada com sucesso", {
            "task_id": db_task.id
        })
        
        # Executa a tarefa usando o pool de sessões
        result = await browser_manager.execute_task(task.task, task.config)
        log_info(logger, "Tarefa executada com sucesso", {
            "task_id": db_task.id
        })
        
        # Atualiza o status e resultado da tarefa
        db_task.status = "completed"
        db_task.result = str(result)
        db_task.completed_at = datetime.utcnow()
        await db.commit()
        
        return TaskResponse(
            id=db_task.id,
            status=db_task.status,
            priority=db_task.priority,
            result=db_task.result,
            error=db_task.error,
            created_at=db_task.created_at,
            completed_at=db_task.completed_at
        )
    except Exception as e:
        log_error(logger, "Erro ao executar tarefa", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_metrics():
    """Retorna métricas do sistema e do navegador"""
    try:
        return await browser_manager.get_metrics()
    except Exception as e:
        log_error(logger, "Erro ao obter métricas", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Lista todas as tarefas com paginação"""
    try:
        tasks = await get_tasks(db, skip=skip, limit=limit)
        return [
            TaskResponse(
                id=task.id,
                status=task.status,
                priority=task.priority,
                result=task.result,
                error=task.error,
                created_at=task.created_at,
                completed_at=task.completed_at
            )
            for task in tasks
        ]
    except Exception as e:
        log_error(logger, "Erro ao listar tarefas", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_by_id(task_id: int, db: Session = Depends(get_db)):
    """Obtém detalhes de uma tarefa específica"""
    try:
        task = await get_task(db, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskResponse(
            id=task.id,
            status=task.status,
            priority=task.priority,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            completed_at=task.completed_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Erro ao obter tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks", response_model=TaskResponse)
async def create_new_task(task: TaskCreate, db: Session = Depends(get_db)):
    """Cria uma nova tarefa"""
    try:
        db_task = await create_task(db, task)
        log_info(logger, "Tarefa criada com sucesso", {
            "task_id": db_task.id
        })
        return TaskResponse(
            id=db_task.id,
            status=db_task.status,
            priority=db_task.priority,
            result=db_task.result,
            error=db_task.error,
            created_at=db_task.created_at,
            completed_at=db_task.completed_at
        )
    except Exception as e:
        log_error(logger, "Erro ao criar tarefa", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_existing_task(task_id: int, task: TaskUpdate, db: Session = Depends(get_db)):
    """Atualiza uma tarefa existente"""
    try:
        db_task = await update_task(db, task_id, task)
        if not db_task:
            raise HTTPException(status_code=404, detail="Task not found")
        log_info(logger, "Tarefa atualizada com sucesso", {
            "task_id": task_id
        })
        return TaskResponse(
            id=db_task.id,
            status=db_task.status,
            priority=db_task.priority,
            result=db_task.result,
            error=db_task.error,
            created_at=db_task.created_at,
            completed_at=db_task.completed_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Erro ao atualizar tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/tasks/{task_id}")
async def delete_existing_task(task_id: int, db: Session = Depends(get_db)):
    """Remove uma tarefa"""
    try:
        success = await delete_task(db, task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        log_info(logger, "Tarefa removida com sucesso", {
            "task_id": task_id
        })
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Erro ao deletar tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser-sessions", response_model=List[BrowserSessionResponse])
async def list_browser_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Lista todas as sessões do navegador com paginação"""
    try:
        sessions = await get_browser_sessions(db, skip=skip, limit=limit)
        return [
            BrowserSessionResponse(
                id=session.id,
                task_id=session.task_id,
                status=session.status,
                config=session.config,
                metadata=session.metadata,
                created_at=session.created_at,
                updated_at=session.updated_at
            )
            for session in sessions
        ]
    except Exception as e:
        log_error(logger, "Erro ao listar sessões", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser-sessions/{session_id}", response_model=BrowserSessionResponse)
async def get_browser_session_by_id(session_id: int, db: Session = Depends(get_db)):
    """Obtém detalhes de uma sessão específica"""
    try:
        session = await get_browser_session(db, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Browser session not found")
        return BrowserSessionResponse(
            id=session.id,
            task_id=session.task_id,
            status=session.status,
            config=session.config,
            metadata=session.metadata,
            created_at=session.created_at,
            updated_at=session.updated_at
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(logger, "Erro ao obter sessão", {
            "session_id": session_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}/browser-sessions", response_model=List[BrowserSessionResponse])
async def get_task_browser_sessions(task_id: int, db: Session = Depends(get_db)):
    """Lista todas as sessões associadas a uma tarefa"""
    try:
        sessions = await get_browser_sessions_by_task(db, task_id)
        return [
            BrowserSessionResponse(
                id=session.id,
                task_id=session.task_id,
                status=session.status,
                config=session.config,
                metadata=session.metadata,
                created_at=session.created_at,
                updated_at=session.updated_at
            )
            for session in sessions
        ]
    except Exception as e:
        log_error(logger, "Erro ao obter sessões da tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Tratamento global de exceções"""
    log_error(logger, "Erro não tratado", {
        "error": str(exc)
    }, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

@app.get("/health")
async def health_check():
    """Endpoint de verificação de saúde da aplicação"""
    return {"status": "healthy"}

@app.get("/tasks/", response_model=List[TaskResponse])
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    tasks = await get_tasks(db, skip=skip, limit=limit)
    return [
        TaskResponse(
            id=task.id,
            status=task.status,
            priority=task.priority,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            completed_at=task.completed_at
        )
        for task in tasks
    ]

@app.get("/metrics/errors")
async def get_error_metrics(db: Session = Depends(get_db)):
    """Retorna métricas de erros"""
    try:
        last_hour = datetime.utcnow() - timedelta(hours=1)
        error_tasks = db.query(Task).filter(
            Task.status == "failed",
            Task.created_at >= last_hour
        ).all()
        
        return {
            "total_errors": len(error_tasks),
            "errors": [
                {
                    "task_id": task.id,
                    "error": task.error,
                    "timestamp": task.created_at.isoformat()
                } for task in error_tasks
            ]
        }
    except Exception as e:
        log_error(logger, "Erro ao obter métricas de erros", {
            "error": str(e)
        }, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def main():
    """Função principal que inicia o servidor e o coletor de métricas"""
    try:
        log_info(logger, "Iniciando aplicação")
        
        # Inicia o coletor de métricas em background
        log_info(logger, "Iniciando coletor de métricas")
        asyncio.create_task(collect_metrics_periodically())
        
        # Inicia o servidor FastAPI
        log_info(logger, "Iniciando servidor FastAPI")
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
        
    except Exception as e:
        log_error(logger, "Erro ao iniciar aplicação", {
            "error": str(e)
        }, exc_info=True)
        raise

if __name__ == "__main__":
    # Configura o logging
    setup_logging()
    
    # Executa a aplicação
    asyncio.run(main()) 