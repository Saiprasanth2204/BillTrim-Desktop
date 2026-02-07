from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import distinct
from app.core.database import get_db
from app.models.user import User
from app.models.membership import Membership
from app.models.customer import Customer
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.membership import MembershipCreate, MembershipUpdate, MembershipResponse

router = APIRouter()


@router.post("/", response_model=MembershipResponse, status_code=201)
async def create_membership(
    membership: MembershipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new membership"""
    from app.models.company import Branch
    
    # Validate discount percentage
    if membership.discount_percentage < 0 or membership.discount_percentage > 100:
        raise HTTPException(
            status_code=400, 
            detail="Discount percentage must be between 0 and 100"
        )
    
    effective_company_id = get_effective_company_id(current_user)
    if effective_company_id is None:
        raise HTTPException(status_code=400, detail="Super admin must not create memberships; use a company context")
    # Validate branch belongs to user's company
    branch = db.query(Branch).filter(
        Branch.id == membership.branch_id,
        Branch.company_id == effective_company_id,
        Branch.is_active == True
    ).first()
    if not branch:
        raise HTTPException(status_code=403, detail="Branch not found, inactive, or access denied")
    db_membership = Membership(
        company_id=effective_company_id,
        branch_id=membership.branch_id,
        name=membership.name,
        description=membership.description,
        discount_percentage=membership.discount_percentage,
        is_active=membership.is_active
    )
    db.add(db_membership)
    db.commit()
    db.refresh(db_membership)
    return db_membership


@router.get("/", response_model=List[MembershipResponse])
async def list_memberships(
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all memberships for the company (filtered by branch if specified)"""
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = db.query(Membership)
    if effective_company_id is not None:
        query = query.filter(Membership.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Membership.branch_id == effective_branch_id)
    
    memberships = query.order_by(Membership.name).all()
    return memberships


@router.get("/{membership_id}", response_model=MembershipResponse)
async def get_membership(
    membership_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get membership by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Membership).filter(Membership.id == membership_id)
    if effective_company_id is not None:
        query = query.filter(Membership.company_id == effective_company_id)
    membership = query.first()
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")
    return membership


@router.put("/{membership_id}", response_model=MembershipResponse)
async def update_membership(
    membership_id: int,
    membership_update: MembershipUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update membership"""
    from app.models.company import Branch
    
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Membership).filter(Membership.id == membership_id)
    if effective_company_id is not None:
        query = query.filter(Membership.company_id == effective_company_id)
    membership = query.first()
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")
    update_data = membership_update.dict(exclude_unset=True)
    if 'discount_percentage' in update_data:
        if update_data['discount_percentage'] < 0 or update_data['discount_percentage'] > 100:
            raise HTTPException(
                status_code=400,
                detail="Discount percentage must be between 0 and 100"
            )
    if 'branch_id' in update_data:
        bq = db.query(Branch).filter(
            Branch.id == update_data['branch_id'],
            Branch.is_active == True
        )
        if effective_company_id is not None:
            bq = bq.filter(Branch.company_id == effective_company_id)
        branch = bq.first()
        if not branch:
            raise HTTPException(status_code=403, detail="Branch not found, inactive, or access denied")
    
    for field, value in update_data.items():
        setattr(membership, field, value)
    
    db.commit()
    db.refresh(membership)
    return membership


@router.delete("/{membership_id}", status_code=204)
async def delete_membership(
    membership_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete membership"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Membership).filter(Membership.id == membership_id)
    if effective_company_id is not None:
        query = query.filter(Membership.company_id == effective_company_id)
    membership = query.first()
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")
    
    # Check if any customers are using this membership
    if membership.customers:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete membership that is assigned to customers. Please remove membership from customers first."
        )
    
    db.delete(membership)
    db.commit()
    return None
