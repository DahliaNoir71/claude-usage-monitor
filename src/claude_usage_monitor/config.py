"""
Claude Usage Monitor - Configuration
"""
import json
import os
import platform
from pathlib import Path

APP_NAME = "Claude Usage Monitor"
APP_VERSION = "2.1.0"

# Paths
_PKG_DIR = Path(__file__).parent
STATIC_DIR = _PKG_DIR / "static"


def _resolve_data_dir() -> Path:
    """Resolve a stable data directory, independent of CWD.

    Critical: at Windows boot, CWD = C:\\Windows\\System32.
    """
    env_override = os.environ.get("CLAUDE_MONITOR_DATA")
    if env_override:
        return Path(env_override)

    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / "ClaudeUsageMonitor"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ClaudeUsageMonitor"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg) / "claude-usage-monitor"


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "usage.db"
CONFIG_PATH = DATA_DIR / "config.json"
LOG_PATH = DATA_DIR / "monitor.log"
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)

# Server
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8420

# Scraping
SCRAPE_URL = "https://claude.ai/settings/usage"
SCRAPE_INTERVAL_MINUTES = 30
SCRAPE_TIMEOUT_SECONDS = 30
PLAYWRIGHT_HEADLESS = True

# Browser profile
CHROME_USER_DATA_DIR = None

# Model pricing (USD per 1M tokens)
# Updated 2026-03-20 - verify against https://www.anthropic.com/pricing
MODEL_PRICING = {
    "claude-opus-4": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    "claude-sonnet-4": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "claude-haiku-4.5": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_creation": 1.0,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_creation": 1.0,
    },
}

# Plans
PLANS = {
    "free": {
        "name": "Free", "price": 0, "description": "Accès limité",
        "models": ["sonnet", "haiku"], "extended_thinking": False, "priority": "low",
    },
    "pro": {
        "name": "Pro", "price": 20, "description": "Usage standard",
        "models": ["opus", "sonnet", "haiku"], "extended_thinking": "10 min", "priority": "normal",
    },
    "max_100": {
        "name": "Max $100", "price": 100, "description": "5x plus de messages, extended thinking",
        "models": ["opus", "sonnet", "haiku"], "extended_thinking": "45 min", "priority": "high",
    },
    "max_200": {
        "name": "Max $200", "price": 200, "description": "20x plus de messages, priorité max",
        "models": ["opus", "sonnet", "haiku"], "extended_thinking": "45 min", "priority": "highest",
    },
}

DEFAULT_CONFIG = {
    "plan": "max_100",
    "scrape_interval_minutes": SCRAPE_INTERVAL_MINUTES,
    "auto_scrape": True,
    "auto_export_csv": True,
    "notifications_enabled": True,
    "alert_all_models_threshold": 80,
    "alert_sonnet_threshold": 80,
    "alert_on_reset": True,
    "alert_cooldown_minutes": 60,
    "chrome_user_data_dir": None,
    "chrome_profile": "Default",
    "launch_at_startup": False,
    "claude_code_scan_enabled": True,
    "claude_code_dir": None,  # Auto-detect if None
    "claude_code_scan_interval_minutes": 30,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config = {**DEFAULT_CONFIG, **saved}
        except ValueError:
            config = DEFAULT_CONFIG.copy()
            save_config(config)
    else:
        config = DEFAULT_CONFIG.copy()
        save_config(config)
    return config


def save_config(config: dict):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
