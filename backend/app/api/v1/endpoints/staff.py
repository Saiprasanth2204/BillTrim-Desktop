from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User
from app.models.staff import Staff, StaffWeekOff, StaffRoleEnum
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.staff import StaffCreate, StaffUpdate, StaffResponse

router = APIRouter()


@router.post("/", response_model=StaffResponse, status_code=201)
async def create_staff(
    staff: StaffCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new staff member"""
    from app.models.company import Branch
    
    # Validate branch belongs to user's company
    branch = db.query(Branch).filter(
        Branch.id == staff.branch_id,
        Branch.company_id == current_user.company_id,
        Branch.is_active == True
    ).first()
    if not branch:
        raise HTTPException(status_code=403, detail="Branch not found, inactive, or access denied")
    
    # Ensure role is the enum value (lowercase string)
    role_value = staff.role.value if isinstance(staff.role, StaffRoleEnum) else staff.role
    
    # Set defaults: Sunday (6) as weekly off, 9 AM - 7 PM as standard times if not provided
    from datetime import time as dt_time
    default_weekly_off = staff.standard_weekly_off if staff.standard_weekly_off is not None else 6  # Default: Sunday
    default_in_time = staff.standard_in_time if staff.standard_in_time is not None else dt_time(9, 0)  # Default: 9 AM
    default_out_time = staff.standard_out_time if staff.standard_out_time is not None else dt_time(19, 0)  # Default: 7 PM
    
    db_staff = Staff(
        company_id=current_user.company_id,
        branch_id=staff.branch_id,
        name=staff.name,
        phone=staff.phone,
        email=staff.email,
        role=role_value,
        commission_percentage=staff.commission_percentage,
        standard_weekly_off=default_weekly_off,
        standard_in_time=default_in_time,
        standard_out_time=default_out_time
    )
    db.add(db_staff)
    db.flush()
    
    # Add week offs (custom week offs in addition to standard weekly off)
    if staff.week_offs:
        for week_off in staff.week_offs:
            db_week_off = StaffWeekOff(
                staff_id=db_staff.id,
                day_of_week=week_off.day_of_week
            )
            db.add(db_week_off)
    
    db.commit()
    db.refresh(db_staff)
    return db_staff


@router.get("/", response_model=List[StaffResponse])
async def list_staff(
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List staff members (includes name, image_url, week_offs, etc.)."""
    from sqlalchemy.orm import joinedload
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = (
        db.query(Staff)
        .options(joinedload(Staff.week_offs))
        .filter(Staff.is_active == True)
    )
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Staff.branch_id == effective_branch_id)
    
    staff_list = query.all()
    return staff_list


@router.get("/{staff_id}", response_model=StaffResponse)
async def get_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get staff by ID"""
    from sqlalchemy.orm import joinedload
    
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).options(joinedload(Staff.week_offs)).filter(Staff.id == staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    return staff


@router.put("/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: int,
    staff_update: StaffUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update staff member"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    update_data = staff_update.dict(exclude_unset=True)
    
    # Handle role enum conversion
    if 'role' in update_data and update_data['role']:
        role_value = update_data['role'].value if isinstance(update_data['role'], StaffRoleEnum) else update_data['role']
        update_data['role'] = role_value
    
    for field, value in update_data.items():
        setattr(staff, field, value)
    
    db.commit()
    db.refresh(staff)
    return staff


@router.delete("/{staff_id}", status_code=204)
async def delete_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete staff member (soft delete by setting is_active=False)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    # Soft delete by setting is_active to False
    staff.is_active = False
    db.commit()
    return None
