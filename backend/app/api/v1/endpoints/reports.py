from typing import Optional, List
from datetime import datetime, timezone
from starlette.requests import Request
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Date, extract, case, String
from app.core.database import get_db
from app.models.user import User, RoleEnum
from app.models.invoice import Invoice, InvoiceItem, Payment, InvoiceStatusEnum
from app.models.attendance import Attendance, AttendanceStatusEnum
from app.models.staff import Staff
from app.models.appointment import Appointment, AppointmentStatusEnum
from app.models.customer import Customer
from app.models.service import Service
from app.models.company import Branch, Company
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.core.cache import cache_get, cache_set, report_cache_key, CACHE_TTL_SHORT

router = APIRouter()


def _parse_report_dates(request: Request) -> tuple[datetime, datetime]:
    """Parse start_date and end_date from query params (handles duplicate/array params)."""
    start_raw = request.query_params.get("start_date")
    end_raw = request.query_params.get("end_date")
    if isinstance(start_raw, list):
        start_raw = start_raw[0] if start_raw else None
    if isinstance(end_raw, list):
        end_raw = end_raw[0] if end_raw else None
    if not start_raw or not end_raw:
        raise HTTPException(status_code=400, detail="start_date and end_date query parameters are required")
    try:
        start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    return start_dt, end_dt


@router.get("/revenue")
async def get_revenue_report(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get revenue report (cached 2 min when Redis available)"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    cache_key = report_cache_key(
        "revenue", effective_company_id, effective_branch_id,
        start_date.isoformat(), end_date.isoformat()
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = db.query(
        func.sum(Invoice.total_amount).label("total_revenue"),
        func.sum(Invoice.tax_amount).label("total_tax"),
        func.count(Invoice.id).label("invoice_count")
    ).filter(
        Invoice.invoice_date >= start_date,
        Invoice.invoice_date <= end_date,
        Invoice.status != InvoiceStatusEnum.VOID,
        Invoice.status != InvoiceStatusEnum.REFUNDED
    )
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Invoice.branch_id == effective_branch_id)
    
    result = query.first()
    data = {
        "total_revenue": float(result.total_revenue or 0),
        "total_tax": float(result.total_tax or 0),
        "invoice_count": result.invoice_count or 0,
        "start_date": start_date,
        "end_date": end_date
    }
    cache_set(cache_key, data, ttl_seconds=CACHE_TTL_SHORT)
    return data


