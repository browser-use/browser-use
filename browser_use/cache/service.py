"""
Caching service for browser_use to speed up repeated agent runs.
"""

import hashlib
import json
import logging
import os
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.messages import BaseMessage

from browser_use.agent.views import AgentHistoryList, AgentOutput, ActionResult, AgentHistory
from browser_use.browser.views import BrowserState
from browser_use.cache.views import (
    CacheSettings,
    CacheStrategy,
    CachedAgentRun,
    CachedLLMResponse,
    MessageHash,
    CacheKey,
    CacheStats,
    CacheEntry,
)
from browser_use.utils import singleton, time_execution_sync

logger = logging.getLogger(__name__)


@singleton
class CacheService:
    """Service for caching agent runs and LLM responses."""
    
    def __init__(self, cache_dir=None):
        self.cache: Dict[str, CacheEntry] = {}
        self.stats = CacheStats()
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / '.cache' / 'browser_use' / 'llm_cache'
        self.settings = CacheSettings()  # Add default settings
        self._ensure_cache_dir()
        
    def _ensure_cache_dir(self) -> None:
        """Ensure the cache directory exists"""
        if not self._cache_dir.exists():
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories for different cache types
        os.makedirs(self._cache_dir / "llm_responses", exist_ok=True)
        os.makedirs(self._cache_dir / "agent_runs", exist_ok=True)
        
        logger.debug(f"Cache directory set up at {self._cache_dir}")
    
    def _compute_hash(self, data: Any) -> str:
        """Compute a hash for the given data."""
        if isinstance(data, list) and all(isinstance(item, BaseMessage) for item in data):
            # For message lists, hash the content and type of each message
            serialized = json.dumps([
                {"type": msg.__class__.__name__, "content": msg.content}
                for msg in data
            ], sort_keys=True)
            return hashlib.sha256(serialized.encode()).hexdigest()
        elif isinstance(data, dict):
            # For dictionaries, sort keys for consistent hashing
            serialized = json.dumps(data, sort_keys=True)
            return hashlib.sha256(serialized.encode()).hexdigest()
        elif isinstance(data, str):
            serialized = data
            return hashlib.sha256(serialized.encode()).hexdigest()
        else:
            # For other types, use pickle for serialization
            try:
                serialized = pickle.dumps(data)
                # No need to encode since pickle.dumps already returns bytes
                return hashlib.sha256(serialized).hexdigest()
            except:
                # If pickling fails, use string representation
                serialized = str(data)
                return hashlib.sha256(serialized.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str, cache_type: str = 'llm') -> Path:
        """Get the path for a cache file."""
        cache_dir = self._cache_dir if cache_type == 'llm' else self._cache_dir
        return cache_dir / f"{cache_key}.pickle"
    
    def _save_to_file(self, cache_key: str, entry: CacheEntry, cache_type: str = 'llm') -> None:
        """Save a cache entry to a file."""
        cache_path = self._get_cache_path(cache_key, cache_type)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(entry, f)
            logger.debug(f"Saved cache entry to {cache_path}")
        except Exception as e:
            logger.warning(f"Failed to save cache entry to {cache_path}: {e}")
    
    def _load_from_file(self, cache_key: str, cache_type: str = 'llm') -> Optional[CacheEntry]:
        """Load a cache entry from a file."""
        cache_path = self._get_cache_path(cache_key, cache_type)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                entry = pickle.load(f)
            
            # Check if the entry is expired
            if entry.is_expired:
                logger.debug(f"Cache entry {cache_path} is expired")
                cache_path.unlink(missing_ok=True)
                return None
            
            logger.debug(f"Loaded cache entry from {cache_path}")
            return entry
        except Exception as e:
            logger.warning(f"Failed to load cache entry from {cache_path}: {e}")
            return None
    
    def get_cached_llm_response(self, messages: List[BaseMessage]) -> Optional[AgentOutput]:
        """Get a cached LLM response for the given messages
        
        Args:
            messages: The messages to get a cached response for
            
        Returns:
            The cached response, or None if not found
        """
        if not self._should_read_cache() or not self.settings.cache_llm_responses:
            return None
            
        input_hash = self._hash_messages(messages)
        cache_path = self._get_llm_cache_path(input_hash)
        
        if not os.path.exists(cache_path):
            return None
            
        try:
            with open(cache_path, "r") as f:
                cached_data = json.load(f)
                
            cached_response = CachedLLMResponse.model_validate(cached_data)
            
            # Check if cache is expired
            if time.time() - cached_response.timestamp > self.settings.cache_ttl:
                logger.debug(f"Cache expired for hash {input_hash}")
                return None
                
            logger.info(f"Cache hit for LLM response with hash {input_hash}")
            return cached_response.output
            
        except Exception as e:
            logger.warning(f"Failed to read cached LLM response: {e}")
            return None
            
    def cache_llm_response(self, messages: List[BaseMessage], output: AgentOutput) -> None:
        """Cache an LLM response
        
        Args:
            messages: The input messages
            output: The output from the LLM
        """
        if not self._should_write_cache() or not self.settings.cache_llm_responses:
            return
            
        input_hash = self._hash_messages(messages)
        cache_path = self._get_llm_cache_path(input_hash)
        
        try:
            cached_response = CachedLLMResponse(
                input_hash=input_hash,
                output=output,
                timestamp=time.time(),
            )
            
            with open(cache_path, "w") as f:
                f.write(cached_response.model_dump_json())
                
            logger.debug(f"Cached LLM response with hash {input_hash}")
            
        except Exception as e:
            logger.warning(f"Failed to cache LLM response: {e}")
            
    def get_cached_agent_run(self, task: str) -> Optional[Dict[str, Any]]:
        """Get a cached agent run for the given task
        
        Args:
            task: The task to get a cached run for
            
        Returns:
            The cached agent history, or None if not found
        """
        if not self._should_read_cache() or not self.settings.cache_agent_runs:
            return None
            
        task_hash = self._hash_task(task)
        cache_path = self._get_agent_cache_path(task_hash)
        
        if not os.path.exists(cache_path):
            return None
            
        try:
            with open(cache_path, "r") as f:
                cached_data = json.load(f)
                
            cached_run = CachedAgentRun.model_validate(cached_data)
            
            # Check if cache is expired
            if time.time() - cached_run.timestamp > self.settings.cache_ttl:
                logger.debug(f"Cache expired for task hash {task_hash}")
                return None
                
            logger.info(f"Cache hit for agent run with task hash {task_hash}")
            return cached_run.history
            
        except Exception as e:
            logger.warning(f"Failed to read cached agent run: {e}")
            return None
            
    def cache_agent_run(self, task: str, history: AgentHistoryList) -> None:
        """Cache an agent run
        
        Args:
            task: The task
            history: The agent history
        """
        if not self._should_write_cache() or not self.settings.cache_agent_runs:
            return
            
        task_hash = self._hash_task(task)
        cache_path = self._get_agent_cache_path(task_hash)
        
        try:
            # Convert history to dict
            history_dict = history.to_dict()
            
            cached_run = CachedAgentRun(
                task_hash=task_hash,
                history=history_dict,
                timestamp=time.time(),
            )
            
            with open(cache_path, "w") as f:
                f.write(cached_run.model_dump_json())
                
            logger.debug(f"Cached agent run with task hash {task_hash}")
            
        except Exception as e:
            logger.warning(f"Failed to cache agent run: {e}")
            
    def _hash_messages(self, messages: List[BaseMessage]) -> str:
        """Hash a list of messages for caching
        
        Args:
            messages: The messages to hash
            
        Returns:
            A hash of the messages
        """
        # Create message hashes
        message_hashes = [str(MessageHash.from_message(msg)) for msg in messages]
        
        # Join and hash
        combined = "|".join(message_hashes)
        return hashlib.sha256(combined.encode()).hexdigest()
        
    def _hash_task(self, task: str) -> str:
        """Hash a task for caching
        
        Args:
            task: The task to hash
            
        Returns:
            A hash of the task
        """
        if self.settings.cache_id:
            # Use provided cache ID if available
            return self.settings.cache_id
            
        return hashlib.sha256(task.encode()).hexdigest()
        
    def _get_llm_cache_path(self, input_hash: str) -> str:
        """Get the path to a cached LLM response
        
        Args:
            input_hash: The hash of the input messages
            
        Returns:
            The path to the cached response
        """
        return os.path.join(self._cache_dir, "llm_responses", f"{input_hash}.json")
        
    def _get_agent_cache_path(self, task_hash: str) -> str:
        """Get the path to a cached agent run
        
        Args:
            task_hash: The hash of the task
            
        Returns:
            The path to the cached run
        """
        return os.path.join(self._cache_dir, "agent_runs", f"{task_hash}.json")
        
    def _should_read_cache(self) -> bool:
        """Check if we should read from cache
        
        Returns:
            True if we should read from cache, False otherwise
        """
        return self.settings.strategy in [CacheStrategy.READ_ONLY, CacheStrategy.READ_WRITE]
        
    def _should_write_cache(self) -> bool:
        """Check if we should write to cache
        
        Returns:
            True if we should write to cache, False otherwise
        """
        return self.settings.strategy in [CacheStrategy.WRITE_ONLY, CacheStrategy.READ_WRITE]
        
    def clear_cache(self) -> None:
        """Clear all cached data"""
        if not self._cache_dir or not os.path.exists(self._cache_dir):
            return
            
        try:
            # Clear LLM responses
            llm_dir = os.path.join(self._cache_dir, "llm_responses")
            if os.path.exists(llm_dir):
                for file in os.listdir(llm_dir):
                    os.remove(os.path.join(llm_dir, file))
                    
            # Clear agent runs
            agent_dir = os.path.join(self._cache_dir, "agent_runs")
            if os.path.exists(agent_dir):
                for file in os.listdir(agent_dir):
                    os.remove(os.path.join(agent_dir, file))
                    
            logger.info("Cache cleared")
            
        except Exception as e:
            logger.warning(f"Failed to clear cache: {e}")

    @time_execution_sync('--get_cache_key')
    def get_cache_key(self, task: str, browser_state: BrowserState, step: int) -> CacheKey:
        """Generate a cache key from the task and browser state"""
        # Create a hash of the DOM state
        dom_state_hash = None
        if browser_state.element_tree:
            # Use the xpath and attributes of all interactive elements to create a hash
            interactive_elements = []
            
            def collect_interactive(node):
                if hasattr(node, 'is_interactive') and node.is_interactive:
                    interactive_elements.append({
                        'xpath': node.xpath,
                        'tag_name': node.tag_name,
                        'attributes': node.attributes
                    })
                if hasattr(node, 'children'):
                    for child in node.children:
                        collect_interactive(child)
            
            collect_interactive(browser_state.element_tree)
            
            if interactive_elements:
                dom_state_str = json.dumps(interactive_elements, sort_keys=True)
                dom_state_hash = hash(dom_state_str)
        
        return CacheKey(
            task=task,
            url=browser_state.url,
            title=browser_state.title,
            dom_state_hash=str(dom_state_hash) if dom_state_hash else None,
            step=step
        )
    
    @time_execution_sync('--get')
    def get(self, key: CacheKey, settings: CacheSettings) -> Optional[Any]:
        """Get a value from the cache"""
        if not settings.enabled:
            return None
        
        key_hash = key.to_hash()
        
        # Try to load from disk if not in memory
        if key_hash not in self.cache:
            self._load_from_disk(key_hash)
        
        if key_hash in self.cache:
            entry = self.cache[key_hash]
            
            # Check if the entry is expired
            if entry.is_expired(settings.ttl_seconds):
                logger.debug(f"Cache entry expired for key: {key_hash}")
                del self.cache[key_hash]
                self.stats.misses += 1
                return None
            
            logger.debug(f"Cache hit for key: {key_hash}")
            self.stats.hits += 1
            return entry.value
        
        logger.debug(f"Cache miss for key: {key_hash}")
        self.stats.misses += 1
        return None
    
    @time_execution_sync('--set')
    def set(self, key: CacheKey, value: Any, settings: CacheSettings, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Set a value in the cache"""
        if not settings.enabled:
            return
        
        key_hash = key.to_hash()
        
        # Create a new entry
        entry = CacheEntry(
            key=key_hash,
            value=value,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(seconds=settings.ttl_seconds),
            metadata=metadata or {}  # Use empty dict if metadata is None
        )
        
        # Add to cache
        self.cache[key_hash] = entry
        
        # Save to disk
        self._save_to_disk(key_hash, entry)
        
        # Prune cache if needed
        self._prune_cache(settings.max_entries)
        
        logger.debug(f"Cached value for key: {key_hash}")
    
    def _prune_cache(self, max_entries: int) -> None:
        """Remove oldest entries if cache is too large"""
        if len(self.cache) <= max_entries:
            return
        
        # Sort entries by creation time
        sorted_entries = sorted(
            self.cache.items(),
            key=lambda x: x[1].created_at
        )
        
        # Remove oldest entries
        entries_to_remove = len(self.cache) - max_entries
        for i in range(entries_to_remove):
            key, _ = sorted_entries[i]
            del self.cache[key]
            
            # Remove from disk
            cache_file = self._get_cache_path(key)
            if cache_file.exists():
                os.remove(cache_file)
    
    def _save_to_disk(self, key_hash: str, entry: CacheEntry) -> None:
        """Save a cache entry to disk"""
        try:
            cache_file = self._get_cache_path(key_hash)
            
            # Prepare data for serialization
            data = {
                "data": entry.value,
                "created_at": entry.created_at.isoformat(),
                "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
                "metadata": entry.metadata
            }
            
            with open(cache_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Failed to save cache entry to disk: {e}")
    
    def _load_from_disk(self, key_hash: str) -> None:
        """Load a cache entry from disk"""
        try:
            cache_file = self._cache_dir / f"{key_hash}.json"
            
            if not cache_file.exists():
                return
            
            with open(cache_file, 'r') as f:
                data = json.load(f)
            
            entry = CacheEntry(
                key=key_hash,
                value=data["data"],
                created_at=datetime.fromisoformat(data["created_at"]),
                expires_at=datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None,
                metadata=data["metadata"]
            )
            
            self.cache[key_hash] = entry
        except Exception as e:
            logger.warning(f"Failed to load cache entry from disk: {e}")
    
    def clear(self) -> None:
        """Clear the cache"""
        self.cache.clear()
        self.stats = CacheStats()
        
        # Clear disk cache
        for file in self._get_cache_path("").glob("*.json"):
            os.remove(file)
    
    def get_stats(self) -> CacheStats:
        """Get cache statistics"""
        return self.stats 

    def get_cached_agent_history(self, task: str) -> Optional[AgentHistoryList]:
        """Get cached agent history for a task"""
        task_hash = self._compute_hash(task)
        cache_key = f"agent_history_{task_hash}"
        
        # Check if we have a cached entry
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if not entry.is_expired(self.settings.ttl_seconds):
                self.stats.hits += 1
                return entry.value
        
        # Try to load from disk
        cache_path = self._get_cache_path(cache_key, "agent_history")
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    data = json.load(f)
                
                # Create AgentHistoryList from data
                # Since AgentHistoryList is a dataclass, we need to create it manually
                history_items = []
                for item_data in data.get("items", []):
                    history_item = AgentHistory.model_validate(item_data)
                    history_items.append(history_item)
                
                history = AgentHistoryList(items=history_items)
                
                # Cache it in memory
                self.cache[cache_key] = CacheEntry(
                    key=cache_key,
                    value=history,
                    created_at=datetime.now(),
                    expires_at=datetime.now() + timedelta(seconds=self.settings.ttl_seconds)
                )
                
                self.stats.hits += 1
                return history
            except Exception as e:
                logger.warning(f"Failed to load cached agent history: {e}")
        
        self.stats.misses += 1
        return None

    def cache_agent_history(self, task: str, history: AgentHistoryList) -> None:
        """Cache agent history for a task"""
        task_hash = self._compute_hash(task)
        cache_key = f"agent_history_{task_hash}"
        
        # Convert history to dict
        history_dict = history.to_dict()
        
        # Save to disk
        cache_path = self._get_cache_path(cache_key, "agent_history")
        try:
            with open(cache_path, "w") as f:
                json.dump(history_dict, f)
            
            # Cache in memory
            self.cache[cache_key] = CacheEntry(
                key=cache_key,
                value=history,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(seconds=self.settings.ttl_seconds)
            )
            
            logger.debug(f"Cached agent history for task: {task}")
        except Exception as e:
            logger.warning(f"Failed to cache agent history: {e}") 