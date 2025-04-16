import os
import json
import hashlib
from pathlib import Path

# Directory where cached task plans will be stored
CACHE_DIR = Path(".cache/task_plans")
# Ensure the cache directory exists, creating it if necessary
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Generate a unique hash based on task, URL, and DOM content
def _hash_data(task: str, url: str, dom: str) -> str:
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
    # Generate a unique key for the cache file
    key = _hash_data(task, url, dom)
    file_path = CACHE_DIR / f"{key}.json"
    # Check if the cache file exists
    if file_path.exists():
        # Read and return the cached plan as a dictionary
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Return None if no cache file is found
    return None

# Save a task plan to the cache
def save_plan_to_cache(task: str, url: str, dom: str, plan: dict):
    # Generate a unique key for the cache file
    key = _hash_data(task, url, dom)
    file_path = CACHE_DIR / f"{key}.json"
    # Write the plan dictionary to the cache file in JSON format
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

# Clear all cached task plans
def clear_cache():
    # Iterate over all JSON files in the cache directory
    for file in CACHE_DIR.glob("*.json"):
        # Delete each file
        file.unlink()
