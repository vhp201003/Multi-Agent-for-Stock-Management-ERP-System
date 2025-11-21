"""
Entry point for the Multi-Agent Stock Management ERP System.
Run this file to start the FastAPI server.

Usage:
    python app.py
"""

import uvicorn
from dotenv import load_dotenv

from config.settings import get_env_bool, get_env_str, get_server_host, get_server_port

# Load environment variables from .env file
load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=get_server_host(),
        port=get_server_port(),
        reload=get_env_bool("RELOAD", True),
        access_log=True,
        log_level=get_env_str("LOG_LEVEL", "info"),
    )
