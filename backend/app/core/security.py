from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
import secrets
import hashlib
from app.core.config import settings


def hash_sha256(text: str) -> str:
    """Hash text using SHA-256."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def verify_password(received_password: str, hashed_password: str) -> bool:
    """
    Verify password. Handles frontend-hashed passwords (SHA-256 hash, then bcrypt).
    
    Frontend now always sends SHA-256 hashed passwords. The backend stores them as
    bcrypt(SHA-256(plaintext)). This function compares the received SHA-256 hash
    with the stored bcrypt hash.
    
    Args:
        received_password: SHA-256 hash of password (from frontend)
        hashed_password: Stored bcrypt hash of SHA-256(password)
    
    Returns:
        bool: True if password matches
    """
    try:
        # Frontend always sends SHA-256 hashed passwords (64 hex characters)
        # The stored hash is bcrypt(SHA-256(plaintext))
        # So we compare the SHA-256 hash directly with the stored bcrypt hash
        sha256_hash_bytes = received_password.encode('utf-8')
        if len(sha256_hash_bytes) > 72:
            sha256_hash_bytes = sha256_hash_bytes[:72]
        
        # Compare SHA-256 hash with stored bcrypt hash
        return bcrypt.checkpw(sha256_hash_bytes, hashed_password.encode('utf-8'))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """
    Hash password for storage. 
    Frontend sends SHA-256 hash, so we bcrypt that hash.
    For direct password input (e.g., admin tools), hash with SHA-256 first.
    
    Args:
        password: Password (may be SHA-256 hash from frontend or plaintext)
    
    Returns:
        str: Bcrypt hash of the password (or SHA-256 hash if from frontend)
    """
    # Check if password is already a SHA-256 hash (64 hex characters)
    is_sha256_hash = len(password) == 64 and all(c in '0123456789abcdef' for c in password.lower())
    
    if is_sha256_hash:
        # Password is already SHA-256 hashed (from frontend)
        password_bytes = password.encode('utf-8')
    else:
        # Password is plaintext, hash with SHA-256 first
        sha256_hash = hash_sha256(password)
        password_bytes = sha256_hash.encode('utf-8')
    
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": secrets.token_urlsafe(32),
        "type": "access"
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str, verify_exp: bool = True) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": verify_exp}
        )
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None
