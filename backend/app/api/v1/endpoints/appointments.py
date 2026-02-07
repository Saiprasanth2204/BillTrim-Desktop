from typing import List, Optional, Tuple
from datetime import datetime, timedelta, timezone, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from app.core.database import get_db
from app.models.user import User
from app.models.appointment import Appointment, AppointmentService, AppointmentStatusEnum
from app.models.service import Service
from app.models.customer import Customer
from app.models.staff import Staff, StaffLeave, StaffWeekOff
from app.models.attendance import Attendance, AttendanceStatusEnum
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.appointment import (
    AppointmentCreate, AppointmentUpdate, AppointmentResponse, AppointmentServiceResponse,
    AvailabilityCheckRequest, StaffAvailabilityResponse, AvailableSlotResponse, StaffAvailableSlotsRequest,
    StaffAvailabilityDayResponse
)
from app.services.sms_service import send_appointment_confirmation_sms, send_appointment_confirmation_sms_async
from app.core.config import settings

router = APIRouter()


@router.post("/", response_model=AppointmentResponse, status_code=201)
async def create_appointment(
    appointment: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new appointment"""
    from app.models.company import Branch
    
    # Determine branch_id
    branch_id = appointment.branch_id or current_user.branch_id
    
    # If still None (e.g., owner without branch assignment), get first active branch for company
    if branch_id is None:
        branch = db.query(Branch).filter(
            Branch.company_id == current_user.company_id,
            Branch.is_active == True
        ).first()
        if not branch:
            raise HTTPException(status_code=400, detail="No active branch found for your company")
        branch_id = branch.id
    
    # Validate branch belongs to user's company
    branch = db.query(Branch).filter(
        Branch.id == branch_id,
        Branch.company_id == current_user.company_id
    ).first()
    if not branch:
        raise HTTPException(status_code=403, detail="Branch not found or access denied")
    
    # Validate staff belongs to the branch
    staff = db.query(Staff).filter(
        Staff.id == appointment.staff_id,
        Staff.company_id == current_user.company_id,
        Staff.branch_id == branch_id,
        Staff.is_active == True
    ).first()
    if not staff:
        raise HTTPException(status_code=400, detail="Staff not found or does not belong to the selected branch")
    
    # Validate services exist and belong to the branch
    service_ids = [s.service_id for s in appointment.services]
    services = db.query(Service).filter(
        Service.id.in_(service_ids),
        Service.company_id == current_user.company_id,
        Service.branch_id == branch_id,
        Service.is_active == True
    ).all()
    
    if len(services) != len(service_ids):
        raise HTTPException(status_code=400, detail="One or more services not found or do not belong to the selected branch")
    
    # Validate customer belongs to the branch (if branch-specific)
    customer = db.query(Customer).filter(
        Customer.id == appointment.customer_id,
        Customer.company_id == current_user.company_id
    ).first()
    if not customer:
        raise HTTPException(status_code=400, detail="Customer not found")
    
    # Create appointment
    db_appointment = Appointment(
        company_id=current_user.company_id,
        branch_id=branch_id,
        customer_id=appointment.customer_id,
        staff_id=appointment.staff_id,
        appointment_date=appointment.appointment_date,
        notes=appointment.notes,
        created_by=current_user.id
    )
    db.add(db_appointment)
    db.flush()
    
    # Add services
    for appt_service in appointment.services:
        service = next(s for s in services if s.id == appt_service.service_id)
        db_appt_service = AppointmentService(
            appointment_id=db_appointment.id,
            service_id=appt_service.service_id,
            quantity=appt_service.quantity,
            price=int(service.price * 100)  # Convert to paise
        )
        db.add(db_appt_service)
    
    # Commit transaction with error handling
    from app.core.db_transaction import safe_commit
    if not safe_commit(db, "create_appointment"):
        raise HTTPException(status_code=500, detail="Failed to create appointment")
    
    db.refresh(db_appointment)
    
    # Load relationships for response
    db_appointment = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    ).filter(Appointment.id == db_appointment.id).first()
    
    # Send SMS confirmation via MessageBot (async via Celery if enabled, else sync)
    try:
        if settings.USE_CELERY_FOR_SMS:
            send_appointment_confirmation_sms_async(db_appointment.id)
        else:
            send_appointment_confirmation_sms(db_appointment, db)
    except Exception as e:
        # Log error but don't fail the request
        from app.core.logging_config import get_logger
        logger = get_logger("appointments")
        logger.warning(
            f"SMS sending failed for appointment {db_appointment.id}",
            exc_info=True,
            extra={
                "appointment_id": db_appointment.id,
                "customer_id": db_appointment.customer_id,
                "error": str(e)
            }
        )
    
    # Build response
    return {
        "id": db_appointment.id,
        "customer_id": db_appointment.customer_id,
        "customer_name": db_appointment.customer.name,
        "customer_phone": db_appointment.customer.phone,
        "staff_id": db_appointment.staff_id,
        "staff_name": db_appointment.staff.name,
        "appointment_date": db_appointment.appointment_date,
        "status": db_appointment.status,
        "services": [
            {
                "id": s.id,
                "service_id": s.service_id,
                "service_name": s.service.name if s.service else "Unknown",
                "quantity": s.quantity,
                "price": s.price
            }
            for s in db_appointment.services
        ],
        "checked_in_at": db_appointment.checked_in_at,
        "completed_at": db_appointment.completed_at,
        "created_at": db_appointment.created_at,
        "invoice_id": db_appointment.invoice.id if db_appointment.invoice else None
    }


@router.get("/", response_model=List[AppointmentResponse])
async def list_appointments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    staff_id: Optional[int] = None,
    status: Optional[AppointmentStatusEnum] = None,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List appointments"""
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    )
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Appointment.branch_id == effective_branch_id)
    
    if start_date:
        query = query.filter(Appointment.appointment_date >= start_date)
    if end_date:
        query = query.filter(Appointment.appointment_date <= end_date)
    if staff_id:
        query = query.filter(Appointment.staff_id == staff_id)
    if status:
        query = query.filter(Appointment.status == status)
    
    appointments = query.order_by(Appointment.appointment_date).offset(skip).limit(limit).all()
    
    # Serialize with relationships
    return [
        {
            "id": apt.id,
            "customer_id": apt.customer_id,
            "customer_name": apt.customer.name,
            "customer_phone": apt.customer.phone,
            "staff_id": apt.staff_id,
            "staff_name": apt.staff.name,
            "appointment_date": apt.appointment_date,
            "status": apt.status,
            "services": [
                {
                    "id": s.id,
                    "service_id": s.service_id,
                    "service_name": s.service.name if s.service else "Unknown",
                    "quantity": s.quantity,
                    "price": s.price,
                    "duration_minutes": s.service.duration_minutes if s.service else 30
                }
                for s in apt.services
            ],
            "checked_in_at": apt.checked_in_at,
            "completed_at": apt.completed_at,
            "created_at": apt.created_at,
            "invoice_id": apt.invoice.id if apt.invoice else None
        }
        for apt in appointments
    ]


