#!/usr/bin/env python3
"""
Standalone server script for Electron desktop app.
This script starts the FastAPI server with proper configuration.
"""
import sys
import os
from pathlib import Path

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Set up environment
os.chdir(backend_dir)

# Ensure data directory exists
data_dir = backend_dir / 'data'
data_dir.mkdir(exist_ok=True)

# Ensure uploads directory exists
uploads_dir = backend_dir / 'uploads'
uploads_dir.mkdir(exist_ok=True)

# Initialize database if it doesn't exist
db_path = data_dir / 'billtrim.db'
if not db_path.exists():
    print("Database not found. Initializing...")
    try:
        from scripts.init_db import init_db
        init_db()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Warning: Could not initialize database: {e}")

# Run migrations once in this process before uvicorn starts (avoids running in async startup)
def run_migrations():
    try:
        from alembic.config import Config
        from alembic import command
        alembic_ini = backend_dir / "alembic.ini"
        if alembic_ini.exists():
            print("Running database migrations...")
            cfg = Config(str(alembic_ini))
            command.upgrade(cfg, "head")
            print("Migrations complete.")
        else:
            print("No alembic.ini found, skipping migrations.")
    except Exception as e:
        print(f"Warning: Migrations failed (server will still start): {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    import uvicorn
    import sys
    import socket
    
    def is_port_in_use(host, port):
        """Check if a port is already in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return False
            except OSError:
                return True
    
    HOST = "127.0.0.1"
    PORT = 8765
    
    # Check if port is already in use; retry a few times (e.g. previous instance still shutting down)
    import time
    for attempt in range(3):
        if not is_port_in_use(HOST, PORT):
            break
        if attempt == 0:
            print(f"Port {PORT} is in use. Waiting for it to be free (retry 1/3)...", file=sys.stderr)
        else:
            print(f"Port {PORT} still in use. Retrying in 3s ({attempt + 1}/3)...", file=sys.stderr)
        time.sleep(3)
    else:
        print(f"ERROR: Port {PORT} is still in use after retries. Another instance may be running.", file=sys.stderr)
        print(f"Please stop the existing server or kill the process: lsof -ti:{PORT} | xargs kill -9", file=sys.stderr)
        sys.exit(1)
    
    # Run migrations before starting server (so FastAPI startup doesn't run them)
    run_migrations()

    # Test import before starting server
    try:
        print("Testing app import...")
        from app.main import app
        print("App import successful!")
    except Exception as e:
        print(f"ERROR: Failed to import app: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    
    try:
        print("Starting uvicorn server...")
        print(f"Python executable: {sys.executable}")
        print(f"Working directory: {os.getcwd()}")
        print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")
        
        # Run the server - use reload=False to prevent issues
        uvicorn.run(
            "app.main:app",
            host=HOST,
            port=PORT,
            log_level="info",
            access_log=True,
            reload=False,  # Explicitly disable reload
        )
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"ERROR: Port {PORT} is already in use. Another instance may be running.", file=sys.stderr)
            print(f"Please stop the existing server or kill the process using port {PORT}.", file=sys.stderr)
            print(f"To find and kill the process: lsof -ti:{PORT} | xargs kill -9", file=sys.stderr)
        else:
            print(f"ERROR: OS error starting server: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except SystemExit as e:
        print(f"Server exited with code: {e.code}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(e.code if e.code is not None else 1)
    except Exception as e:
        print(f"ERROR: Failed to start server: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
