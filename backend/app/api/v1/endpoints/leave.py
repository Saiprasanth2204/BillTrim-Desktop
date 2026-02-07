from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone, time, date
from app.core.database import get_db
from app.models.user import User
from app.models.staff import Staff, StaffLeave
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.leave import StaffLeaveCreate, StaffLeaveUpdate, StaffLeaveResponse

router = APIRouter()


@router.post("/", response_model=StaffLeaveResponse, status_code=201)
async def create_leave(
    leave: StaffLeaveCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a leave record for a staff member (active staff only)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == leave.staff_id, Staff.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    # Normalize leave_from and leave_to to start/end of day in UTC
    leave_from = leave.leave_from
    leave_to = leave.leave_to
    
    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received leave dates - leave_from: {leave_from} (type: {type(leave_from)}, tzinfo: {leave_from.tzinfo if isinstance(leave_from, datetime) else 'N/A'}), leave_to: {leave_to} (type: {type(leave_to)}, tzinfo: {leave_to.tzinfo if isinstance(leave_to, datetime) else 'N/A'})")
    
    # Helper function to extract date from datetime, ensuring correct calendar date
    def extract_utc_date(dt: datetime) -> date:
        """Extract date component from datetime, ensuring correct date in UTC.
        Since frontend sends UTC datetimes at noon (12:00), we extract the date
        by explicitly getting UTC components to avoid any timezone conversion issues."""
        if dt.tzinfo is not None:
            # Datetime has timezone - convert to UTC first to ensure we're working in UTC
            dt_utc = dt.astimezone(timezone.utc)
            logger.info(f"Extracting date from datetime: {dt} -> UTC: {dt_utc} -> date: {dt_utc.year}-{dt_utc.month}-{dt_utc.day}")
            # Extract date components explicitly from UTC datetime
            # This ensures we get the correct calendar date regardless of any timezone issues
            return date(dt_utc.year, dt_utc.month, dt_utc.day)
        else:
            # Naive datetime - this shouldn't happen if Pydantic parses ISO strings correctly
            # But if it does, we need to be careful. Since frontend sends UTC times,
            # we'll extract date directly but log a warning
            logger.warning(f"Received naive datetime: {dt}, assuming UTC")
            # The issue is that naive datetimes might be interpreted in server's local timezone
            # So we'll extract components directly, assuming they represent UTC
            return date(dt.year, dt.month, dt.day)
    
    # Extract date components ensuring we get the correct calendar date
    if isinstance(leave_from, datetime):
        leave_from_date = extract_utc_date(leave_from)
    else:
        leave_from_date = leave_from
    
    if isinstance(leave_to, datetime):
        leave_to_date = extract_utc_date(leave_to)
    else:
        leave_to_date = leave_to
    
    logger.info(f"Extracted dates - leave_from_date: {leave_from_date}, leave_to_date: {leave_to_date}")
    
    # Create UTC datetimes at start and end of day
    leave_from_start = datetime.combine(leave_from_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    leave_to_end = datetime.combine(leave_to_date, time(23, 59, 59)).replace(tzinfo=timezone.utc)
    
    logger.info(f"Final datetimes - leave_from_start: {leave_from_start}, leave_to_end: {leave_to_end}")
    
    # Check for overlapping leaves
    existing = db.query(StaffLeave).filter(
        StaffLeave.staff_id == leave.staff_id,
        (
            # Check if new leave overlaps with existing leave ranges
            (
                (StaffLeave.leave_from.is_(None) & (StaffLeave.leave_date >= leave_from_start) & (StaffLeave.leave_date <= leave_to_end)) |
                (StaffLeave.leave_from.isnot(None) & (
                    (StaffLeave.leave_from <= leave_to_end) & (StaffLeave.leave_to >= leave_from_start)
                ))
            )
        )
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Leave already exists for this date range")
    
    # Use leave_from_start as leave_date for backward compatibility
    # Normalize leave_date if provided, otherwise use leave_from_start
    if leave.leave_date:
        if isinstance(leave.leave_date, datetime):
            # Extract date and normalize to start of day UTC
            leave_date_normalized = datetime.combine(
                extract_utc_date(leave.leave_date),
                datetime.min.time()
            ).replace(tzinfo=timezone.utc)
        else:
            # Already a date object
            leave_date_normalized = datetime.combine(
                leave.leave_date,
                datetime.min.time()
            ).replace(tzinfo=timezone.utc)
        leave_date = leave_date_normalized
    else:
        leave_date = leave_from_start
    
    try:
        db_leave = StaffLeave(
            staff_id=leave.staff_id,
            leave_date=leave_date,
            leave_from=leave_from_start,
            leave_to=leave_to_end,
            reason=leave.reason,
            is_planned=leave.is_planned,
            is_approved=leave.is_approved
        )
        db.add(db_leave)
        db.commit()
        db.refresh(db_leave)
        return db_leave
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create leave: {str(e)}")


@router.get("/", response_model=List[StaffLeaveResponse])
async def list_leaves(
    staff_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List leave records"""
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = db.query(StaffLeave).join(Staff).filter(Staff.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Staff.branch_id == effective_branch_id)
    
    if staff_id:
        query = query.filter(StaffLeave.staff_id == staff_id)
    
    if start_date:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        # Check if leave range overlaps with start_date
        query = query.filter(
            (StaffLeave.leave_from.is_(None) & (StaffLeave.leave_date >= start)) |
            (StaffLeave.leave_from.isnot(None) & (StaffLeave.leave_to >= start))
        )
    
    if end_date:
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        # Check if leave range overlaps with end_date
        query = query.filter(
            (StaffLeave.leave_from.is_(None) & (StaffLeave.leave_date <= end)) |
            (StaffLeave.leave_from.isnot(None) & (StaffLeave.leave_from <= end))
        )
    
    leaves = query.order_by(StaffLeave.leave_date.desc()).all()
    # Include staff_name from joined Staff (soft-deleted staff still have row so name is available)
    return [
        StaffLeaveResponse(
            id=l.id,
            staff_id=l.staff_id,
            staff_name=l.staff.name if l.staff else "Unknown",
            leave_date=l.leave_date,
            leave_from=l.leave_from,
            leave_to=l.leave_to,
            reason=l.reason,
            is_planned=l.is_planned,
            is_approved=l.is_approved,
            created_at=l.created_at,
        )
        for l in leaves
    ]


@router.get("/staff/{staff_id}/today")
async def check_staff_on_leave_today(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if a staff member is on leave today (active staff only)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == staff_id, Staff.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    # Get today's date
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    # Find today's leave record (check both single date and date range)
    leave = db.query(StaffLeave).filter(
        StaffLeave.staff_id == staff_id,
        (
            # Single date leave
            (StaffLeave.leave_from.is_(None) & (StaffLeave.leave_date >= start_of_day) & (StaffLeave.leave_date <= end_of_day)) |
            # Date range leave
            (StaffLeave.leave_from.isnot(None) & (StaffLeave.leave_from <= end_of_day) & (StaffLeave.leave_to >= start_of_day))
        )
    ).first()
    
    if leave:
        return {
            "is_on_leave": True,
            "leave": leave
        }
    else:
        return {
            "is_on_leave": False,
            "leave": None
        }


@router.get("/{leave_id}", response_model=StaffLeaveResponse)
async def get_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get leave by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(StaffLeave).join(Staff).filter(StaffLeave.id == leave_id, Staff.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    leave = query.first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave not found")
    return leave


@router.patch("/{leave_id}", response_model=StaffLeaveResponse)
async def update_leave(
    leave_id: int,
    leave_update: StaffLeaveUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update leave record (only for active staff)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(StaffLeave).join(Staff).filter(StaffLeave.id == leave_id, Staff.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    leave = query.first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave not found")
    
    # Prevent editing approved leaves
    if leave.is_approved:
        raise HTTPException(status_code=400, detail="Cannot edit approved leaves")
    
    # Helper function to extract date from datetime, ensuring correct calendar date
    def extract_utc_date(dt: datetime) -> date:
        """Extract date component from datetime, ensuring correct date in UTC."""
        if dt.tzinfo is not None:
            dt_utc = dt.astimezone(timezone.utc)
            return date(dt_utc.year, dt_utc.month, dt_utc.day)
        else:
            return date(dt.year, dt.month, dt.day)
    
    if leave_update.leave_date is not None:
        # Normalize leave_date if provided
        if isinstance(leave_update.leave_date, datetime):
            leave_date_normalized = datetime.combine(
                extract_utc_date(leave_update.leave_date),
                datetime.min.time()
            ).replace(tzinfo=timezone.utc)
        else:
            leave_date_normalized = datetime.combine(
                leave_update.leave_date,
                datetime.min.time()
            ).replace(tzinfo=timezone.utc)
        leave.leave_date = leave_date_normalized
    
    if leave_update.leave_from is not None:
        # Extract date components ensuring we get the correct calendar date
        if isinstance(leave_update.leave_from, datetime):
            leave_from_date = extract_utc_date(leave_update.leave_from)
        else:
            leave_from_date = leave_update.leave_from
        leave.leave_from = datetime.combine(leave_from_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    
    if leave_update.leave_to is not None:
        # Extract date components ensuring we get the correct calendar date
        if isinstance(leave_update.leave_to, datetime):
            leave_to_date = extract_utc_date(leave_update.leave_to)
        else:
            leave_to_date = leave_update.leave_to
        leave.leave_to = datetime.combine(leave_to_date, time(23, 59, 59)).replace(tzinfo=timezone.utc)
    
    if leave_update.reason is not None:
        leave.reason = leave_update.reason
    if leave_update.is_planned is not None:
        leave.is_planned = leave_update.is_planned
    if leave_update.is_approved is not None:
        leave.is_approved = leave_update.is_approved
    
    try:
        db.commit()
        db.refresh(leave)
        return leave
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update leave: {str(e)}")


@router.delete("/{leave_id}", status_code=204)
async def delete_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete leave record (only for active staff)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(StaffLeave).join(Staff).filter(StaffLeave.id == leave_id, Staff.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    leave = query.first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave not found")
    
    # Prevent deleting approved leaves
    if leave.is_approved:
        raise HTTPException(status_code=400, detail="Cannot delete approved leaves")
    
    try:
        db.delete(leave)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete leave: {str(e)}")
