"""
Utility functions for TikTokMCIntegrator
Common helpers to reduce code duplication.
"""
import os
import json


def load_json(file_path, default=None):
    """Load JSON file safely with fallback default.
    
    Args:
        file_path: Path to JSON file
        default: Default value if file doesn't exist or is invalid
        
    Returns:
        Parsed JSON data or default value
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[UTILS] Failed to load {file_path}: {e}")
    return default if default is not None else {}


def save_json(file_path, data):
    """Save data to JSON file safely.
    
    Args:
        file_path: Path to JSON file
        data: Data to save (must be JSON-serializable)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[UTILS] Failed to save {file_path}: {e}")
        return False


def safe_json_read(path, retries=3):
    """Read a JSON file with retry-on-error for race-condition safety.
    
    Args:
        path: Path to JSON file
        retries: Number of retry attempts (default: 3)
        
    Returns:
        Parsed JSON data or None if all retries fail
    """
    for attempt in range(retries):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            if attempt < retries - 1:
                import time
                time.sleep(0.1 * (attempt + 1))  # Exponential backoff
            else:
                print(f"[UTILS] Failed to read {path} after {retries} attempts: {e}")
                return None
