from sqlalchemy.orm import Session
from typing import List, Optional
from models import Task, BrowserSession
from schemas import TaskCreate, TaskUpdate, BrowserSessionCreate

async def create_task(db: Session, task: TaskCreate) -> Task:
    db_task = Task(
        task=task.task,
        config=task.config,
        status="pending",
        priority=task.priority,
        max_retries=task.max_retries,
        timeout=task.timeout,
        tags=task.tags,
        metadata=task.metadata
    )
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task

async def get_tasks(db: Session, skip: int = 0, limit: int = 100) -> List[Task]:
    return db.query(Task).order_by(Task.created_at.desc()).offset(skip).limit(limit).all()

async def get_task(db: Session, task_id: int) -> Optional[Task]:
    return db.query(Task).filter(Task.id == task_id).first()

async def update_task(db: Session, task_id: int, task: TaskUpdate) -> Task:
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        return None
        
    for key, value in task.dict(exclude_unset=True).items():
        setattr(db_task, key, value)
        
    await db.commit()
    await db.refresh(db_task)
    return db_task

async def delete_task(db: Session, task_id: int) -> bool:
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        return False
        
    db.delete(db_task)
    await db.commit()
    return True

async def create_browser_session(db: Session, session: BrowserSessionCreate) -> BrowserSession:
    db_session = BrowserSession(
        task_id=session.task_id,
        status="active",
        config=session.config,
        metadata=session.metadata
    )
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)
    return db_session

async def get_browser_sessions(db: Session, skip: int = 0, limit: int = 100) -> List[BrowserSession]:
    return db.query(BrowserSession).order_by(BrowserSession.created_at.desc()).offset(skip).limit(limit).all()

async def get_browser_session(db: Session, session_id: int) -> Optional[BrowserSession]:
    return db.query(BrowserSession).filter(BrowserSession.id == session_id).first()

async def get_browser_sessions_by_task(db: Session, task_id: int) -> List[BrowserSession]:
    return db.query(BrowserSession).filter(BrowserSession.task_id == task_id).all() 