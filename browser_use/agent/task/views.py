from datetime import datetime, UTC
from typing import Literal
from pydantic import BaseModel, Field


class TaskVector(BaseModel):
    """Model for storing task vectors in Qdrant"""
    # Core task info
    task: str
    steps: list[str]
    actions: list[dict]
    tags: list[str] = Field(
        default_factory=list,
        description="Keywords and categories (e.g., ['search', 'youtube', 'form_fill', 'data_extraction'])"
    )
    difficulty: int
    final_result: str
    
    # Execution details
    execution_time: float = Field(0.0, description="Total execution time in seconds")
    step_count: int = Field(0, description="Number of steps taken")
    error_count: int = Field(0, description="Number of errors encountered")
    
    # System info
    llm_name: str | None = Field(None, description="Name of LLM used")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the task was executed"
    )

class TaskContext(BaseModel):
    """Context from similar successful tasks"""
    
    # Most similar task details
    most_similar_task: TaskVector | None = None
    similarity_score: float | None = None
    
    # Aggregate statistics
    n_similar_tasks: int = Field(
        0,
        description="Number of similar tasks found"
    )
    success_rate: float = Field(
        0.0,
        description="Ratio of successful steps to total steps"
    )
    
    # Common patterns
    common_patterns: dict[str, float] = Field(
        default_factory=dict,
        description="Mapping of steps to their frequency across similar tasks"
    )

class PlanAnalysis(BaseModel):
    """Structured output for task analysis"""
    task_summary: str = Field(description="Brief description of what needs to be done")
    tags: list[str] = Field(description="Relevant task categories")
    difficulty: int = Field(description="Task difficulty on 1-10 scale", ge=1, le=10)
    potential_challenges: list[str] = Field(description="Possible issues to handle")

class PlanExecution(BaseModel):
    """Structured output for execution plan"""
    steps: list[str] = Field(description="Steps to take")
    success_criteria: str = Field(description="How to know when task is complete")
    fallback_strategies: list[str] = Field(description="Alternative approaches if needed")

class Plan(BaseModel):
    """Structured output for task planning"""
    analysis: PlanAnalysis
    execution: PlanExecution

class TaskAnalysis(BaseModel):
    """Result from task planning - either a full plan or adapted actions"""
    type: Literal["plan", "actions"]
    content: Plan | list[dict]
    similarity_score: float | None = None
    original_task: str | None = None

class TaskMemoryConfig(BaseModel):
    """Configuration for task memory"""
    use_local_qdrant: bool = Field(
        default=False,
        description="Whether to use local Qdrant instance"
    )
    retry_on_hallucination: bool = Field(
        default=False,
        description="Whether to retry plan generation on detecting hallucinations"
    )
    local_qdrant_path: str | None = Field(
        default=None,
        description="Path to local Qdrant storage"
    )
    qdrant_url: str | None = Field(
        default=None,
        description="URL for remote Qdrant instance"
    )
    qdrant_api_key: str | None = Field(
        default=None,
        description="API key for remote Qdrant instance"
    )
    # Similarity thresholds
    adaptation_threshold: float = Field(
        default=0.92,
        description="Threshold for direct task adaptation",
        ge=0.0,
        le=1.0
    )
    context_threshold: float = Field(
        default=0.5,
        description="Threshold for finding similar tasks for context",
        ge=0.0,
        le=1.0
    )