@router.get("/service-wise")
async def get_service_wise_report(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    start_date, end_date = _parse_report_dates(request)
    """Get service-wise revenue report (cached 2 min when Redis available)"""
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    cache_key = report_cache_key(
        "service_wise", effective_company_id, effective_branch_id,
        start_date.isoformat(), end_date.isoformat()
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = db.query(
        InvoiceItem.service_id,
        Service.name.label("service_name"),
        func.sum(InvoiceItem.total_amount).label("revenue"),
        func.sum(InvoiceItem.quantity).label("quantity")
    ).join(
        Invoice, InvoiceItem.invoice_id == Invoice.id
    ).outerjoin(
        Service, InvoiceItem.service_id == Service.id
    ).filter(
        Invoice.invoice_date >= start_date,
        Invoice.invoice_date <= end_date,
        Invoice.status != InvoiceStatusEnum.VOID,
        Invoice.status != InvoiceStatusEnum.REFUNDED,
        InvoiceItem.service_id.isnot(None)
    )
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Invoice.branch_id == effective_branch_id)
    
    results = query.group_by(InvoiceItem.service_id, Service.name).all()
    data = [
        {
            "service_id": r.service_id,
            "service_name": r.service_name or f"Service {r.service_id}",
            "revenue": float(r.revenue or 0),
            "quantity": r.quantity or 0
        }
        for r in results
    ]
    cache_set(cache_key, data, ttl_seconds=CACHE_TTL_SHORT)
    return data


@router.get("/revenue/daily")
async def get_daily_revenue_report(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get daily revenue breakdown (cached 2 min when Redis available)"""
    import logging
    # Use root logger to ensure logs are visible
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Ensure DEBUG level is set
    
    # DEBUG: Log full request details
    logger.info("=" * 80)
    logger.info("DEBUG: /revenue/daily endpoint called")
    logger.info(f"DEBUG: Full URL: {request.url}")
    logger.info(f"DEBUG: Query string: {request.url.query}")
    logger.info(f"DEBUG: Query params type: {type(request.query_params)}")
    logger.info(f"DEBUG: Query params dict: {dict(request.query_params)}")
    
    # Get query params - ensure they're strings
    start_date_raw = request.query_params.get("start_date")
    end_date_raw = request.query_params.get("end_date")
    
    logger.info(f"DEBUG: start_date_raw = {start_date_raw} (type: {type(start_date_raw)})")
    logger.info(f"DEBUG: end_date_raw = {end_date_raw} (type: {type(end_date_raw)})")
    
    if start_date_raw is None or end_date_raw is None:
        logger.error(f"DEBUG: Missing params - start_date_raw={start_date_raw}, end_date_raw={end_date_raw}")
        raise HTTPException(status_code=400, detail="start_date and end_date query parameters are required")
    
    # Handle list case (multiple values)
    if isinstance(start_date_raw, list):
        logger.info(f"DEBUG: start_date_raw is a list: {start_date_raw}")
        start_date_raw = start_date_raw[0] if start_date_raw else None
    if isinstance(end_date_raw, list):
        logger.info(f"DEBUG: end_date_raw is a list: {end_date_raw}")
        end_date_raw = end_date_raw[0] if end_date_raw else None
    
    if start_date_raw is None or end_date_raw is None:
        logger.error(f"DEBUG: After list handling - start_date_raw={start_date_raw}, end_date_raw={end_date_raw}")
        raise HTTPException(status_code=400, detail="start_date and end_date query parameters are required")
    
    # Convert to string explicitly - this is critical
    logger.info(f"DEBUG: Before string conversion - start_date_raw type: {type(start_date_raw)}, value: {repr(start_date_raw)}")
    logger.info(f"DEBUG: Before string conversion - end_date_raw type: {type(end_date_raw)}, value: {repr(end_date_raw)}")
    
    # Use explicit type checking and conversion
    if not isinstance(start_date_raw, str):
        start_date_str = str(start_date_raw)
        logger.info(f"DEBUG: Converted start_date_raw to string: {repr(start_date_str)}")
    else:
        start_date_str = start_date_raw
        logger.info(f"DEBUG: start_date_raw already a string: {repr(start_date_str)}")
    
    if not isinstance(end_date_raw, str):
        end_date_str = str(end_date_raw)
        logger.info(f"DEBUG: Converted end_date_raw to string: {repr(end_date_str)}")
    else:
        end_date_str = end_date_raw
        logger.info(f"DEBUG: end_date_raw already a string: {repr(end_date_str)}")
    
    logger.info(f"DEBUG: After conversion - start_date_str type: {type(start_date_str)}, value: {repr(start_date_str)}")
    logger.info(f"DEBUG: After conversion - end_date_str type: {type(end_date_str)}, value: {repr(end_date_str)}")
    
    if not start_date_str or not end_date_str or not start_date_str.strip() or not end_date_str.strip():
        logger.error(f"DEBUG: Empty strings - start_date_str: {repr(start_date_str)}, end_date_str: {repr(end_date_str)}")
        raise HTTPException(status_code=400, detail="start_date and end_date cannot be empty")
    
    # Parse datetime strings - ensure fromisoformat gets a string
    try:
        logger.info("DEBUG: Starting datetime parsing...")
        
        # Replace Z with +00:00 for ISO format - this always returns a string
        start_date_clean = str(start_date_str).replace('Z', '+00:00')
        end_date_clean = str(end_date_str).replace('Z', '+00:00')
        
        logger.info(f"DEBUG: After replace - start_date_clean type: {type(start_date_clean)}, value: {repr(start_date_clean)}")
        logger.info(f"DEBUG: After replace - end_date_clean type: {type(end_date_clean)}, value: {repr(end_date_clean)}")
        
        # Absolute final check - ensure we're passing strings to fromisoformat
        if not isinstance(start_date_clean, str):
            error_msg = f"CRITICAL: start_date_clean must be str, got {type(start_date_clean)}. Value: {repr(start_date_clean)}"
            logger.error(error_msg)
            raise TypeError(error_msg)
        if not isinstance(end_date_clean, str):
            error_msg = f"CRITICAL: end_date_clean must be str, got {type(end_date_clean)}. Value: {repr(end_date_clean)}"
            logger.error(error_msg)
            raise TypeError(error_msg)
        
        logger.info(f"DEBUG: About to call fromisoformat with start_date_clean: {repr(start_date_clean)}")
        logger.info(f"DEBUG: About to call fromisoformat with end_date_clean: {repr(end_date_clean)}")
        
        # Now call fromisoformat - it MUST receive a string at this point
        start_date = datetime.fromisoformat(start_date_clean)
        logger.info(f"DEBUG: Successfully parsed start_date: {start_date}")
        
        end_date = datetime.fromisoformat(end_date_clean)
        logger.info(f"DEBUG: Successfully parsed end_date: {end_date}")
        
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        else:
            start_date = start_date.astimezone(timezone.utc)
            
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        else:
            end_date = end_date.astimezone(timezone.utc)
            
        logger.info(f"DEBUG: Final dates - start_date: {start_date}, end_date: {end_date}")
    except TypeError as e:
        logger.error(f"DEBUG: TypeError caught: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Type error parsing dates: {str(e)}")
    except ValueError as e:
        logger.error(f"DEBUG: ValueError caught: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        logger.error(f"DEBUG: Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error parsing dates: {str(e)}")
    
    logger.info("DEBUG: Date parsing completed successfully")
    logger.info("=" * 80)
    
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    cache_key = report_cache_key(
        "revenue_daily", effective_company_id, effective_branch_id,
        start_date.isoformat(), end_date.isoformat()
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # Log date values before query
    logger.info(f"DEBUG: About to execute query with start_date: {start_date} (type: {type(start_date)})")
    logger.info(f"DEBUG: About to execute query with end_date: {end_date} (type: {type(end_date)})")
    
    try:
        # Use func.date() instead of cast() to avoid SQLAlchemy datetime conversion issues
        query = db.query(
            func.date(Invoice.invoice_date).label("date"),
            func.sum(Invoice.total_amount).label("revenue"),
            func.count(Invoice.id).label("invoice_count")
        ).filter(
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
            Invoice.status != InvoiceStatusEnum.VOID,
            Invoice.status != InvoiceStatusEnum.REFUNDED
        )
        if effective_company_id is not None:
            query = query.filter(Invoice.company_id == effective_company_id)
        if effective_branch_id is not None:
            query = query.filter(Invoice.branch_id == effective_branch_id)
        
        logger.info(f"DEBUG: Query constructed, about to execute...")
        logger.info(f"DEBUG: Query SQL: {str(query)}")
        
        results = query.group_by(func.date(Invoice.invoice_date)).order_by("date").all()
        logger.info(f"DEBUG: Query executed successfully, got {len(results)} results")
        
        # Process results with error handling
        logger.info("DEBUG: Starting to process results...")
        data = []
        for idx, r in enumerate(results):
            try:
                logger.debug(f"DEBUG: Processing result {idx}: date={r.date}, revenue={r.revenue}")
                date_str = r.date.isoformat() if r.date else None
                data.append({
                    "date": date_str,
                    "revenue": float(r.revenue or 0),
                    "invoice_count": r.invoice_count or 0
                })
            except Exception as e:
                logger.error(f"DEBUG: Error processing result {idx}: {e}", exc_info=True)
                logger.error(f"DEBUG: Result object: {r}, date type: {type(r.date) if r else 'None'}")
                # Skip this result and continue
                continue
        
        logger.info(f"DEBUG: Processed {len(data)} results successfully")
    except Exception as e:
        logger.error(f"DEBUG: Query execution failed: {e}", exc_info=True)
        logger.error(f"DEBUG: start_date type: {type(start_date)}, value: {start_date}")
        logger.error(f"DEBUG: end_date type: {type(end_date)}, value: {end_date}")
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")
    cache_set(cache_key, data, ttl_seconds=CACHE_TTL_SHORT)
    return data


@router.get("/revenue/monthly")
async def get_monthly_revenue_report(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get monthly revenue breakdown"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = db.query(
        extract('year', Invoice.invoice_date).label("year"),
        extract('month', Invoice.invoice_date).label("month"),
        func.sum(Invoice.total_amount).label("revenue"),
        func.count(Invoice.id).label("invoice_count")
    ).filter(
        Invoice.invoice_date >= start_date,
        Invoice.invoice_date <= end_date,
        Invoice.status != InvoiceStatusEnum.VOID,
        Invoice.status != InvoiceStatusEnum.REFUNDED
    )
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Invoice.branch_id == effective_branch_id)
    
    results = query.group_by(
        extract('year', Invoice.invoice_date),
        extract('month', Invoice.invoice_date)
    ).order_by("year", "month").all()
    
    return [
        {
            "year": int(r.year),
            "month": int(r.month),
            "revenue": float(r.revenue or 0),
            "invoice_count": r.invoice_count or 0
        }
        for r in results
    ]


@router.get("/attendance/staff-summary")
async def get_staff_attendance_summary(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get staff attendance summary (cached 2 min when Redis available)"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    cache_key = report_cache_key(
        "attendance_staff", effective_company_id, effective_branch_id,
        start_date.isoformat(), end_date.isoformat()
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    query = db.query(
        Staff.id,
        Staff.name,
        func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.PRESENT).label("present_days"),
        func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.ABSENT).label("absent_days"),
        func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.LEAVE).label("leave_days"),
        func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.HALF_DAY).label("half_days"),
        func.count(Attendance.id).label("total_days")
    ).join(
        Attendance, Staff.id == Attendance.staff_id
    ).filter(
        Staff.is_active == True,
        Attendance.attendance_date >= start_date,
        Attendance.attendance_date <= end_date
    )
    if effective_company_id is not None:
        query = query.filter(Staff.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Staff.branch_id == effective_branch_id)
    
    results = query.group_by(Staff.id, Staff.name).all()
    data = [
        {
            "staff_id": r.id,
            "staff_name": r.name,
            "present_days": r.present_days or 0,
            "absent_days": r.absent_days or 0,
            "leave_days": r.leave_days or 0,
            "half_days": r.half_days or 0,
            "total_days": r.total_days or 0,
            "attendance_rate": round((r.present_days or 0) / (r.total_days or 1) * 100, 2) if r.total_days else 0
        }
        for r in results
    ]
    cache_set(cache_key, data, ttl_seconds=CACHE_TTL_SHORT)
    return data


@router.get("/attendance/daily")
async def get_daily_attendance_report(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get daily attendance breakdown (cached 2 min when Redis available)"""
    import logging
    # Use root logger to ensure logs are visible
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Ensure DEBUG level is set
    
    # DEBUG: Log full request details
    logger.info("=" * 80)
    logger.info("DEBUG: /attendance/daily endpoint called")
    logger.info(f"DEBUG: Full URL: {request.url}")
    logger.info(f"DEBUG: Query string: {request.url.query}")
    logger.info(f"DEBUG: Query params type: {type(request.query_params)}")
    logger.info(f"DEBUG: Query params dict: {dict(request.query_params)}")
    
    # Get query params - ensure they're strings
    start_date_raw = request.query_params.get("start_date")
    end_date_raw = request.query_params.get("end_date")
    
    logger.info(f"DEBUG: start_date_raw = {start_date_raw} (type: {type(start_date_raw)})")
    logger.info(f"DEBUG: end_date_raw = {end_date_raw} (type: {type(end_date_raw)})")
    
    if start_date_raw is None or end_date_raw is None:
        logger.error(f"DEBUG: Missing params - start_date_raw={start_date_raw}, end_date_raw={end_date_raw}")
        raise HTTPException(status_code=400, detail="start_date and end_date query parameters are required")
    
    # Handle list case (multiple values)
    if isinstance(start_date_raw, list):
        logger.info(f"DEBUG: start_date_raw is a list: {start_date_raw}")
        start_date_raw = start_date_raw[0] if start_date_raw else None
    if isinstance(end_date_raw, list):
        logger.info(f"DEBUG: end_date_raw is a list: {end_date_raw}")
        end_date_raw = end_date_raw[0] if end_date_raw else None
    
    if start_date_raw is None or end_date_raw is None:
        logger.error(f"DEBUG: After list handling - start_date_raw={start_date_raw}, end_date_raw={end_date_raw}")
        raise HTTPException(status_code=400, detail="start_date and end_date query parameters are required")
    
    # Convert to string explicitly - this is critical
    logger.info(f"DEBUG: Before string conversion - start_date_raw type: {type(start_date_raw)}, value: {repr(start_date_raw)}")
    logger.info(f"DEBUG: Before string conversion - end_date_raw type: {type(end_date_raw)}, value: {repr(end_date_raw)}")
    
    # Use explicit type checking and conversion
    if not isinstance(start_date_raw, str):
        start_date_str = str(start_date_raw)
        logger.info(f"DEBUG: Converted start_date_raw to string: {repr(start_date_str)}")
    else:
        start_date_str = start_date_raw
        logger.info(f"DEBUG: start_date_raw already a string: {repr(start_date_str)}")
    
    if not isinstance(end_date_raw, str):
        end_date_str = str(end_date_raw)
        logger.info(f"DEBUG: Converted end_date_raw to string: {repr(end_date_str)}")
    else:
        end_date_str = end_date_raw
        logger.info(f"DEBUG: end_date_raw already a string: {repr(end_date_str)}")
    
    logger.info(f"DEBUG: After conversion - start_date_str type: {type(start_date_str)}, value: {repr(start_date_str)}")
    logger.info(f"DEBUG: After conversion - end_date_str type: {type(end_date_str)}, value: {repr(end_date_str)}")
    
    if not start_date_str or not end_date_str or not start_date_str.strip() or not end_date_str.strip():
        logger.error(f"DEBUG: Empty strings - start_date_str: {repr(start_date_str)}, end_date_str: {repr(end_date_str)}")
        raise HTTPException(status_code=400, detail="start_date and end_date cannot be empty")
    
    # Parse datetime strings - ensure fromisoformat gets a string
    try:
        logger.info("DEBUG: Starting datetime parsing...")
        
        # Replace Z with +00:00 for ISO format - this always returns a string
        start_date_clean = str(start_date_str).replace('Z', '+00:00')
        end_date_clean = str(end_date_str).replace('Z', '+00:00')
        
        logger.info(f"DEBUG: After replace - start_date_clean type: {type(start_date_clean)}, value: {repr(start_date_clean)}")
        logger.info(f"DEBUG: After replace - end_date_clean type: {type(end_date_clean)}, value: {repr(end_date_clean)}")
        
        # Absolute final check - ensure we're passing strings to fromisoformat
        if not isinstance(start_date_clean, str):
            error_msg = f"CRITICAL: start_date_clean must be str, got {type(start_date_clean)}. Value: {repr(start_date_clean)}"
            logger.error(error_msg)
            raise TypeError(error_msg)
        if not isinstance(end_date_clean, str):
            error_msg = f"CRITICAL: end_date_clean must be str, got {type(end_date_clean)}. Value: {repr(end_date_clean)}"
            logger.error(error_msg)
            raise TypeError(error_msg)
        
        logger.info(f"DEBUG: About to call fromisoformat with start_date_clean: {repr(start_date_clean)}")
        logger.info(f"DEBUG: About to call fromisoformat with end_date_clean: {repr(end_date_clean)}")
        
        # Now call fromisoformat - it MUST receive a string at this point
        start_date_dt = datetime.fromisoformat(start_date_clean)
        logger.info(f"DEBUG: Successfully parsed start_date_dt: {start_date_dt}")
        
        end_date_dt = datetime.fromisoformat(end_date_clean)
        logger.info(f"DEBUG: Successfully parsed end_date_dt: {end_date_dt}")
        
        if start_date_dt.tzinfo is None:
            start_date_dt = start_date_dt.replace(tzinfo=timezone.utc)
        else:
            start_date_dt = start_date_dt.astimezone(timezone.utc)
            
        if end_date_dt.tzinfo is None:
            end_date_dt = end_date_dt.replace(tzinfo=timezone.utc)
        else:
            end_date_dt = end_date_dt.astimezone(timezone.utc)
            
        logger.info(f"DEBUG: Final dates - start_date_dt: {start_date_dt}, end_date_dt: {end_date_dt}")
    except TypeError as e:
        logger.error(f"DEBUG: TypeError caught: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Type error parsing dates: {str(e)}")
    except ValueError as e:
        logger.error(f"DEBUG: ValueError caught: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        logger.error(f"DEBUG: Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error parsing dates: {str(e)}")
    
    logger.info("DEBUG: Date parsing completed successfully")
    logger.info("=" * 80)
    
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    cache_key = report_cache_key(
        "attendance_daily", effective_company_id, effective_branch_id,
        start_date_dt.isoformat(), end_date_dt.isoformat()
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # Log date values before query
    logger.info(f"DEBUG: About to execute query with start_date_dt: {start_date_dt} (type: {type(start_date_dt)})")
    logger.info(f"DEBUG: About to execute query with end_date_dt: {end_date_dt} (type: {type(end_date_dt)})")
    
    try:
        # Use func.date() instead of cast() to avoid SQLAlchemy datetime conversion issues
        query = db.query(
            func.date(Attendance.attendance_date).label("date"),
            func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.PRESENT).label("present_count"),
            func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.ABSENT).label("absent_count"),
            func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.LEAVE).label("leave_count"),
            func.count(Attendance.id).filter(Attendance.status == AttendanceStatusEnum.HALF_DAY).label("half_day_count"),
            func.count(Attendance.id).label("total_count")
        ).join(
            Staff, Attendance.staff_id == Staff.id
        ).filter(
            Staff.is_active == True,
            Attendance.attendance_date >= start_date_dt,
            Attendance.attendance_date <= end_date_dt
        )
        if effective_company_id is not None:
            query = query.filter(Staff.company_id == effective_company_id)
        if effective_branch_id is not None:
            query = query.filter(Staff.branch_id == effective_branch_id)
        
        logger.info(f"DEBUG: Query constructed, about to execute...")
        logger.info(f"DEBUG: Query SQL: {str(query)}")
        
        results = query.group_by(func.date(Attendance.attendance_date)).order_by("date").all()
        logger.info(f"DEBUG: Query executed successfully, got {len(results)} results")
        
        # Process results with error handling
        logger.info("DEBUG: Starting to process results...")
        data = []
        for idx, r in enumerate(results):
            try:
                logger.debug(f"DEBUG: Processing result {idx}: date={r.date}, present_count={r.present_count}")
                date_str = r.date.isoformat() if r.date else None
                data.append({
                    "date": date_str,
                    "present_count": r.present_count or 0,
                    "absent_count": r.absent_count or 0,
                    "leave_count": r.leave_count or 0,
                    "half_day_count": r.half_day_count or 0,
                    "total_count": r.total_count or 0
                })
            except Exception as e:
                logger.error(f"DEBUG: Error processing result {idx}: {e}", exc_info=True)
                logger.error(f"DEBUG: Result object: {r}, date type: {type(r.date) if r else 'None'}")
                # Skip this result and continue
                continue
        
        logger.info(f"DEBUG: Processed {len(data)} results successfully")
    except Exception as e:
        logger.error(f"DEBUG: Query execution failed: {e}", exc_info=True)
        logger.error(f"DEBUG: start_date_dt type: {type(start_date_dt)}, value: {start_date_dt}")
        logger.error(f"DEBUG: end_date_dt type: {type(end_date_dt)}, value: {end_date_dt}")
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")
    cache_set(cache_key, data, ttl_seconds=CACHE_TTL_SHORT)
    return data


@router.get("/customers/analysis")
async def get_customer_analysis(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get customer analysis (cached 2 min when Redis available)"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    cache_key = report_cache_key(
        "customers_analysis", effective_company_id, effective_branch_id,
        start_date.isoformat(), end_date.isoformat()
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # Use enum values for comparison
    completed_value = AppointmentStatusEnum.COMPLETED.value  # "completed"
    cancelled_value = AppointmentStatusEnum.CANCELLED.value  # "cancelled"
    no_show_value = AppointmentStatusEnum.NO_SHOW.value  # "no_show"
    scheduled_value = AppointmentStatusEnum.SCHEDULED.value  # "scheduled"
    
    # Base query: Get customers with appointments in date range
    base_query = db.query(
        Customer.id,
        Customer.name,
        Customer.phone,
        Customer.email,
        Customer.last_visit,
        func.count(Appointment.id).label("total_appointments"),
        func.sum(case((cast(Appointment.status, String) == completed_value, 1), else_=0)).label("completed"),
        func.sum(case((cast(Appointment.status, String) == cancelled_value, 1), else_=0)).label("cancelled"),
        func.sum(case((cast(Appointment.status, String) == no_show_value, 1), else_=0)).label("no_show"),
        func.sum(case((cast(Appointment.status, String) == scheduled_value, 1), else_=0)).label("scheduled")
    ).join(
        Appointment, Customer.id == Appointment.customer_id
    ).filter(
        Appointment.appointment_date >= start_date,
        Appointment.appointment_date <= end_date
    )
    if effective_company_id is not None:
        base_query = base_query.filter(
            Customer.company_id == effective_company_id,
            Appointment.company_id == effective_company_id
        )
    if effective_branch_id is not None:
        base_query = base_query.filter(
            Customer.branch_id == effective_branch_id,
            Appointment.branch_id == effective_branch_id
        )
    
    # Group by customer and get appointment counts
    customer_stats = base_query.group_by(
        Customer.id, Customer.name, Customer.phone, Customer.email, Customer.last_visit
    ).having(func.count(Appointment.id) > 0).all()
    
    # Get invoice totals for customers
    customer_ids = [c.id for c in customer_stats]
    invoice_totals = {}
    
    if customer_ids:
        invoice_query = db.query(
            Invoice.customer_id,
            func.sum(Invoice.total_amount).label("total_spent")
        ).join(
            Customer, Invoice.customer_id == Customer.id
        ).filter(
            Invoice.customer_id.in_(customer_ids),
            Invoice.invoice_date >= start_date,
            Invoice.invoice_date <= end_date,
            Invoice.status != InvoiceStatusEnum.VOID,
            Invoice.status != InvoiceStatusEnum.REFUNDED
        )
        if effective_company_id is not None:
            invoice_query = invoice_query.filter(Customer.company_id == effective_company_id)
        if effective_branch_id is not None:
            invoice_query = invoice_query.filter(Invoice.branch_id == effective_branch_id)
        
        invoice_results = invoice_query.group_by(Invoice.customer_id).all()
        invoice_totals = {r.customer_id: float(r.total_spent or 0) for r in invoice_results}
    
    # Get completed appointment dates for each customer to calculate avg days between visits
    customer_visit_dates = {}
    if customer_ids:
        visit_dates_query = db.query(
            Appointment.customer_id,
            Appointment.appointment_date
        ).filter(
            Appointment.customer_id.in_(customer_ids),
            Appointment.appointment_date >= start_date,
            Appointment.appointment_date <= end_date,
            cast(Appointment.status, String) == completed_value
        )
        if effective_company_id is not None:
            visit_dates_query = visit_dates_query.filter(Appointment.company_id == effective_company_id)
        if effective_branch_id is not None:
            visit_dates_query = visit_dates_query.filter(Appointment.branch_id == effective_branch_id)
        
        visit_dates_results = visit_dates_query.all()
        for result in visit_dates_results:
            if result.customer_id not in customer_visit_dates:
                customer_visit_dates[result.customer_id] = []
            customer_visit_dates[result.customer_id].append(result.appointment_date)
    
    # Build customer analysis results
    customer_analysis = []
    for stat in customer_stats:
        total_appointments = stat.total_appointments or 0
        completed = int(stat.completed or 0)
        cancelled = int(stat.cancelled or 0)
        no_show = int(stat.no_show or 0)
        scheduled = int(stat.scheduled or 0)
        
        # Calculate avg days between visits
        avg_days_between_visits = None
        if stat.id in customer_visit_dates:
            visit_dates = sorted(customer_visit_dates[stat.id])
            if len(visit_dates) > 1:
                total_days = sum(
                    (visit_dates[i] - visit_dates[i-1]).days 
                    for i in range(1, len(visit_dates))
                )
                avg_days_between_visits = round(total_days / (len(visit_dates) - 1), 1)
        
        customer_analysis.append({
            "customer_id": stat.id,
            "customer_name": stat.name,
            "phone": stat.phone,
            "email": stat.email,
            "total_appointments": total_appointments,
            "completed_appointments": completed,
            "cancelled_appointments": cancelled,
            "no_show_appointments": no_show,
            "scheduled_appointments": scheduled,
            "cancellation_rate": round((cancelled / total_appointments * 100), 2) if total_appointments > 0 else 0,
            "completion_rate": round((completed / total_appointments * 100), 2) if total_appointments > 0 else 0,
            "avg_days_between_visits": avg_days_between_visits,
            "total_spent": invoice_totals.get(stat.id, 0.0),
            "last_visit": stat.last_visit.isoformat() if stat.last_visit else None
        })
    
    cache_set(cache_key, customer_analysis, ttl_seconds=CACHE_TTL_SHORT)
    return customer_analysis


@router.get("/customers/visit-frequency")
async def get_customer_visit_frequency(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get customer visit frequency distribution"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    completed_value = AppointmentStatusEnum.COMPLETED.value  # "completed"
    
    query = db.query(
        Customer.id,
        Customer.name,
        func.count(Appointment.id).filter(
            cast(Appointment.status, String) == completed_value
        ).label("visit_count")
    ).join(
        Appointment, Customer.id == Appointment.customer_id
    ).filter(
        Appointment.appointment_date >= start_date,
        Appointment.appointment_date <= end_date,
        cast(Appointment.status, String) == completed_value
    )
    if effective_company_id is not None:
        query = query.filter(
            Customer.company_id == effective_company_id,
            Appointment.company_id == effective_company_id
        )
    if effective_branch_id is not None:
        query = query.filter(Customer.branch_id == effective_branch_id)
    
    results = query.group_by(Customer.id, Customer.name).order_by(func.count(Appointment.id).desc()).all()
    
    return [
        {
            "customer_id": r.id,
            "customer_name": r.name,
            "visit_count": r.visit_count or 0
        }
        for r in results
    ]


@router.get("/customers/cancellation-frequency")
async def get_customer_cancellation_frequency(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get customer cancellation frequency"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    cancelled_value = AppointmentStatusEnum.CANCELLED.value  # "cancelled"
    
    cancellation_expr = func.sum(
        case(
            (cast(Appointment.status, String) == cancelled_value, 1),
            else_=0
        )
    )
    
    query = db.query(
        Customer.id,
        Customer.name,
        cancellation_expr.label("cancellation_count"),
        func.count(Appointment.id).label("total_appointments")
    ).join(
        Appointment, Customer.id == Appointment.customer_id
    ).filter(
        Appointment.appointment_date >= start_date,
        Appointment.appointment_date <= end_date
    )
    if effective_company_id is not None:
        query = query.filter(
            Customer.company_id == effective_company_id,
            Appointment.company_id == effective_company_id
        )
    if effective_branch_id is not None:
        query = query.filter(Customer.branch_id == effective_branch_id)
    
    results = query.group_by(Customer.id, Customer.name).having(
        cancellation_expr > 0
    ).order_by(cancellation_expr.desc()).all()
    
    return [
        {
            "customer_id": r.id,
            "customer_name": r.name,
            "cancellation_count": int(r.cancellation_count or 0),
            "total_appointments": r.total_appointments or 0,
            "cancellation_rate": round((int(r.cancellation_count or 0) / (r.total_appointments or 1)) * 100, 2)
        }
        for r in results
    ]


def extract_state_code_from_gstin(gstin: Optional[str]) -> Optional[str]:
    """Extract state code from GSTIN (first 2 digits)"""
    if gstin and len(gstin) >= 2:
        return gstin[:2]
    return None


def get_financial_year(date: datetime) -> str:
    """Get financial year in format YYYY-YY"""
    if date.month >= 4:
        return f"{date.year}-{str(date.year + 1)[2:]}"
    else:
        return f"{date.year - 1}-{str(date.year)[2:]}"


@router.get("/gst-audit")
async def get_gst_audit_export(
    request: Request,
    branch_id: Optional[int] = None,
    branch_ids: Optional[str] = None,  # Comma-separated list of branch IDs
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get GST audit export data for tax purposes"""
    start_date, end_date = _parse_report_dates(request)
    effective_company_id = get_effective_company_id(current_user)
    # Parse branch_ids if provided
    branch_id_list = None
    if branch_ids:
        try:
            branch_id_list = [int(bid.strip()) for bid in branch_ids.split(',') if bid.strip()]
        except ValueError:
            branch_id_list = None
    
    # Get effective branch_id based on role
    effective_branch_id = None
    if not current_user.is_superuser and current_user.role != RoleEnum.OWNER:
        effective_branch_id = current_user.branch_id
    elif branch_id is not None:
        effective_branch_id = branch_id
    
    # Query invoices with all related data
    query = db.query(Invoice).options(
        joinedload(Invoice.branch),
        joinedload(Invoice.customer),
        joinedload(Invoice.items).joinedload(InvoiceItem.service),
        joinedload(Invoice.items).joinedload(InvoiceItem.product),
        joinedload(Invoice.items).joinedload(InvoiceItem.staff),
        joinedload(Invoice.payments)
    ).filter(
        Invoice.invoice_date >= start_date,
        Invoice.invoice_date <= end_date,
        Invoice.status != InvoiceStatusEnum.VOID
    )
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    if branch_id_list and len(branch_id_list) > 0:
        query = query.filter(Invoice.branch_id.in_(branch_id_list))
    elif effective_branch_id is not None:
        query = query.filter(Invoice.branch_id == effective_branch_id)
    
    invoices = query.order_by(Invoice.invoice_date, Invoice.invoice_number).all()
    
    # Get company and user info (for super admin, company is per-invoice from branch)
    company = db.query(Company).filter(Company.id == effective_company_id).first() if effective_company_id else None
    user_map = {}
    if effective_company_id is not None:
        users = db.query(User).filter(User.company_id == effective_company_id).all()
    else:
        users = db.query(User).filter(User.is_superuser == False, User.company_id.isnot(None)).all()
    for u in users:
        user_map[u.id] = u.full_name
    
    # Build export data
    export_data = []
    
    for invoice in invoices:
        branch = invoice.branch
        customer = invoice.customer
        # Get company from branch relationship or use the already fetched company
        invoice_company = branch.company if branch and branch.company else company
        
        # Get branch state code from model or extract from GSTIN
        branch_state_code = branch.state_code if branch and branch.state_code else (
            extract_state_code_from_gstin(branch.gstin) if branch and branch.gstin else None
        )
        customer_state_code = None  # Not stored in customer model
        
        # Determine invoice type (simplified - can be enhanced)
        invoice_type = "Tax Invoice" if branch and branch.gstin else "Bill of Supply"
        
        # Get place of supply from company model or use branch state
        place_of_supply = invoice_company.place_of_supply if invoice_company and invoice_company.place_of_supply else (
            branch.state if branch and branch.state else None
        )
        place_of_supply_state_code = invoice_company.state_code if invoice_company and invoice_company.state_code else branch_state_code
        
        # Calculate totals
        total_taxable_amount = float(invoice.subtotal or 0)
        total_cgst = 0.0
        total_sgst = 0.0
        total_gst = float(invoice.tax_amount or 0)
        round_off = float(invoice.total_amount or 0) - (total_taxable_amount + total_gst - float(invoice.discount_amount or 0))
        
        # Calculate CGST and SGST (assuming equal split for same state)
        if total_gst > 0:
            total_cgst = total_gst / 2
            total_sgst = total_gst / 2
        
        # Get payment details
        payment_mode = None
        payment_status = invoice.status.value if invoice.status else "Pending"
        payment_date = None
        if invoice.payments:
            latest_payment = max(invoice.payments, key=lambda p: p.created_at)
            payment_mode = latest_payment.payment_mode.value if latest_payment.payment_mode else None
            payment_date = latest_payment.created_at.isoformat() if latest_payment.created_at else None
        
        # Get creator info
        creator_name = user_map.get(invoice.created_by, "Unknown")
        
        # Process each invoice item
        for item in invoice.items:
            # Calculate item-level CGST and SGST
            item_taxable_value = float(item.unit_price or 0) * (item.quantity or 1) - float(item.discount_amount or 0)
            item_cgst = 0.0
            item_sgst = 0.0
            if item.tax_amount and item.tax_amount > 0:
                item_cgst = float(item.tax_amount) / 2
                item_sgst = float(item.tax_amount) / 2
            
            # Determine item type
            item_type = "Service" if item.service_id else "Product"
            
            # Get HSN code from invoice item, fallback to service/product if not available
            hsn_sac_code = item.hsn_sac_code
            if not hsn_sac_code:
                if item.service and item.service.hsn_sac_code:
                    hsn_sac_code = item.service.hsn_sac_code
                elif item.product and item.product.hsn_sac_code:
                    hsn_sac_code = item.product.hsn_sac_code
            
            # Check if invoice is refunded
            is_refunded = invoice.status == InvoiceStatusEnum.REFUNDED
            
            # Format invoice created date (date only, not timestamp)
            invoice_created_date = None
            if invoice.created_at:
                invoice_created_date = invoice.created_at.date().isoformat()
            
            # Build row data
            row = {
                # Invoice Details
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                "financial_year": get_financial_year(invoice.invoice_date) if invoice.invoice_date else None,
                "invoice_type": invoice_type,
                "is_refunded": "Yes" if is_refunded else "No",
                "place_of_supply": place_of_supply or (branch.name if branch else "N/A"),
                "place_of_supply_state_code": place_of_supply_state_code or "N/A",
                
                # Seller (Salon / Branch) Details
                "salon_name": invoice_company.name if invoice_company else company.name if company else "N/A",
                "branch_name": branch.name if branch else "N/A",
                "branch_address": branch.address if branch else "N/A",
                "branch_state": branch.state if branch and branch.state else "N/A",
                "branch_state_code": branch_state_code or "N/A",
                "branch_gstin": branch.gstin if branch and branch.gstin else "NA",
                "branch_phone": branch.phone if branch else "N/A",
                
                # Customer Details
                "customer_name": customer.name if customer else "Walk-in Customer",
                
                # Line Item Details
                "item_name": item.description,
                "item_type": item_type,
                "hsn_sac_code": hsn_sac_code or "N/A",
                "quantity": item.quantity or 1,
                "unit_price": float(item.unit_price or 0),
                "discount_amount": float(item.discount_amount or 0),
                "taxable_value": item_taxable_value,
                "gst_rate": float(item.tax_rate or 0),
                "cgst_amount": item_cgst,
                "sgst_amount": item_sgst,
                
                # Invoice Totals
                "total_taxable_amount": total_taxable_amount,
                "total_cgst": total_cgst,
                "total_sgst": total_sgst,
                "total_gst": total_gst,
                "grand_total": float(invoice.total_amount or 0),
                
                # Payment Details
                "payment_mode": payment_mode or "N/A",
                "payment_status": payment_status,
                "payment_date": payment_date or (invoice.invoice_date.isoformat() if invoice.invoice_date else None),
                
                # Internal / Audit Fields
                "invoice_created_by": creator_name,
                "invoice_created_date": invoice_created_date,
            }
            
            export_data.append(row)
    
    return export_data
