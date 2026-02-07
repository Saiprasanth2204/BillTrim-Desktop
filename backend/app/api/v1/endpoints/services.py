from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.gst_rates import get_gst_rates, get_gst_rate_by_id
from app.models.user import User
from app.models.service import Service
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.service import ServiceCreate, ServiceUpdate, ServiceResponse, GSTRateResponse

router = APIRouter()


def _attach_gst_rate(service: Service) -> None:
    """Attach hardcoded GST rate to service for response serialization."""
    if service.gst_rate_id:
        rate = get_gst_rate_by_id(service.gst_rate_id)
        setattr(service, "gst_rate", rate)
    else:
        setattr(service, "gst_rate", None)


@router.post("/", response_model=ServiceResponse, status_code=201)
async def create_service(
    service: ServiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new service"""
    from app.models.company import Branch
    
    # Validate GST rate exists (hardcoded list)
    if service.gst_rate_id and not get_gst_rate_by_id(service.gst_rate_id):
        raise HTTPException(status_code=400, detail="Invalid GST rate ID")
    
    # Determine branch_id
    branch_id = service.branch_id or current_user.branch_id
    
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
    
    db_service = Service(
        company_id=current_user.company_id,
        branch_id=branch_id,
        name=service.name,
        description=service.description,
        price=service.price,
        duration_minutes=service.duration_minutes or 30,
        hsn_sac_code=service.hsn_sac_code,
        gst_rate_id=service.gst_rate_id
    )
    db.add(db_service)
    db.commit()
    db.refresh(db_service)
    _attach_gst_rate(db_service)
    return db_service


@router.get("/", response_model=List[ServiceResponse])
async def list_services(
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List services"""
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = db.query(Service).filter(Service.is_active == True)
    if effective_company_id is not None:
        query = query.filter(Service.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Service.branch_id == effective_branch_id)
    
    services = query.all()
    for s in services:
        _attach_gst_rate(s)
    return services


@router.get("/gst-rates", response_model=List[GSTRateResponse])
async def list_gst_rates(
    current_user: User = Depends(get_current_user)
):
    """List GST rates (hardcoded reference data)."""
    return get_gst_rates()


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get service by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Service).filter(Service.id == service_id)
    if effective_company_id is not None:
        query = query.filter(Service.company_id == effective_company_id)
    service = query.first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    _attach_gst_rate(service)
    return service


@router.put("/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: int,
    service_update: ServiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update service"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Service).filter(Service.id == service_id)
    if effective_company_id is not None:
        query = query.filter(Service.company_id == effective_company_id)
    service = query.first()
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Validate GST rate if being updated (hardcoded list)
    if service_update.gst_rate_id and not get_gst_rate_by_id(service_update.gst_rate_id):
        raise HTTPException(status_code=400, detail="Invalid GST rate ID")
    
    update_data = service_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(service, field, value)
    
    db.commit()
    db.refresh(service)
    _attach_gst_rate(service)
    return service


@router.delete("/{service_id}", status_code=204)
async def delete_service(
    service_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete service (soft delete by setting is_active=False)"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Service).filter(Service.id == service_id)
    if effective_company_id is not None:
        query = query.filter(Service.company_id == effective_company_id)
    service = query.first()
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Soft delete by setting is_active to False
    service.is_active = False
    db.commit()
    return None
