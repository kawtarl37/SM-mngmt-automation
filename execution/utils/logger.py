import os
import logging
import json
from datetime import datetime
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "execution" / "data"
LOGS_DIR = BASE_DIR / "logs"
TMP_DIR = BASE_DIR / ".tmp"

# Create required directories if they don't exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
(TMP_DIR / "pins").mkdir(parents=True, exist_ok=True)

class JsonFormatter(logging.Formatter):
    """Format logs as JSON strings for easy parsing."""
    def format(self, record):
        log_obj = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage()
        }
        if record.exc_info:
            log_obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

def setup_logger(name: str) -> logging.Logger:
    """Initialize and return a structured JSON logger."""
    logger = logging.getLogger(name)
    
    # Only configure if it hasn't been configured yet
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # File handler (JSON format, one file per day)
        date_str = datetime.now().strftime("%Y%m%d")
        log_file = LOGS_DIR / f"pipeline_{date_str}.log"
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)
        
        # Console handler (standard formatting for readability)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(levelname)s - %(name)s - %(message)s'))
        logger.addHandler(console_handler)
        
    return logger
