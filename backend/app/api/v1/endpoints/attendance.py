from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from datetime import datetime, date, timezone, timedelta
from app.core.database import get_db
from app.models.user import User
from app.models.staff import Staff, StaffLeave
from app.models.attendance import Attendance, AttendanceStatusEnum
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate, AttendanceResponse

router = APIRouter()


@router.post("/", response_model=AttendanceResponse, status_code=201)
async def create_attendance(
    attendance: AttendanceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark attendance for a staff member"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == attendance.staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    # Check if attendance already exists for this date
    # Extract date part for comparison (normalize to start of day)
    attendance_date = attendance.attendance_date
    if isinstance(attendance_date, datetime):
        # Convert to UTC and extract date
        if attendance_date.tzinfo is not None:
            attendance_date_utc = attendance_date.astimezone(timezone.utc)
        else:
            attendance_date_utc = attendance_date.replace(tzinfo=timezone.utc)
        attendance_date_only = attendance_date_utc.date()
    else:
        attendance_date_only = attendance_date
    
    # Calculate start and end of the day for comparison (timezone-aware)
    start_of_day = datetime.combine(attendance_date_only, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(attendance_date_only, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    existing = db.query(Attendance).filter(
        Attendance.staff_id == attendance.staff_id,
        Attendance.attendance_date >= start_of_day,
        Attendance.attendance_date <= end_of_day
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Attendance already marked for this date")
    
    db_attendance = Attendance(
        staff_id=attendance.staff_id,
        attendance_date=attendance.attendance_date,
        status=attendance.status.value if isinstance(attendance.status, AttendanceStatusEnum) else attendance.status,
        check_in_time=attendance.check_in_time,
        check_out_time=attendance.check_out_time,
        notes=attendance.notes
    )
    db.add(db_attendance)
    db.commit()
    db.refresh(db_attendance)
    return db_attendance


@router.get("/", response_model=List[AttendanceResponse])
async def list_attendance(
    staff_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List attendance records, including leaves from staff_leaves table"""
    try:
        effective_company_id = get_effective_company_id(current_user)
        query = db.query(Attendance).join(Staff)
        if effective_company_id is not None:
            query = query.filter(Staff.company_id == effective_company_id)
        if staff_id:
            query = query.filter(Attendance.staff_id == staff_id)
        
        # Parse dates and ensure they're timezone-aware
        start = None
        end = None
        
        if start_date:
            start_parsed = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            # Ensure timezone-aware
            if start_parsed.tzinfo is None:
                start = start_parsed.replace(tzinfo=timezone.utc)
            else:
                start = start_parsed.astimezone(timezone.utc)
            query = query.filter(Attendance.attendance_date >= start)
        
        if end_date:
            end_parsed = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            # Ensure timezone-aware
            if end_parsed.tzinfo is None:
                end = end_parsed.replace(tzinfo=timezone.utc)
            else:
                end = end_parsed.astimezone(timezone.utc)
            query = query.filter(Attendance.attendance_date <= end)
        
        attendance_list = query.order_by(Attendance.attendance_date.desc()).all()
        
        # Fetch leaves for the date range and merge them into attendance records
        if start_date and end_date:
            # Ensure start and end are set and timezone-aware
            if start is None:
                start_parsed = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                start = start_parsed if start_parsed.tzinfo else start_parsed.replace(tzinfo=timezone.utc)
            else:
                # Ensure it's in UTC
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                else:
                    start = start.astimezone(timezone.utc)
            
            if end is None:
                end_parsed = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                end = end_parsed if end_parsed.tzinfo else end_parsed.replace(tzinfo=timezone.utc)
            else:
                # Ensure it's in UTC
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                else:
                    end = end.astimezone(timezone.utc)
            
            # Query leaves that overlap with the date range
            leave_query = db.query(StaffLeave).join(Staff)
            if effective_company_id is not None:
                leave_query = leave_query.filter(Staff.company_id == effective_company_id)
            
            if staff_id:
                leave_query = leave_query.filter(StaffLeave.staff_id == staff_id)
            
            # Find leaves that overlap with the date range
            # Ensure all datetime comparisons use timezone-aware datetimes
            leaves = leave_query.filter(
                (
                    # Single date leaves
                    (StaffLeave.leave_from.is_(None) & (StaffLeave.leave_date >= start) & (StaffLeave.leave_date <= end)) |
                    # Date range leaves
                    (StaffLeave.leave_from.isnot(None) & (StaffLeave.leave_from <= end) & (StaffLeave.leave_to >= start))
                )
            ).all()
        
        # Create a set of dates that already have attendance records
        attendance_dates = set()
        for att in attendance_list:
            # Extract UTC date to avoid timezone issues
            if isinstance(att.attendance_date, datetime):
                if att.attendance_date.tzinfo is not None:
                    att_date = att.attendance_date.astimezone(timezone.utc).date()
                else:
                    att_date = att.attendance_date.date()
            else:
                att_date = att.attendance_date
            attendance_dates.add((att.staff_id, att_date))
        
        # Generate attendance records for leave days that don't have attendance records
        leave_attendance_records = []
        
        # Helper function to extract UTC date from datetime
        def extract_utc_date(dt: datetime) -> date:
            """Extract date component from datetime, ensuring correct date in UTC."""
            if dt.tzinfo is not None:
                dt_utc = dt.astimezone(timezone.utc)
                return date(dt_utc.year, dt_utc.month, dt_utc.day)
            else:
                return dt.date()
        
        for leave in leaves:
            try:
                # Determine the date range for this leave
                if leave.leave_from and leave.leave_to:
                    # Extract UTC dates to avoid timezone conversion issues
                    if isinstance(leave.leave_from, datetime):
                        leave_start = extract_utc_date(leave.leave_from)
                    else:
                        leave_start = leave.leave_from
                    
                    if isinstance(leave.leave_to, datetime):
                        leave_end = extract_utc_date(leave.leave_to)
                    else:
                        leave_end = leave.leave_to
                else:
                    # Single date leave
                    if isinstance(leave.leave_date, datetime):
                        leave_date = extract_utc_date(leave.leave_date)
                    else:
                        leave_date = leave.leave_date
                    leave_start = leave_date
                    leave_end = leave_date
                
                # Generate records for each day in the leave range
                current_date = leave_start
                while current_date <= leave_end:
                    # Only include dates within the requested range
                    # Convert start and end to date objects for comparison
                    start_date = start.date() if isinstance(start, datetime) else start
                    end_date = end.date() if isinstance(end, datetime) else end
                    
                    if start_date <= current_date <= end_date:
                        date_key = (leave.staff_id, current_date)
                        if date_key not in attendance_dates:
                            # Create a virtual attendance record for this leave day
                            leave_datetime = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                            leave_attendance = Attendance(
                                id=0,  # Virtual record, no real ID
                                staff_id=leave.staff_id,
                                attendance_date=leave_datetime,
                                status=AttendanceStatusEnum.LEAVE.value,
                                check_in_time=None,
                                check_out_time=None,
                                notes=leave.reason,
                                created_at=leave.created_at
                            )
                            leave_attendance_records.append(leave_attendance)
                            attendance_dates.add(date_key)
                    
                    current_date += timedelta(days=1)
            except Exception as e:
                # Log error but continue processing other leaves
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error processing leave {leave.id}: {str(e)}", exc_info=True)
                continue
        
        # Combine attendance records with leave records (outside the loop)
        attendance_list = list(attendance_list) + leave_attendance_records
        
        # Sort by date descending
        # Normalize all datetimes to UTC-aware for comparison
        def get_sort_key(att):
            """Get a sortable datetime value, ensuring it's timezone-aware."""
            dt = att.attendance_date
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    # Naive datetime - assume UTC and make it aware
                    return dt.replace(tzinfo=timezone.utc)
                else:
                    # Already aware - convert to UTC for consistent comparison
                    return dt.astimezone(timezone.utc)
            else:
                # Date object - convert to datetime at start of day UTC
                return datetime.combine(dt, datetime.min.time()).replace(tzinfo=timezone.utc)
        
        attendance_list.sort(key=get_sort_key, reverse=True)
        
        return attendance_list
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in list_attendance: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch attendance records: {str(e)}")


@router.get("/{attendance_id}", response_model=AttendanceResponse)
async def get_attendance(
    attendance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get attendance by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Attendance).join(Staff).filter(Attendance.id == attendance_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    attendance = query.first()
    
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    
    return attendance


@router.patch("/{attendance_id}", response_model=AttendanceResponse)
async def update_attendance(
    attendance_id: int,
    attendance_update: AttendanceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update attendance record"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Attendance).join(Staff).filter(Attendance.id == attendance_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    attendance = query.first()
    
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    
    if attendance_update.status:
        attendance.status = attendance_update.status.value if isinstance(attendance_update.status, AttendanceStatusEnum) else attendance_update.status
    if attendance_update.check_in_time:
        attendance.check_in_time = attendance_update.check_in_time
    if attendance_update.check_out_time:
        attendance.check_out_time = attendance_update.check_out_time
    if attendance_update.notes is not None:
        attendance.notes = attendance_update.notes
    
    db.commit()
    db.refresh(attendance)
    return attendance


@router.delete("/{attendance_id}", status_code=204)
async def delete_attendance(
    attendance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete attendance record"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Attendance).join(Staff).filter(Attendance.id == attendance_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    attendance = query.first()
    
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    
    db.delete(attendance)
    db.commit()
    return None


@router.post("/staff/{staff_id}/check-in", response_model=AttendanceResponse)
async def check_in_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check in a staff member for today"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    # Get today's date (start of day)
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    # Check if attendance already exists for today
    existing = db.query(Attendance).filter(
        Attendance.staff_id == staff_id,
        Attendance.attendance_date >= start_of_day,
        Attendance.attendance_date <= end_of_day
    ).first()
    
    now = datetime.now(timezone.utc)
    
    if existing:
        # If already checked in, return existing record
        if existing.check_in_time:
            raise HTTPException(status_code=400, detail="Staff member already checked in today")
        # If attendance exists but no check-in time, update it
        existing.check_in_time = now
        existing.status = AttendanceStatusEnum.PRESENT.value
        db.commit()
        db.refresh(existing)
        return existing
    else:
        # Create new attendance record for today
        db_attendance = Attendance(
            staff_id=staff_id,
            attendance_date=now,
            status=AttendanceStatusEnum.PRESENT.value,
            check_in_time=now,
            check_out_time=None
        )
        db.add(db_attendance)
        db.commit()
        db.refresh(db_attendance)
        return db_attendance


@router.post("/staff/{staff_id}/check-out", response_model=AttendanceResponse)
async def check_out_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check out a staff member for today"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    # Get today's date (start of day)
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    # Find today's attendance record
    attendance = db.query(Attendance).filter(
        Attendance.staff_id == staff_id,
        Attendance.attendance_date >= start_of_day,
        Attendance.attendance_date <= end_of_day
    ).first()
    
    if not attendance:
        raise HTTPException(status_code=404, detail="No check-in record found for today")
    
    if not attendance.check_in_time:
        raise HTTPException(status_code=400, detail="Staff member has not checked in today")
    
    if attendance.check_out_time:
        raise HTTPException(status_code=400, detail="Staff member already checked out today")
    
    # Update check-out time
    attendance.check_out_time = datetime.now(timezone.utc)
    db.commit()
    db.refresh(attendance)
    return attendance


@router.get("/staff/{staff_id}/today", response_model=Optional[AttendanceResponse])
async def get_today_attendance(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get today's attendance for a staff member"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Staff).filter(Staff.id == staff_id)
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    staff = query.first()
    
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    
    # Get today's date (start of day)
    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    # Find today's attendance record
    attendance = db.query(Attendance).filter(
        Attendance.staff_id == staff_id,
        Attendance.attendance_date >= start_of_day,
        Attendance.attendance_date <= end_of_day
    ).first()
    
    return attendance
