"""
Entry point for the Multi-Agent Stock Management ERP System.
Run this file to start the FastAPI server.

Usage:
    python app.py
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8010,
        reload=True,
        access_log=True,
        log_level="info",
    )
