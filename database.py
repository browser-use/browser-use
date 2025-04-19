from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Float, TypeDecorator
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
from dotenv import load_dotenv
import logging
from logging_config import setup_logging, log_info, log_error, log_debug
from datetime import datetime
from sqlalchemy.sql import select
from contextlib import contextmanager
import json

# Configuração de logging
logger = logging.getLogger('browser-use.database')

load_dotenv()

# Configuração do banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./browser_use.db")

log_info(logger, "Inicializando conexão com o banco de dados", {
    "database_url": DATABASE_URL,
    "type": "SQLite"
})

# Configuração do banco de dados
engine = create_engine(
    DATABASE_URL
    # connect_args={"check_same_thread": False}  # Necessário para SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Classes para converter JSON para string e vice-versa (necessário para SQLite)
class JSONEncodedDict(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return None

# Modelos
class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task = Column(String, nullable=False)
    config = Column(JSONEncodedDict, nullable=True)  # Usando JSONEncodedDict
    status = Column(String, nullable=False)
    result = Column(JSONEncodedDict, nullable=True)  # Usando JSONEncodedDict
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False)

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)

# Função para obter sessão do banco de dados
@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()

# Função para inicializar o banco
def init_db():
    log_info(logger, "Inicializando banco de dados")
    try:
        Base.metadata.create_all(bind=engine)
        log_info(logger, "Tabelas do banco de dados criadas com sucesso")
    except Exception as e:
        log_error(logger, "Erro ao inicializar banco de dados", {
            "error": str(e)
        }, exc_info=True)
        raise

# Funções CRUD para Task (versão síncrona)
def create_task(db: Session, task_data: dict) -> Task:
    try:
        task = Task(
            task=task_data["task"],
            config=task_data.get("config"),
            status="pending",
            created_at=datetime.utcnow()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    except Exception as e:
        log_error(logger, "Erro ao criar tarefa", {
            "error": str(e)
        }, exc_info=True)
        raise

def get_task(db: Session, task_id: int) -> Task:
    try:
        return db.query(Task).filter(Task.id == task_id).first()
    except Exception as e:
        log_error(logger, "Erro ao obter tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

def update_task(db: Session, task_id: int, task_data: dict) -> Task:
    try:
        task = get_task(db, task_id)
        if task:
            for key, value in task_data.items():
                setattr(task, key, value)
            db.commit()
            db.refresh(task)
        return task
    except Exception as e:
        log_error(logger, "Erro ao atualizar tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> list[Task]:
    try:
        return db.query(Task).offset(skip).limit(limit).all()
    except Exception as e:
        log_error(logger, "Erro ao listar tarefas", {
            "error": str(e)
        }, exc_info=True)
        raise

# Funções para Session
def get_sessions(db: Session, skip: int = 0, limit: int = 100) -> list[Session]:
    """Lista todas as sessões com paginação"""
    try:
        result = db.query(Session).offset(skip).limit(limit).all()
        return result
    except Exception as e:
        log_error(logger, "Erro ao listar sessões", {
            "error": str(e)
        }, exc_info=True)
        raise

def get_session(db: Session, session_id: int) -> Session:
    """Obtém uma sessão pelo ID"""
    try:
        return db.query(Session).filter(Session.id == session_id).first()
    except Exception as e:
        log_error(logger, "Erro ao obter sessão", {
            "session_id": session_id,
            "error": str(e)
        }, exc_info=True)
        raise

def get_task_sessions(db: Session, task_id: int) -> list[Session]:
    """Obtém todas as sessões de uma tarefa"""
    try:
        result = db.query(Session).filter(Session.task_id == task_id).all()
        return result
    except Exception as e:
        log_error(logger, "Erro ao obter sessões da tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise

def delete_task(db: Session, task_id: int) -> bool:
    """Remove uma tarefa do banco de dados"""
    try:
        task = get_task(db, task_id)
        if task:
            db.delete(task)
            db.commit()
            return True
        return False
    except Exception as e:
        log_error(logger, "Erro ao deletar tarefa", {
            "task_id": task_id,
            "error": str(e)
        }, exc_info=True)
        raise 