@router.get("/staff-availability-calendar", response_model=List[StaffAvailabilityDayResponse])
async def get_staff_availability_calendar(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get staff availability for each day in a date range.
    Returns a list of daily availability data for the calendar view.
    """
    try:
        effective_company_id = get_effective_company_id(current_user)
        effective_branch_id = get_effective_branch_id(current_user, branch_id)
        
        # Parse dates (format: YYYY-MM-DD)
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Get all active staff for the branch
        staff_query = db.query(Staff).filter(Staff.is_active == True)
        if effective_company_id is not None:
            staff_query = staff_query.filter(Staff.company_id == effective_company_id)
        if effective_branch_id is not None:
            staff_query = staff_query.filter(Staff.branch_id == effective_branch_id)
        
        all_staff = staff_query.all()
        
        # Get all leaves in the date range
        leave_query = db.query(StaffLeave).join(Staff)
        if effective_company_id is not None:
            leave_query = leave_query.filter(Staff.company_id == effective_company_id)
        if effective_branch_id is not None:
            leave_query = leave_query.filter(Staff.branch_id == effective_branch_id)
        
        # Query leaves that overlap with the date range
        start_datetime = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_datetime = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)
        
        leaves = leave_query.filter(
            (
                # Single date leaves
                (StaffLeave.leave_from.is_(None) & (StaffLeave.leave_date >= start_datetime) & (StaffLeave.leave_date <= end_datetime)) |
                # Date range leaves
                (StaffLeave.leave_from.isnot(None) & (StaffLeave.leave_from <= end_datetime) & (StaffLeave.leave_to >= start_datetime))
            )
        ).all()
        
        # Get all week offs
        week_offs = db.query(StaffWeekOff).join(Staff).filter(
            StaffWeekOff.is_active == True
        )
        if effective_company_id is not None:
            week_offs = week_offs.filter(Staff.company_id == effective_company_id)
        if effective_branch_id is not None:
            week_offs = week_offs.filter(Staff.branch_id == effective_branch_id)
        week_offs = week_offs.all()
        
        # Helper function to extract UTC date from datetime
        def extract_utc_date(dt: datetime) -> date:
            if dt.tzinfo is not None:
                dt_utc = dt.astimezone(timezone.utc)
                return date(dt_utc.year, dt_utc.month, dt_utc.day)
            else:
                return dt.date()
        
        # Build a map of staff leaves by date
        leaves_by_staff_date = {}
        for leave in leaves:
            staff_id = leave.staff_id
            if leave.leave_from and leave.leave_to:
                leave_start = extract_utc_date(leave.leave_from)
                leave_end = extract_utc_date(leave.leave_to)
            else:
                leave_date = extract_utc_date(leave.leave_date)
                leave_start = leave_date
                leave_end = leave_date
            
            current_date = leave_start
            while current_date <= leave_end:
                if start <= current_date <= end:
                    key = (staff_id, current_date)
                    if key not in leaves_by_staff_date:
                        leaves_by_staff_date[key] = []
                    leaves_by_staff_date[key].append({
                        "reason": leave.reason,
                        "is_approved": leave.is_approved
                    })
                current_date += timedelta(days=1)
        
        # Build a map of week offs by staff and day of week
        week_offs_by_staff = {}
        for wo in week_offs:
            if wo.staff_id not in week_offs_by_staff:
                week_offs_by_staff[wo.staff_id] = set()
            week_offs_by_staff[wo.staff_id].add(wo.day_of_week)
        
        # Get all appointments in the date range for conflict checking
        appointments_query = db.query(Appointment).filter(
            Appointment.appointment_date >= start_datetime,
            Appointment.appointment_date <= end_datetime,
            Appointment.status.in_([AppointmentStatusEnum.SCHEDULED, AppointmentStatusEnum.CHECKED_IN])
        )
        if effective_company_id is not None:
            appointments_query = appointments_query.filter(Appointment.company_id == effective_company_id)
        if effective_branch_id is not None:
            appointments_query = appointments_query.filter(Appointment.branch_id == effective_branch_id)
        appointments = appointments_query.all()
        
        # Helper function to normalize datetime to UTC (timezone-aware)
        def normalize_to_utc(dt: datetime) -> datetime:
            """Convert datetime to UTC timezone-aware datetime"""
            if dt.tzinfo is None:
                # If naive, assume it's UTC
                return dt.replace(tzinfo=timezone.utc)
            else:
                # If aware, convert to UTC
                return dt.astimezone(timezone.utc)
        
        # Build a map of appointments by staff and date
        appointments_by_staff_date = {}
        for apt in appointments:
            apt_date = extract_utc_date(apt.appointment_date)
            if start <= apt_date <= end:
                key = (apt.staff_id, apt_date)
                if key not in appointments_by_staff_date:
                    appointments_by_staff_date[key] = []
                # Get appointment duration from services
                apt_services = db.query(AppointmentService).filter(
                    AppointmentService.appointment_id == apt.id
                ).all()
                duration_minutes = 30  # Default
                if apt_services:
                    service_ids = [s.service_id for s in apt_services]
                    services = db.query(Service).filter(Service.id.in_(service_ids)).all()
                    if services:
                        duration_minutes = sum(s.duration_minutes for s in services)
                
                # Normalize appointment date to UTC timezone-aware datetime
                apt_start_utc = normalize_to_utc(apt.appointment_date)
                
                appointments_by_staff_date[key].append({
                    "start": apt_start_utc,
                    "duration_minutes": duration_minutes
                })
        
        # Generate calendar data for each day
        calendar_data = []
        current_date = start
        SLOT_INTERVAL_MINUTES = 30  # 30-minute slots
        DEFAULT_DURATION_MINUTES = 30
        
        while current_date <= end:
            day_of_week = current_date.weekday()  # 0=Monday, 6=Sunday
            
            # Get availability for each staff member on this day
            day_staff_availability = []
            for staff in all_staff:
                is_available = True
                reasons = []
                
                # Check standard weekly off
                if staff.standard_weekly_off is not None and staff.standard_weekly_off == day_of_week:
                    is_available = False
                    reasons.append("Standard weekly off")
                
                # Check custom week off
                if staff.id in week_offs_by_staff and day_of_week in week_offs_by_staff[staff.id]:
                    is_available = False
                    reasons.append("Week off")
                
                # Check leave
                leave_key = (staff.id, current_date)
                if leave_key in leaves_by_staff_date:
                    is_available = False
                    leave_info = leaves_by_staff_date[leave_key][0]
                    reason_text = "On leave"
                    if leave_info["reason"]:
                        reason_text += f": {leave_info['reason']}"
                    reasons.append(reason_text)
                
                # Calculate available time slots if staff is available
                available_time_slots = []
                if is_available:
                    # Get staff working hours (default 9 AM - 7 PM)
                    from datetime import time as dt_time
                    in_time = staff.standard_in_time or dt_time(9, 0)
                    out_time = staff.standard_out_time or dt_time(19, 0)
                    
                    # Create day start and end datetimes
                    day_start = datetime.combine(current_date, in_time).replace(tzinfo=timezone.utc)
                    day_end = datetime.combine(current_date, out_time).replace(tzinfo=timezone.utc)
                    
                    # Get appointments for this staff on this day
                    staff_appointments = appointments_by_staff_date.get((staff.id, current_date), [])
                    
                    # Generate time slots
                    current_slot_start = day_start
                    while current_slot_start < day_end:
                        slot_end = current_slot_start + timedelta(minutes=DEFAULT_DURATION_MINUTES)
                        
                        # Check if this slot conflicts with any appointment
                        slot_conflicts = False
                        for apt in staff_appointments:
                            apt_start = apt["start"]
                            apt_end = apt_start + timedelta(minutes=apt["duration_minutes"])
                            
                            # Check if slot overlaps with appointment
                            if not (slot_end <= apt_start or current_slot_start >= apt_end):
                                slot_conflicts = True
                                break
                        
                        if not slot_conflicts and slot_end <= day_end:
                            available_time_slots.append({
                                "start_time": current_slot_start.strftime("%H:%M"),
                                "end_time": slot_end.strftime("%H:%M")
                            })
                        
                        current_slot_start += timedelta(minutes=SLOT_INTERVAL_MINUTES)
                
                day_staff_availability.append({
                    "staff_id": staff.id,
                    "staff_name": staff.name,
                    "is_available": is_available,
                    "reasons": reasons,
                    "available_time_slots": available_time_slots
                })
            
            calendar_data.append({
                "date": current_date.isoformat(),
                "day_of_week": day_of_week,
                "staff_availability": day_staff_availability
            })
            
            current_date += timedelta(days=1)
        
        return calendar_data
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in get_staff_availability_calendar: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch staff availability calendar: {str(e)}")


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get appointment by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    ).filter(Appointment.id == appointment_id)
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    appointment = query.first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    return {
        "id": appointment.id,
        "customer_id": appointment.customer_id,
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "staff_id": appointment.staff_id,
        "staff_name": appointment.staff.name,
        "appointment_date": appointment.appointment_date,
        "status": appointment.status,
        "services": [
            {
                "id": s.id,
                "service_id": s.service_id,
                "service_name": s.service.name if s.service else "Unknown",
                "quantity": s.quantity,
                "price": s.price
            }
            for s in appointment.services
        ],
        "checked_in_at": appointment.checked_in_at,
        "completed_at": appointment.completed_at,
        "created_at": appointment.created_at
    }


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: int,
    appointment_update: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update appointment"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Appointment).filter(Appointment.id == appointment_id)
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    appointment = query.first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status in [AppointmentStatusEnum.COMPLETED]:
        raise HTTPException(
            status_code=400,
            detail="Cannot update completed appointments"
        )
    update_data = appointment_update.dict(exclude_unset=True)
    if 'staff_id' in update_data:
        sq = db.query(Staff).filter(Staff.id == update_data['staff_id'])
        if effective_company_id is not None:
            sq = sq.filter(Staff.company_id == effective_company_id)
        staff = sq.first()
        if not staff:
            raise HTTPException(status_code=400, detail="Invalid staff ID")
    
    for field, value in update_data.items():
        setattr(appointment, field, value)
    
    db.commit()
    db.refresh(appointment)
    
    # Reload with relationships
    appointment = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    ).filter(Appointment.id == appointment.id).first()
    
    return {
        "id": appointment.id,
        "customer_id": appointment.customer_id,
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "staff_id": appointment.staff_id,
        "staff_name": appointment.staff.name,
        "appointment_date": appointment.appointment_date,
        "status": appointment.status,
        "services": [
            {
                "id": s.id,
                "service_id": s.service_id,
                "service_name": s.service.name if s.service else "Unknown",
                "quantity": s.quantity,
                "price": s.price
            }
            for s in appointment.services
        ],
        "checked_in_at": appointment.checked_in_at,
        "completed_at": appointment.completed_at,
        "created_at": appointment.created_at,
        "invoice_id": appointment.invoice.id if appointment.invoice else None
    }


@router.delete("/{appointment_id}", status_code=204)
async def delete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete appointment"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Appointment).filter(Appointment.id == appointment_id)
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    appointment = query.first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Don't allow deleting completed appointments or appointments with invoices
    if appointment.status == AppointmentStatusEnum.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete completed appointments"
        )
    
    if appointment.invoice:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete appointment with associated invoice"
        )
    
    db.delete(appointment)
    db.commit()
    return None


@router.patch("/{appointment_id}/check-in", response_model=AppointmentResponse)
async def check_in_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check in an appointment"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Appointment).filter(Appointment.id == appointment_id)
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    appointment = query.first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    if appointment.status != AppointmentStatusEnum.SCHEDULED:
        raise HTTPException(status_code=400, detail="Appointment is not in scheduled status")
    
    appointment.status = AppointmentStatusEnum.CHECKED_IN
    appointment.checked_in_at = datetime.now(timezone.utc)
    
    db.commit()
    
    # Reload with relationships for response
    appointment = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    ).filter(Appointment.id == appointment.id).first()
    
    return {
        "id": appointment.id,
        "customer_id": appointment.customer_id,
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "staff_id": appointment.staff_id,
        "staff_name": appointment.staff.name,
        "appointment_date": appointment.appointment_date,
        "status": appointment.status,
        "services": [
            {
                "id": s.id,
                "service_id": s.service_id,
                "service_name": s.service.name if s.service else "Unknown",
                "quantity": s.quantity,
                "price": s.price
            }
            for s in appointment.services
        ],
        "checked_in_at": appointment.checked_in_at,
        "completed_at": appointment.completed_at,
        "created_at": appointment.created_at,
        "invoice_id": appointment.invoice.id if appointment.invoice else None
    }


@router.patch("/{appointment_id}/complete", response_model=AppointmentResponse)
async def complete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark appointment as completed"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Appointment).filter(Appointment.id == appointment_id)
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    appointment = query.first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    appointment.status = AppointmentStatusEnum.COMPLETED
    appointment.completed_at = datetime.now(timezone.utc)
    
    db.commit()
    
    # Reload with relationships for response
    appointment = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    ).filter(Appointment.id == appointment.id).first()
    
    return {
        "id": appointment.id,
        "customer_id": appointment.customer_id,
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "staff_id": appointment.staff_id,
        "staff_name": appointment.staff.name,
        "appointment_date": appointment.appointment_date,
        "status": appointment.status,
        "services": [
            {
                "id": s.id,
                "service_id": s.service_id,
                "service_name": s.service.name if s.service else "Unknown",
                "quantity": s.quantity,
                "price": s.price
            }
            for s in appointment.services
        ],
        "checked_in_at": appointment.checked_in_at,
        "completed_at": appointment.completed_at,
        "created_at": appointment.created_at,
        "invoice_id": appointment.invoice.id if appointment.invoice else None
    }


@router.patch("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel an appointment"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Appointment).filter(Appointment.id == appointment_id)
    if effective_company_id is not None:
        query = query.filter(Appointment.company_id == effective_company_id)
    appointment = query.first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Don't allow cancelling completed appointments or appointments with invoices
    if appointment.status == AppointmentStatusEnum.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel completed appointments"
        )
    
    if appointment.invoice:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel appointment with associated invoice"
        )
    
    appointment.status = AppointmentStatusEnum.CANCELLED
    
    db.commit()
    
    # Reload with relationships for response
    appointment = db.query(Appointment).options(
        joinedload(Appointment.customer),
        joinedload(Appointment.staff),
        joinedload(Appointment.services).joinedload(AppointmentService.service),
        joinedload(Appointment.invoice)
    ).filter(Appointment.id == appointment.id).first()
    
    return {
        "id": appointment.id,
        "customer_id": appointment.customer_id,
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "staff_id": appointment.staff_id,
        "staff_name": appointment.staff.name,
        "appointment_date": appointment.appointment_date,
        "status": appointment.status,
        "services": [
            {
                "id": s.id,
                "service_id": s.service_id,
                "service_name": s.service.name if s.service else "Unknown",
                "quantity": s.quantity,
                "price": s.price
            }
            for s in appointment.services
        ],
        "checked_in_at": appointment.checked_in_at,
        "completed_at": appointment.completed_at,
        "created_at": appointment.created_at,
        "invoice_id": appointment.invoice.id if appointment.invoice else None
    }


@router.post("/availability", response_model=List[StaffAvailabilityResponse])
async def check_staff_availability(
    request: AvailabilityCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check staff availability for a given appointment time.
    Returns list of all staff with their availability status.
    """
    effective_company_id = get_effective_company_id(current_user)
    branch_id = request.branch_id or current_user.branch_id
    
    duration_minutes = request.duration_minutes or 30
    if request.service_ids:
        svc_query = db.query(Service).filter(
            Service.id.in_(request.service_ids),
            Service.branch_id == branch_id
        )
        if effective_company_id is not None:
            svc_query = svc_query.filter(Service.company_id == effective_company_id)
        services = svc_query.all()
        if services:
            duration_minutes = sum(service.duration_minutes for service in services)
    
    appointment_date = request.appointment_date
    if appointment_date.tzinfo is None:
        appointment_date = appointment_date.replace(tzinfo=timezone.utc)
    
    appointment_end = appointment_date + timedelta(minutes=duration_minutes)
    appointment_date_only = appointment_date.date()
    day_of_week = appointment_date.weekday()
    
    staff_query = db.query(Staff).filter(
        Staff.branch_id == branch_id,
        Staff.is_active == True
    )
    if effective_company_id is not None:
        staff_query = staff_query.filter(Staff.company_id == effective_company_id)
    all_staff = staff_query.all()
    
    # Pre-calculate day boundaries for efficiency
    start_of_day = datetime.combine(appointment_date_only, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(appointment_date_only, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    availability_results = []
    
    for staff in all_staff:
        is_available = True
        reason = None
        conflicting_appointment_id = None
        
        # Check 1: Standard weekly off (same logic as staff availability page)
        if staff.standard_weekly_off is not None and staff.standard_weekly_off == day_of_week:
            is_available = False
            reason = "Standard weekly off"
        
        # Check 2: Custom week off (StaffWeekOff table)
        if is_available:
            week_off = db.query(StaffWeekOff).filter(
                StaffWeekOff.staff_id == staff.id,
                StaffWeekOff.day_of_week == day_of_week,
                StaffWeekOff.is_active == True
            ).first()
            
            if week_off:
                is_available = False
                reason = "Week off"
        
        # Check 3: Leave
        if is_available:
            leave = db.query(StaffLeave).filter(
                StaffLeave.staff_id == staff.id,
                StaffLeave.leave_date >= start_of_day,
                StaffLeave.leave_date <= end_of_day
            ).first()
            
            if leave:
                is_available = False
                reason = f"On leave: {leave.reason or 'No reason specified'}"
        
        # Check 4: Conflicting appointments
        # Only consider active appointments (scheduled, checked_in) on the same day
        if is_available:
            
            conflicting_query = db.query(Appointment).filter(
                Appointment.staff_id == staff.id,
                Appointment.status.in_([AppointmentStatusEnum.SCHEDULED, AppointmentStatusEnum.CHECKED_IN]),
                Appointment.appointment_date >= start_of_day,
                Appointment.appointment_date <= end_of_day
            )
            if effective_company_id is not None:
                conflicting_query = conflicting_query.filter(Appointment.company_id == effective_company_id)
            conflicting_appointments = conflicting_query.all()
            
            for existing_appt in conflicting_appointments:
                # Calculate existing appointment duration from services
                existing_services = db.query(AppointmentService).filter(
                    AppointmentService.appointment_id == existing_appt.id
                ).all()
                
                existing_duration = 0
                for appt_service in existing_services:
                    service = db.query(Service).filter(Service.id == appt_service.service_id).first()
                    if service:
                        existing_duration += service.duration_minutes * appt_service.quantity
                
                if existing_duration == 0:
                    existing_duration = 30  # Default if no services found
                
                existing_start = existing_appt.appointment_date
                if existing_start.tzinfo is None:
                    existing_start = existing_start.replace(tzinfo=timezone.utc)
                existing_end = existing_start + timedelta(minutes=existing_duration)
                
                # Check for time overlap
                if not (appointment_end <= existing_start or appointment_date >= existing_end):
                    is_available = False
                    conflicting_appointment_id = existing_appt.id
                    reason = f"Conflicting appointment at {existing_start.strftime('%Y-%m-%d %H:%M')}"
                    break
        
        # Check 5: Attendance (optional - check if staff is absent today)
        # This is optional as attendance might not be marked yet for future dates
        if is_available and appointment_date_only == datetime.now(timezone.utc).date():
            start_of_day = datetime.combine(appointment_date_only, datetime.min.time()).replace(tzinfo=timezone.utc)
            end_of_day = datetime.combine(appointment_date_only, datetime.max.time()).replace(tzinfo=timezone.utc)
            
            attendance = db.query(Attendance).filter(
                Attendance.staff_id == staff.id,
                Attendance.attendance_date >= start_of_day,
                Attendance.attendance_date <= end_of_day
            ).first()
            
            if attendance and attendance.status == AttendanceStatusEnum.ABSENT:
                is_available = False
                reason = "Absent today"
        
        availability_results.append(StaffAvailabilityResponse(
            staff_id=staff.id,
            staff_name=staff.name,
            is_available=is_available,
            reason=reason,
            conflicting_appointment_id=conflicting_appointment_id
        ))
    
    return availability_results


def check_staff_available_at_time(
    staff: Staff,
    check_datetime: datetime,
    duration_minutes: int,
    company_id: int,
    db: Session
) -> Tuple[bool, Optional[str]]:
    """
    Helper function to check if a staff member is available at a specific time.
    Returns (is_available, reason_if_unavailable)
    """
    if check_datetime.tzinfo is None:
        check_datetime = check_datetime.replace(tzinfo=timezone.utc)
    
    check_end = check_datetime + timedelta(minutes=duration_minutes)
    check_date_only = check_datetime.date()
    day_of_week = check_datetime.weekday()  # 0=Monday, 6=Sunday
    check_time_only = check_datetime.time()
    
    # Check 1: Standard weekly off (from staff.standard_weekly_off)
    if staff.standard_weekly_off is not None and staff.standard_weekly_off == day_of_week:
        return False, "Standard weekly off"
    
    # Check 2: Week off (from StaffWeekOff table - for custom week offs)
    week_off = db.query(StaffWeekOff).filter(
        StaffWeekOff.staff_id == staff.id,
        StaffWeekOff.day_of_week == day_of_week,
        StaffWeekOff.is_active == True
    ).first()
    
    if week_off:
        return False, "Week off"
    
    # Check 3: Standard working hours
    if staff.standard_in_time and staff.standard_out_time:
        # Check if start time is before working hours
        if check_time_only < staff.standard_in_time:
            return False, f"Before working hours (starts at {staff.standard_in_time.strftime('%H:%M')})"
        
        # Check if appointment end time exceeds standard out time
        check_end_time = check_end.time()
        if check_end_time > staff.standard_out_time:
            return False, f"Appointment extends beyond working hours (ends at {staff.standard_out_time.strftime('%H:%M')})"
    
    # Check 4: Leave
    start_of_day = datetime.combine(check_date_only, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(check_date_only, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    leave = db.query(StaffLeave).filter(
        StaffLeave.staff_id == staff.id,
        or_(
            and_(
                StaffLeave.leave_from.isnot(None),
                StaffLeave.leave_to.isnot(None),
                StaffLeave.leave_from <= check_end,
                StaffLeave.leave_to >= check_datetime
            ),
            and_(
                StaffLeave.leave_from.is_(None),
                StaffLeave.leave_to.is_(None),
                StaffLeave.leave_date >= start_of_day,
                StaffLeave.leave_date <= end_of_day
            )
        )
    ).first()
    
    if leave:
        return False, f"On leave: {leave.reason or 'No reason specified'}"
    
    # Check 5: Conflicting appointments
    # Query appointments on the same day that could potentially conflict
    # Use date comparison to get all appointments on this day regardless of time
    next_day_start = start_of_day + timedelta(days=1)
    conflicting_appointments = db.query(Appointment).filter(
        Appointment.staff_id == staff.id,
        Appointment.company_id == company_id,
        Appointment.status.in_([AppointmentStatusEnum.SCHEDULED, AppointmentStatusEnum.CHECKED_IN]),
        Appointment.appointment_date >= start_of_day,
        Appointment.appointment_date < next_day_start  # All appointments on this day
    ).all()
    
    for existing_appt in conflicting_appointments:
        # Calculate existing appointment duration from services
        existing_services = db.query(AppointmentService).filter(
            AppointmentService.appointment_id == existing_appt.id
        ).all()
        
        existing_duration = 0
        for appt_service in existing_services:
            service = db.query(Service).filter(Service.id == appt_service.service_id).first()
            if service:
                existing_duration += service.duration_minutes * appt_service.quantity
        
        if existing_duration == 0:
            existing_duration = 30  # Default if no services found
        
        existing_start = existing_appt.appointment_date
        if existing_start.tzinfo is None:
            existing_start = existing_start.replace(tzinfo=timezone.utc)
        existing_end = existing_start + timedelta(minutes=existing_duration)
        
        # Check for time overlap
        if not (check_end <= existing_start or check_datetime >= existing_end):
            return False, f"Conflicting appointment at {existing_start.strftime('%Y-%m-%d %H:%M')}"
    
    # Check 6: Attendance (only for today)
    if check_date_only == datetime.now(timezone.utc).date():
        attendance = db.query(Attendance).filter(
            Attendance.staff_id == staff.id,
            Attendance.attendance_date >= start_of_day,
            Attendance.attendance_date <= end_of_day
        ).first()
        
        if attendance and attendance.status == AttendanceStatusEnum.ABSENT:
            return False, "Absent today"
    
    return True, None


@router.post("/staff/{staff_id}/available-slots", response_model=List[AvailableSlotResponse])
async def get_staff_available_slots(
    staff_id: int,
    request: StaffAvailableSlotsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the next available time slots for a specific staff member.
    Returns up to max_slots (default 3) available slots.
    """
    branch_id = request.branch_id or current_user.branch_id
    
    # Validate staff belongs to the branch
    staff = db.query(Staff).filter(
        Staff.id == staff_id,
        Staff.company_id == current_user.company_id,
        Staff.branch_id == branch_id,
        Staff.is_active == True
    ).first()
    
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found or does not belong to the selected branch")
    
    # Calculate duration from services if provided
    duration_minutes = request.duration_minutes or 30
    if request.service_ids:
        services = db.query(Service).filter(
            Service.id.in_(request.service_ids),
            Service.company_id == current_user.company_id,
            Service.branch_id == branch_id
        ).all()
        if services:
            duration_minutes = sum(service.duration_minutes for service in services)
    
    # Start from the requested datetime
    current_datetime = request.from_datetime
    if current_datetime.tzinfo is None:
        current_datetime = current_datetime.replace(tzinfo=timezone.utc)
    
    # Get staff's standard working hours (default to 9 AM - 7 PM if not set)
    from datetime import time as dt_time
    standard_in_time = staff.standard_in_time or dt_time(9, 0)  # Default 9 AM
    standard_out_time = staff.standard_out_time or dt_time(19, 0)  # Default 7 PM
    
    SLOT_INTERVAL_MINUTES = 30  # Check every 30 minutes
    MAX_DAYS_TO_SEARCH = 30  # Search up to 30 days ahead
    
    available_slots = []
    days_searched = 0
    max_slots = request.max_slots or 3
    
    # Round current time to nearest slot
    current_minute = current_datetime.minute
    rounded_minute = (current_minute // SLOT_INTERVAL_MINUTES) * SLOT_INTERVAL_MINUTES
    current_datetime = current_datetime.replace(minute=rounded_minute, second=0, microsecond=0)
    
    while len(available_slots) < max_slots and days_searched < MAX_DAYS_TO_SEARCH:
        # Check if we've moved to a new day
        if days_searched > 0:
            # Move to start of next day at standard in time
            current_datetime = datetime.combine(
                current_datetime.date() + timedelta(days=1),
                standard_in_time
            ).replace(tzinfo=timezone.utc)
        else:
            # For the first day, ensure we're within working hours
            current_time_only = current_datetime.time()
            if current_time_only < standard_in_time:
                current_datetime = datetime.combine(current_datetime.date(), standard_in_time).replace(tzinfo=timezone.utc)
            elif current_time_only >= standard_out_time:
                # Move to start of next day
                current_datetime = datetime.combine(
                    current_datetime.date() + timedelta(days=1),
                    standard_in_time
                ).replace(tzinfo=timezone.utc)
                days_searched += 1
                continue
        
        # Check slots for this day
        day_start = datetime.combine(current_datetime.date(), standard_in_time).replace(tzinfo=timezone.utc)
        day_end_datetime = datetime.combine(current_datetime.date(), standard_out_time).replace(tzinfo=timezone.utc)
        # Latest time we can start an appointment (must end by standard_out_time)
        latest_start = day_end_datetime - timedelta(minutes=duration_minutes)
        
        # If latest_start is before day_start, skip this day (not enough time for appointment)
        if latest_start < day_start:
            days_searched += 1
            continue
        
        check_time = max(current_datetime, day_start)
        
        # Check slots that can complete before the end of working hours
        while check_time <= latest_start and len(available_slots) < max_slots:
            # Check if this slot is available
            is_available, reason = check_staff_available_at_time(
                staff, check_time, duration_minutes, current_user.company_id, db
            )
            
            if is_available:
                # Format the slot for response
                slot_date = check_time.date()
                slot_time_str = check_time.strftime('%H:%M')
                
                # Format display string
                display_date = check_time.strftime('%b %d, %Y')
                display_time = check_time.strftime('%I:%M %p').lower()
                formatted_display = f"{display_date} at {display_time}"
                
                available_slots.append(AvailableSlotResponse(
                    slot_datetime=check_time,
                    formatted_date=slot_date.isoformat(),
                    formatted_time=slot_time_str,
                    formatted_display=formatted_display
                ))
            
            # Move to next slot
            check_time = check_time + timedelta(minutes=SLOT_INTERVAL_MINUTES)
        
        days_searched += 1
    
    return available_slots
