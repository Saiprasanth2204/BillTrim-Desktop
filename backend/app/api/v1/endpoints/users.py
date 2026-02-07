from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, EmailStr
from app.core.database import get_db
from app.models.user import User, RoleEnum
from app.models.company import Branch, Company, ApprovalStatusEnum
from app.api.v1.endpoints.auth import get_current_user, get_effective_company_id
from app.schemas.auth import UserResponse
from app.core.security import get_password_hash

router = APIRouter()


def _role_value(role) -> str:
    """Normalize role to string value (DB may return enum or string)."""
    if role is None:
        return ""
    if hasattr(role, "value"):
        return getattr(role, "value", "") or ""
    return str(role).lower()


def _is_owner(user: User) -> bool:
    return _role_value(user.role) == "owner"


def _is_superuser(user: User) -> bool:
    return bool(getattr(user, "is_superuser", False))


class BranchManagerCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    branch_id: int


class BranchManagerResponse(BaseModel):
    id: int
    email: str
    full_name: str
    phone: Optional[str] = None
    branch_id: int
    branch_name: str
    is_active: bool
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("/branch-managers", response_model=UserResponse, status_code=201)
async def create_branch_manager(
    manager_data: BranchManagerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a branch manager (owner only) - one manager per branch"""
    # Only owners can create branch managers
    if not _is_owner(current_user) and not _is_superuser(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only salon owners can create branch managers"
        )
    
    # Validate branch_id
    branch_id = getattr(manager_data, "branch_id", None)
    if branch_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="branch_id is required"
        )
    
    # Verify branch exists and belongs to the company
    branch = db.query(Branch).filter(
        Branch.id == branch_id,
        Branch.company_id == current_user.company_id
    ).first()
    
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )
    
    # Check if branch already has a manager
    existing_manager = db.query(User).filter(
        User.company_id == current_user.company_id,
        User.branch_id == manager_data.branch_id,
        User.role == RoleEnum.MANAGER,
        User.is_active == True
    ).first()
    
    if existing_manager:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Branch '{branch.name}' already has a manager: {existing_manager.email}"
        )
    
    # Check if email already exists (only check active users)
    existing_user = db.query(User).filter(
        User.email == manager_data.email,
        User.is_active == True
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Handle phone uniqueness - set to None if empty or if it would cause conflict (only check active users)
    user_phone = None
    if manager_data.phone and manager_data.phone.strip():
        existing_phone = db.query(User).filter(
            User.phone == manager_data.phone,
            User.is_active == True
        ).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered"
            )
        user_phone = manager_data.phone.strip()
    
    # Create branch manager
    manager = User(
        company_id=current_user.company_id,
        branch_id=manager_data.branch_id,
        email=manager_data.email,
        phone=user_phone,
        hashed_password=get_password_hash(manager_data.password),
        full_name=manager_data.full_name,
        role=RoleEnum.MANAGER,
        is_active=True,
        is_superuser=False
    )
    
    try:
        db.add(manager)
        db.commit()
        db.refresh(manager)
    except IntegrityError as e:
        db.rollback()
        # Check if it's an email or phone constraint violation
        error_msg = str(e.orig)
        if 'email' in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered to an active user"
            )
        elif 'phone' in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered to an active user"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create branch manager due to a database constraint violation"
            )
    
    return manager


@router.get("/branch-managers", response_model=List[BranchManagerResponse])
async def list_branch_managers(
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List branch managers (owner only)"""
    # Only owners (and superusers) can list branch managers
    if not _is_owner(current_user) and not _is_superuser(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only salon owners can view branch managers"
        )
    
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(User).filter(User.role == RoleEnum.MANAGER)
    if effective_company_id is not None:
        query = query.filter(User.company_id == effective_company_id)
    if branch_id:
        query = query.filter(User.branch_id == branch_id)
    managers = query.all()
    
    result = []
    for manager in managers:
        branch = db.query(Branch).filter(Branch.id == manager.branch_id).first()
        result.append(BranchManagerResponse(
            id=manager.id,
            email=manager.email or "",
            full_name=manager.full_name or "Unknown",
            phone=getattr(manager, "phone", None),
            branch_id=manager.branch_id,
            branch_name=branch.name if branch else "Unknown",
            is_active=getattr(manager, "is_active", True),
            last_login=getattr(manager, "last_login", None),
        ))
    return result


@router.delete("/branch-managers/{manager_id}", status_code=204)
async def delete_branch_manager(
    manager_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete/deactivate a branch manager (owner only)"""
    # Only owners can delete branch managers
    if not _is_owner(current_user) and not _is_superuser(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only salon owners can delete branch managers"
        )
    
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(User).filter(User.id == manager_id, User.role == RoleEnum.MANAGER)
    if effective_company_id is not None:
        query = query.filter(User.company_id == effective_company_id)
    manager = query.first()
    
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch manager not found"
        )
    
    # Deactivate instead of deleting
    manager.is_active = False
    db.commit()
    
    return None
