import os
import json
import hashlib
import logging
import time
from pathlib import Path
from typing import List, Union, Dict, Any

logger = logging.getLogger(__name__)


# Can be configured via BROWSER_USE_CACHE_DIR environment variable
CACHE_DIR = Path(os.getenv('BROWSER_USE_CACHE_DIR', '.cache/task_plans'))
# Ensure the cache directory exists, creating it if necessary
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_EXPIRATION_DAYS = 7  # Cache files older than this will be deleted
CACHE_MAX_SIZE_MB = 100  # Maximum cache size in megabytes

# Normalize the DOM string to reduce sensitivity to minor changes
def _normalize_dom(dom: str) -> str:
    """Normalize the DOM string to reduce sensitivity to minor changes."""
    # Remove extra whitespace and line breaks
    normalized_dom = " ".join(dom.split())
    # Optionally, add more normalization logic here if needed
    return normalized_dom

# Generate a unique hash based on task, URL, and normalized DOM content
def _hash_data(task: str, url: str, dom: str) -> str:
    """Generate a unique hash based on task, URL, and normalized DOM content."""
    if task is None or url is None or dom is None:
        raise ValueError("Task, URL, and DOM must not be None")
    fingerprint_data = {
        "task": task.strip().lower(),
        "url": url.strip().lower(),
        "dom": _normalize_dom(dom)  # Use normalized DOM
    }
    fingerprint_json = json.dumps(fingerprint_data, sort_keys=True)
    return hashlib.sha256(fingerprint_json.encode()).hexdigest()

# Load a cached task plan if it exists
def load_cached_plan(task: str, url: str, dom: str):
    try:
        # Generate a unique key for the cache file
        key = _hash_data(task, url, dom)
        file_path = CACHE_DIR / f"{key}.json"
        # Check if the cache file exists
        if file_path.exists():
            # Read and return the cached plan as a dictionary
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load cached plan: {e}")
    # Return None if no cache file is found or an error occurs
    return None

# Save a task plan to the cache
def save_plan_to_cache(task: str, url: str, dom: str, plan: List[Dict[str, Any]]) -> None:
    if not isinstance(plan, list):
        logger.error("Invalid plan format: Expected a list of dictionaries.")
        return
    try:
        # Generate a unique key for the cache file
        key = _hash_data(task, url, dom)
        file_path = CACHE_DIR / f"{key}.json"
        # Write the plan list to the cache file in JSON format
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
    except OSError as e:
        logger.error(f"Failed to save plan to cache: {e}")

# Clear all cached task plans
def clear_cache():
    try:
        # Iterate over all JSON files in the cache directory
        for file in CACHE_DIR.glob("*.json"):
            try:
                # Delete each file
                file.unlink()
            except OSError as e:
                logger.error(f"Failed to delete cache file {file}: {e}")
    except OSError as e:
        logger.error(f"Failed to clear cache directory: {e}")

# Add a mechanism to manage cache size and expiration policy
def _is_expired(file_path: Path) -> bool:
    """Check if a cache file is expired based on its modification time."""
    expiration_time = time.time() - (CACHE_EXPIRATION_DAYS * 86400)  # Convert days to seconds
    return file_path.stat().st_mtime < expiration_time

def _get_cache_size() -> int:
    """Calculate the total size of the cache directory in megabytes."""
    return sum(f.stat().st_size for f in CACHE_DIR.glob("*.json")) // (1024 * 1024)

def manage_cache():
    """Manage cache by removing expired files and ensuring size limit."""
    try:
        # Remove expired files
        for file in CACHE_DIR.glob("*.json"):
            if _is_expired(file):
                try:
                    file.unlink()
                except OSError as e:
                    logger.error(f"Failed to delete expired cache file {file}: {e}")

        # Check if cache size exceeds the limit
        while _get_cache_size() > CACHE_MAX_SIZE_MB:
            # Find the oldest file and delete it
            oldest_file = min(CACHE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, default=None)
            if oldest_file:
                try:
                    oldest_file.unlink()
                except OSError as e:
                    logger.error(f"Failed to delete cache file {oldest_file}: {e}")
            else:
                break
    except OSError as e:
        logger.error(f"Failed to manage cache: {e}")
