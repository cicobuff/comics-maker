import json
import os
from pathlib import Path
from typing import Dict, Any


class Config:
    DEFAULT_CONFIG = {
        "settings_directory": str(Path.home() / ".comicsmaker"),
        "projects_directory": str(Path.home() / "Documents" / "ComicsMaker"),
        "undo_limit": 999,
        "min_zoom": 10,
        "max_zoom": 800,
        "scroll_zoom_step": 10,
        "grid_size": 20,
        "panel_border_color": "#000000",
        "panel_border_width": 2,
        "selection_color": "#0066FF",
        "selection_handle_size": 8
    }
    
    def __init__(self):
        self.config_path = Path.home() / ".comicsmaker" / "config.json"
        self.config = self.DEFAULT_CONFIG.copy()
        
    def load(self) -> bool:
        """Load configuration from file. Returns True if config exists."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    loaded = json.load(f)
                    self.config.update(loaded)
                return True
            except Exception as e:
                print(f"Error loading config: {e}")
                return False
        return False
    
    def save(self):
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get(self, key: str, default=None) -> Any:
        """Get configuration value."""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set configuration value."""
        self.config[key] = value
    
    def exists(self) -> bool:
        """Check if configuration file exists."""
        return self.config_path.exists()
    
    def ensure_directories(self):
        """Ensure required directories exist."""
        Path(self.get("settings_directory")).mkdir(parents=True, exist_ok=True)
        Path(self.get("projects_directory")).mkdir(parents=True, exist_ok=True)
