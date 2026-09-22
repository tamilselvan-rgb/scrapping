import os
import json
import logging
from typing import Dict, List, Any

logger = logging.getLogger("scraper.checkpoint")

class CheckpointManager:
    def __init__(self, filepath: str = "output/checkpoint.json"):
        self.filepath = filepath
        self._ensure_dir()

    def _ensure_dir(self):
        dirname = os.path.dirname(self.filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        """
        Loads the checkpoint data if it exists.
        Returns an empty default checkpoint structure if not found or corrupted.
        """
        default_state = {
            "start_url": "",
            "discovered_urls": [],
            "completed_urls": {}, # Maps url to status/timestamp or basic info
            "last_processed_page": 1,
            "is_complete": False
        }
        
        if not os.path.exists(self.filepath):
            return default_state

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure all default keys exist
                for key, val in default_state.items():
                    if key not in data:
                        data[key] = val
                return data
        except Exception as e:
            logger.error(f"Error loading checkpoint file {self.filepath}: {e}. Creating new state.")
            return default_state

    def save(self, state: Dict[str, Any]):
        """
        Saves the checkpoint state to file.
        """
        try:
            # Atomic save: write to temporary file first, then rename
            temp_path = self.filepath + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            
            if os.path.exists(self.filepath):
                os.remove(self.filepath)
            os.rename(temp_path, self.filepath)
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")

    def clear(self):
        """
        Removes the checkpoint file.
        """
        if os.path.exists(self.filepath):
            try:
                os.remove(self.filepath)
            except Exception as e:
                logger.error(f"Failed to remove checkpoint file: {e}")
