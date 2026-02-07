#!/usr/bin/env python3
"""
Debug server script for line-by-line debugging (without reload).
Use this version for better breakpoint support - reload can interfere with debugging.
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
    from app.main import app
    
    # Run WITHOUT reload for better debugging support
    # Reload can interfere with breakpoints and variable inspection
    # Set breakpoints in your code and the debugger will stop there
    uvicorn.run(
        app,  # Can use app object directly when reload=False
        host="127.0.0.1",
        port=8765,
        reload=False,  # Disabled for better debugging
        log_level="info"  # Use info level for cleaner output
    )
