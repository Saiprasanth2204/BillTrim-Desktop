import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.core.config import settings

# Log directory: use BILLTRIM_LOG_DIR from env (set by Electron in production), else ./logs
_log_dir_env = os.environ.get("BILLTRIM_LOG_DIR")
if _log_dir_env:
    LOG_DIR = Path(_log_dir_env)
else:
    LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("billtrim_desktop")
logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
logger.handlers.clear()

_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
console_handler.setFormatter(_formatter)
logger.addHandler(console_handler)

# File (production-friendly: under BILLTRIM_LOG_DIR when set)
if _log_dir_env or True:
    try:
        log_file = LOG_DIR / "backend.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
        file_handler.setFormatter(_formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"billtrim_desktop.{name}")
