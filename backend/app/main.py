from pathlib import Path
import os
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.config import settings
from app.core.logging_config import get_logger  # ensure file logging is registered at startup
import logging

logger = get_logger("main")

# Configure logging to ensure errors are visible
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="BillTrim Desktop API",
    description="Salon Management – Local/Desktop",
    version="1.0.0",
    redirect_slashes=False,
)

# Import router after app creation to catch import errors
try:
    from app.api.v1.api import api_router
    logger.info("Successfully imported api_router")
except Exception as e:
    logger.error(f"Failed to import api_router: {e}", exc_info=True)
    raise

@app.on_event("startup")
async def startup_event():
    """Application startup. Migrations are run by run_server.py before uvicorn starts."""
    logger.info("=== Application startup complete ===")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def get_cors_headers(request: Request) -> dict:
    """Get CORS headers based on request origin"""
    origin = request.headers.get("origin")
    if origin and origin in settings.CORS_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }
    return {}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to ensure CORS headers are always sent"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    cors_headers = get_cors_headers(request)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "error": str(exc) if settings.DEBUG else "An error occurred"},
        headers=cors_headers
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTP exception handler with CORS headers"""
    cors_headers = get_cors_headers(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=cors_headers
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Validation exception handler with CORS headers.
    When the error is 'current_user' / auth missing, return 401 so the client treats it as session expired.
    """
    cors_headers = get_cors_headers(request)
    errors = exc.errors()
    # If this is "current_user" / auth dependency missing (no token), return 401 instead of 422
    for err in errors:
        loc = err.get("loc") or []
        loc_str = " ".join(str(x) for x in loc).lower()
        if "current_user" in loc_str and err.get("type") == "missing":
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"},
                headers={**cors_headers, "WWW-Authenticate": "Bearer"},
            )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": errors},
        headers=cors_headers
    )

try:
    app.include_router(api_router, prefix="/api/v1")
    logger.info("Successfully included api_router")
except Exception as e:
    logger.error(f"Failed to include api_router: {e}", exc_info=True)
    raise

# Serve uploaded files (logos, staff photos) as static files
# This only handles GET requests, so it won't conflict with API routes (POST/DELETE)
# API routes are at /api/v1/uploads/*, static files are at /uploads/*
upload_dir_abs = settings.UPLOAD_DIR_ABS
if Path(upload_dir_abs).exists():
    app.mount("/uploads", StaticFiles(directory=upload_dir_abs), name="uploads")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
