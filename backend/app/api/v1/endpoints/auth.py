"""
Desktop auth: JWT only, no Redis, no approval check, no refresh token, no cookies.
"""
import logging
from datetime import timedelta, datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.logging_config import get_logger
logger = get_logger("auth")
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.database import get_db
from app.core.security import (
    verify_password,
    create_access_token,
    decode_access_token,
    get_password_hash,
)
from app.core.config import settings
from app.models.user import User, RoleEnum
from app.models.user_session import UserSession
from app.models.company import Company, Branch
from app.schemas.auth import Token, UserResponse
from app.schemas.onboarding import (
    SalonOnboardingRequest,
    SalonOnboardingResponse,
    SalonListItem,
    SalonHierarchyResponse,
    BranchHierarchyInfo,
    BranchManagerInfo,
)
import hashlib
from typing import List
from fastapi import Query

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Any:

    """Returns the current User. Annotated as Any so FastAPI does not use SQLAlchemy User as a Pydantic response type."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        logger.warning("get_current_user: no token")
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        logger.warning("get_current_user: token decode failed")
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        logger.warning("get_current_user: no sub in payload")
        raise credentials_exception

    user = db.query(User).filter(
        User.email == email,
        User.is_active == True
    ).first()

    if user is None:
        logger.warning("get_current_user: user not found or inactive, email=%s", email)
        raise credentials_exception

    # Optional: verify session for non-superuser (desktop can skip for simplicity)
    if user.branch_id:
        token_hash = hash_token(token)
        active_session = db.query(UserSession).filter(
            and_(
                UserSession.user_id == user.id,
                UserSession.token_hash == token_hash,
                UserSession.is_active == 1,
                UserSession.expires_at > datetime.utcnow()
            )
        ).first()
        if not active_session:
            logger.warning("get_current_user: no active session for user_id=%s branch_id=%s", user.id, user.branch_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return user


def get_effective_branch_id(
    current_user: User,
    requested_branch_id: Optional[int] = None
) -> Optional[int]:
    if current_user.is_superuser:
        return None
    if current_user.role == RoleEnum.OWNER:
        return requested_branch_id
    return current_user.branch_id


def get_effective_company_id(current_user: User) -> Optional[int]:
    if current_user.is_superuser:
        return None
    return current_user.company_id


def cleanup_expired_sessions(db: Session, branch_id: int):
    now = datetime.utcnow()
    db.query(UserSession).filter(
        and_(
            UserSession.branch_id == branch_id,
            UserSession.expires_at < now,
            UserSession.is_active == 1
        )
    ).update({UserSession.is_active: 0})
    db.commit()


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Login: returns JWT in body (no cookies). Desktop: no approval check."""
    email = form_data.username.lower().strip()
    logger.info("login attempt for email=%s", email)

    user = db.query(User).filter(
        User.email == email,
        User.is_active == True
    ).first()

    password_valid = False
    if user:
        password_valid = verify_password(form_data.password, user.hashed_password)

    if not password_valid or not user:
        logger.warning("login failed for email=%s (user=%s, password_valid=%s)", email, user is not None, password_valid)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Desktop: no approval check - all salons are already approved

    if not user.is_superuser and user.branch_id:
        branch = db.query(Branch).filter(Branch.id == user.branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Branch not found"
            )
        cleanup_expired_sessions(db, branch.id)
        
        # Invalidate old active sessions for this user to ensure proper session tracking
        # This ensures each user only has one active session at a time
        db.query(UserSession).filter(
            and_(
                UserSession.user_id == user.id,
                UserSession.is_active == 1,
                UserSession.expires_at > datetime.utcnow()
            )
        ).update({UserSession.is_active: 0})
        db.flush()  # Ensure the update is visible to the count query
        
        active_sessions_count = db.query(UserSession).filter(
            and_(
                UserSession.branch_id == branch.id,
                UserSession.is_active == 1,
                UserSession.expires_at > datetime.utcnow()
            )
        ).count()
        # Managers: max 2 concurrent logins by default; owners use branch setting
        max_allowed = 2 if user.role == RoleEnum.MANAGER else branch.max_logins_per_branch
        if active_sessions_count >= max_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Maximum concurrent logins ({max_allowed}) reached for this branch."
            )

    user.last_login = datetime.utcnow()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "company_id": user.company_id, "role": user.role.value},
        expires_delta=access_token_expires
    )

    if not user.is_superuser and user.branch_id:
        expires_at = datetime.utcnow() + access_token_expires
        token_hash = hash_token(access_token)
        session = UserSession(
            user_id=user.id,
            branch_id=user.branch_id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_active=1
        )
        db.add(session)
    db.commit()

    logger.info("login success for email=%s user_id=%s role=%s branch_id=%s", email, user.id, user.role.value, user.branch_id)
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(access_token_expires.total_seconds())
    )


