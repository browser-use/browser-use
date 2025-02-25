import logging
from qdrant_client.http import models
from browser_use.agent.vector_db import VectorDB
from browser_use.agent.task.views import TaskVector
import uuid

logger = logging.getLogger(__name__)

class TaskStore:
    """Store for task vectors and similarity search"""

    def __init__(self, vector_db: VectorDB):
        self.vector_db = vector_db

    async def store_task(self, task_vector: TaskVector) -> None:
        """Store a task execution"""
        task_embedding = self.vector_db.encode_text(task_vector.task)
        execution_id = str(uuid.uuid4())
        
        self.vector_db.client.upsert(
            collection_name=self.vector_db.collection_name,
            points=[
                models.PointStruct(
                    id=execution_id,
                    vector=task_embedding,
                    payload=task_vector.model_dump()
                )
            ]
        )

    async def search_similar_tasks(self, task: str, limit: int = 5, context_threshold: float = 0.5) -> list[tuple[TaskVector, float]] | None:
        """Search for similar tasks and return with similarity scores"""
        try:
            task_embedding = self.vector_db.encode_text(task)
            search_result = self.vector_db.client.search(
                collection_name=self.vector_db.collection_name,
                query_vector=task_embedding,
                limit=limit,
                score_threshold=context_threshold
            )
            
            if not search_result:
                logger.info("No similar tasks found in db")
                return None

            similar_tasks = []
            for hit in search_result:
                try:
                    if not hit.payload:
                        continue
                    
                    task_vector = TaskVector(
                        task=str(hit.payload.get("task", "")),
                        steps=list(hit.payload.get("steps", [])),
                        actions=list(hit.payload.get("actions", [])),
                        tags=list(hit.payload.get("tags", [])),
                        difficulty=int(hit.payload.get("difficulty", 1)),
                        final_result=str(hit.payload.get("final_result", "")),
                        execution_time=float(hit.payload.get("execution_time", 0.0)),
                        step_count=int(hit.payload.get("step_count", 0)),
                        error_count=int(hit.payload.get("error_count", 0)),
                        llm_name=str(hit.payload.get("llm_name", ""))
                    )
                    similar_tasks.append((task_vector, hit.score))
                except Exception as e:
                    logger.warning(f"Failed to parse task vector: {e}")
                    continue

            return similar_tasks if similar_tasks else None

        except Exception as e:
            logger.warning(f"Error searching vector database: {e}")
            return None

    @classmethod
    def create(
        cls,
        use_local: bool = False,
        local_path: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
    ) -> 'TaskStore | None':
        """Create a TaskStore instance with vector DB"""
        vector_db = VectorDB.get_instance(
            collection_name="successful_tasks",
            use_local=use_local,
            local_path=local_path,
            url=url,
            api_key=api_key
        )
        
        if vector_db is None:
            return None
            
        return cls(vector_db=vector_db) 