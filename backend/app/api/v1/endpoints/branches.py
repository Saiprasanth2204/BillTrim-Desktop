from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, RoleEnum
from app.models.company import Branch, Company, ApprovalStatusEnum
from app.models.user_session import UserSession
from app.api.v1.endpoints.auth import get_current_user, get_effective_company_id
from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional, List

router = APIRouter()


class BranchResponse(BaseModel):
    id: int
    name: str
    address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    gstin: Optional[str]
    state: Optional[str]
    state_code: Optional[str]
    max_logins_per_branch: int
    is_active: bool
    approval_status: str
    active_sessions_count: int

    class Config:
        from_attributes = True


class BranchUpdate(BaseModel):
    max_logins_per_branch: Optional[int] = None


class BranchCreateRequest(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None


class BranchRequestResponse(BaseModel):
    message: str
    branch_id: int
    status: str


class BranchApprovalRequest(BaseModel):
    branch_id: int
    action: str  # "approve" or "reject"
    notes: Optional[str] = None


@router.get("/", response_model=List[BranchResponse])
async def get_branches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all branches for the current user's company (or all branches for super admin)"""
    effective_company_id = get_effective_company_id(current_user)
    if effective_company_id is None:
        # Super admin: show all branches
        branches = db.query(Branch).all()
    elif current_user.role == RoleEnum.OWNER:
        branches = db.query(Branch).filter(Branch.company_id == effective_company_id).all()
    else:
        branches = db.query(Branch).filter(
            Branch.company_id == effective_company_id,
            Branch.approval_status == ApprovalStatusEnum.APPROVED,
            Branch.is_active == True
        ).all()
    
    result = []
    for branch in branches:
        # Count active sessions
        active_sessions_count = db.query(UserSession).filter(
            UserSession.branch_id == branch.id,
            UserSession.is_active == 1,
            UserSession.expires_at > datetime.utcnow()
        ).count()
        
        result.append(BranchResponse(
            id=branch.id,
            name=branch.name,
            address=branch.address,
            phone=branch.phone,
            email=branch.email,
            gstin=branch.gstin,
            state=branch.state,
            state_code=branch.state_code,
            max_logins_per_branch=branch.max_logins_per_branch,
            is_active=branch.is_active,
            approval_status=branch.approval_status.value,
            active_sessions_count=active_sessions_count
        ))
    
    return result


@router.post("/request", response_model=BranchRequestResponse, status_code=201)
async def request_new_branch(
    branch_request: BranchCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new branch (owner only). Desktop: no approval, created active immediately."""
    if current_user.role != RoleEnum.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only salon owners can add new branches"
        )
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    if branch_request.gstin:
        existing_branch = db.query(Branch).filter(Branch.gstin == branch_request.gstin).first()
        if existing_branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GSTIN already registered for another branch"
            )
    branch = Branch(
        company_id=current_user.company_id,
        name=branch_request.name,
        address=branch_request.address,
        phone=branch_request.phone,
        email=branch_request.email,
        gstin=branch_request.gstin,
        state=branch_request.state,
        state_code=branch_request.state_code,
        max_logins_per_branch=5,
        approval_status=ApprovalStatusEnum.APPROVED,
        is_active=True,
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return BranchRequestResponse(
        message=f"Branch '{branch_request.name}' created successfully.",
        branch_id=branch.id,
        status="approved"
    )


@router.put("/{branch_id}", response_model=BranchResponse)
async def update_branch(
    branch_id: int,
    branch_update: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update branch settings (max_logins_per_branch)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Branch).filter(Branch.id == branch_id)
    if effective_company_id is not None:
        query = query.filter(Branch.company_id == effective_company_id)
    branch = query.first()
    
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Only allow OWNER or MANAGER to update
    if current_user.role.value not in ["owner", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Only owners and managers can update branch settings"
        )
    
    if branch_update.max_logins_per_branch is not None:
        if branch_update.max_logins_per_branch < 1:
            raise HTTPException(
                status_code=400,
                detail="max_logins_per_branch must be at least 1"
            )
        branch.max_logins_per_branch = branch_update.max_logins_per_branch
    
    db.commit()
    db.refresh(branch)
    
    # Count active sessions
    active_sessions_count = db.query(UserSession).filter(
        UserSession.branch_id == branch.id,
        UserSession.is_active == 1,
        UserSession.expires_at > datetime.utcnow()
    ).count()
    
    return BranchResponse(
        id=branch.id,
        name=branch.name,
        address=branch.address,
        phone=branch.phone,
        email=branch.email,
        gstin=branch.gstin,
        state=branch.state,
        state_code=branch.state_code,
        max_logins_per_branch=branch.max_logins_per_branch,
        is_active=branch.is_active,
        approval_status=branch.approval_status.value,
        active_sessions_count=active_sessions_count
    )