@router.post("/logout")
async def logout(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """Deactivate current session (no Redis blacklist)."""
    if token:
        payload = decode_access_token(token, verify_exp=False)
        if payload:
            email = payload.get("sub")
            if email:
                user = db.query(User).filter(
                    User.email == email,
                    User.is_active == True
                ).first()
                if user and user.branch_id:
                    token_hash = hash_token(token)
                    db.query(UserSession).filter(
                        and_(
                            UserSession.user_id == user.id,
                            UserSession.token_hash == token_hash,
                            UserSession.is_active == 1
                        )
                    ).update({UserSession.is_active: 0})
                    db.commit()
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/check-first-time")
async def check_first_time(db: Session = Depends(get_db)):
    """Check if this is the first time setup (no users exist except superusers)."""
    try:
        # Check if any non-superuser users exist
        user_count = db.query(User).filter(User.is_superuser == False).count()
        is_first_time = user_count == 0
        # Also check total users (including superusers) - if database is completely empty, it's first time
        total_users = db.query(User).count()
        if total_users == 0:
            is_first_time = True
        return {"is_first_time": is_first_time}
    except Exception as e:
        # If there's an error (e.g., database not initialized), assume first time
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error checking first time: {e}", exc_info=True)
        return {"is_first_time": True}  # Default to first time on error


@router.get("/salons", response_model=List[SalonListItem])
async def list_all_salons(
    status_filter: Optional[str] = Query(None, description="Filter: active, inactive"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all salons (super admin only). Desktop: no pending/rejected filter."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super administrators can view all salons",
        )
    query = db.query(Company)
    if status_filter == "active":
        query = query.filter(Company.is_active == True)
    elif status_filter == "inactive":
        query = query.filter(Company.is_active == False)
    elif status_filter == "pending" or status_filter == "rejected":
        # Desktop: no approval flow
        return []
    companies = query.order_by(Company.created_at.desc()).all()
    return [
        SalonListItem(
            id=c.id,
            name=c.name,
            email=c.email or "",
            phone=c.phone,
            approval_status=c.approval_status.value,
            is_active=c.is_active,
            created_at=c.created_at.isoformat() if c.created_at else None,
        )
        for c in companies
    ]


@router.get("/salons/{salon_id}/hierarchy", response_model=SalonHierarchyResponse)
async def get_salon_hierarchy(
    salon_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get salon hierarchy (super admin only)."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super administrators can view salon hierarchy",
        )
    company = db.query(Company).filter(Company.id == salon_id).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salon not found")
    owner = db.query(User).filter(
        User.company_id == company.id,
        User.role == RoleEnum.OWNER,
    ).first()
    owner_data = {
        "email": owner.email if owner else None,
        "full_name": owner.full_name if owner else None,
        "phone": owner.phone if owner else None,
    }
    branches = db.query(Branch).filter(Branch.company_id == company.id).all()
    branches_data = []
    for branch in branches:
        managers = db.query(User).filter(
            User.company_id == company.id,
            User.branch_id == branch.id,
            User.role == RoleEnum.MANAGER,
        ).all()
        branches_data.append(
            BranchHierarchyInfo(
                id=branch.id,
                name=branch.name,
                address=branch.address,
                phone=branch.phone,
                email=branch.email,
                approval_status=branch.approval_status.value,
                is_active=branch.is_active,
                managers=[
                    BranchManagerInfo(
                        id=m.id,
                        full_name=m.full_name,
                        email=m.email,
                        phone=m.phone,
                        is_active=m.is_active,
                    )
                    for m in managers
                ],
            )
        )
    return SalonHierarchyResponse(
        id=company.id,
        name=company.name,
        email=company.email or "",
        phone=company.phone,
        address=company.address,
        gstin=company.gstin,
        approval_status=company.approval_status.value,
        is_active=company.is_active,
        created_at=company.created_at.isoformat() if company.created_at else None,
        owner=owner_data,
        branches=branches_data,
    )


@router.post("/onboard", response_model=SalonOnboardingResponse)
async def onboard_salon(
    request: SalonOnboardingRequest,
    db: Session = Depends(get_db),
):
    """Onboard a new salon - immediately active (no approval)."""
    from app.services.onboarding_service import create_salon_from_onboarding
    try:
        return create_salon_from_onboarding(request, db)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        from app.core.logging_config import get_logger
        logger = get_logger("auth")
        logger.error(f"Error in onboard_salon: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again."
        )
