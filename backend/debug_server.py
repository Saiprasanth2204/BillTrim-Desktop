#!/usr/bin/env python3
"""
Debug server script for line-by-line debugging.
This script allows you to set breakpoints and debug the FastAPI application.
"""
import sys
import os
from pathlib import Path

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Set up environment
os.chdir(backend_dir)

# Import and run uvicorn with debugpy support
if __name__ == "__main__":
    import uvicorn
    
    # Run with reload enabled for debugging
    # Use import string format for reload to work properly
    # Set breakpoints in your code and the debugger will stop there
    uvicorn.run(
        "app.main:app",  # Use import string format for reload
        host="127.0.0.1",
        port=8765,
        reload=True,  # Auto-reload on code changes
        log_level="debug"  # Verbose logging
    )
