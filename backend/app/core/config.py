from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import os


class Settings(BaseSettings):
    APP_NAME: str = "BillTrim Desktop"
    DEBUG: bool = True

    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/billtrim.db")

    @property
    def DATABASE_URL(self) -> str:
        # Always resolve path relative to backend directory, not current working directory
        db_path = self.DATABASE_PATH
        if not os.path.isabs(db_path):
            # Get backend directory (go up from app/core/config.py -> app/core -> app -> backend)
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(backend_dir, db_path)
        return f"sqlite:///{os.path.abspath(db_path)}"

    SECRET_KEY: str = os.getenv("SECRET_KEY", "desktop-dev-secret-change-me")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8765", "http://127.0.0.1:8765"]

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024  # 5MB

    @property
    def UPLOAD_DIR_ABS(self) -> str:
        """Get absolute path for upload directory."""
        upload_dir = self.UPLOAD_DIR
        if os.path.isabs(upload_dir):
            return upload_dir
        # Resolve relative to backend directory
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(backend_dir, upload_dir)

    # SMS configuration (via MessageBot API)
    SMS_ENABLED: bool = os.getenv("SMS_ENABLED", "false").lower() == "true"
    USE_CELERY_FOR_SMS: bool = False
    MESSAGEBOT_API_TOKEN: str = os.getenv("MESSAGEBOT_API_TOKEN", "")
    MESSAGEBOT_SENDER_ID: str = os.getenv("MESSAGEBOT_SENDER_ID", "")  # Your registered sender ID (e.g., BILLTM)

    # Optional fields from .env that may not be used by all parts of the app
    HOST: str = "127.0.0.1"
    PORT: int = 8765

    # License and discount codes
    LICENSE_PRICE_INR: int = int(os.getenv("LICENSE_PRICE_INR", "0"))  # Charge per license in INR (0 = free for now)
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")  # Optional: required in X-Admin-API-Key header for admin endpoints (e.g. discount code generator)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"  # Ignore extra environment variables
    )


settings = Settings()
