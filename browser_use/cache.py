import os
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Union, Dict, Any

logger = logging.getLogger(__name__)

# Directory where cached task plans will be stored
CACHE_DIR = Path(".cache/task_plans")
# Ensure the cache directory exists, creating it if necessary
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Generate a unique hash based on task, URL, and DOM content
def _hash_data(task: str, url: str, dom: str) -> str:
    # Validate inputs for None values
    if task is None or url is None or dom is None:
        raise ValueError("Task, URL, and DOM must not be None")
    # Normalize and structure the input data for hashing
    fingerprint_data = {
        "task": task.strip().lower(),  # Normalize task string
        "url": url.strip().lower(),   # Normalize URL string
        "dom": dom.strip()            # Normalize DOM string
    }
    # Convert the structured data to a JSON string with consistent key order
    fingerprint_json = json.dumps(fingerprint_data, sort_keys=True)
    # Return a SHA-256 hash of the JSON string
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
