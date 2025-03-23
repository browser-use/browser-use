from __future__ import annotations

import enum
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from browser_use.agent.views import AgentOutput


class CacheStrategy(str, enum.Enum):
    """Strategy for caching"""
    DISABLED = "disabled"  # No caching
    EXACT_MATCH = "exact_match"  # Only use cache if exact match
    SIMILAR_STATE = "similar_state"  # Use cache if state is similar
    READ_WRITE = "read_write"  # Read from and write to cache
    READ_ONLY = "read_only"  # Only read from cache
    WRITE_ONLY = "write_only"  # Only write to cache


class CacheSettings(BaseModel):
    """Settings for the caching system"""
    enabled: bool = False
    strategy: CacheStrategy = CacheStrategy.EXACT_MATCH
    ttl_seconds: int = 3600  # 1 hour by default
    max_entries: int = 1000
    similarity_threshold: float = 0.9  # For similar state strategy
    cache_llm_responses: bool = True
    cache_agent_runs: bool = True
    cache_agent_history: bool = True
    cache_ttl: int = 3600  # 1 hour by default
    cache_id: Optional[str] = None


@dataclass
class CacheEntry:
    """Entry in the cache"""
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self, ttl_seconds: Optional[int] = None) -> bool:
        """Check if the cache entry is expired"""
        if self.expires_at is None:
            if ttl_seconds is None:
                return False
            return (datetime.now() - self.created_at).total_seconds() > ttl_seconds
        return datetime.now() > self.expires_at


class CacheStats:
    """Statistics for the cache"""
    hits: int = 0
    misses: int = 0
    
    @property
    def total(self) -> int:
        return self.hits + self.misses
    
    @property
    def hit_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.hits / self.total


class CacheKey(BaseModel):
    """Key for the cache"""
    task: str
    url: Optional[str] = None
    title: Optional[str] = None
    dom_state_hash: Optional[str] = None
    step: Optional[int] = None
    
    def to_string(self) -> str:
        """Convert the key to a string"""
        return json.dumps({
            "task": self.task,
            "url": self.url,
            "title": self.title,
            "dom_state_hash": self.dom_state_hash,
            "step": self.step
        }, sort_keys=True)
    
    def to_hash(self) -> str:
        """Convert the key to a hash"""
        return hashlib.sha256(self.to_string().encode()).hexdigest()


class CachedLLMResponse(BaseModel):
    """Cached LLM response"""
    input_hash: str
    output: AgentOutput
    timestamp: float


class CachedAgentRun(BaseModel):
    """Cached agent run"""
    task_hash: str
    history: Dict[str, Any]  # Serialized AgentHistoryList
    timestamp: float


@dataclass
class MessageHash:
    """Hash of a message for caching"""
    content_hash: str
    role: str
    
    @classmethod
    def from_message(cls, message: BaseMessage) -> MessageHash:
        """Create a hash from a message"""
        from hashlib import sha256
        
        # Handle different content types
        if isinstance(message.content, str):
            content_hash = sha256(message.content.encode()).hexdigest()
        elif isinstance(message.content, list):
            # For multimodal content, hash each part
            content_str = str(message.content)
            content_hash = sha256(content_str.encode()).hexdigest()
        else:
            content_hash = sha256(str(message.content).encode()).hexdigest()
            
        return cls(
            content_hash=content_hash,
            role=message.type,
        )
    
    def __str__(self) -> str:
        return f"{self.role}:{self.content_hash}" 