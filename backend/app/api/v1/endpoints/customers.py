from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.models.user import User
from app.models.customer import Customer
from app.models.membership import Membership
from app.api.v1.endpoints.auth import get_current_user, get_effective_company_id
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerResponse

router = APIRouter()


@router.post("/", response_model=CustomerResponse, status_code=201)
async def create_customer(
    customer: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new customer"""
    # Check if customer with phone already exists
    existing = db.query(Customer).filter(
        Customer.phone == customer.phone,
        Customer.company_id == current_user.company_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Customer with this phone already exists")
    
    branch_id = customer.branch_id or current_user.branch_id
    
    # Validate membership if provided
    membership = None
    if customer.membership_id:
        membership = db.query(Membership).filter(
            Membership.id == customer.membership_id,
            Membership.company_id == current_user.company_id,
            Membership.branch_id == branch_id
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found or does not belong to the selected branch")
        if not membership.is_active:
            raise HTTPException(status_code=400, detail="Membership is not active")
    
    customer_data = customer.dict(exclude={'branch_id'})
    db_customer = Customer(
        company_id=current_user.company_id,
        branch_id=branch_id,
        **customer_data
    )
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    
    # Reload with membership relationship
    db_customer = db.query(Customer).options(
        joinedload(Customer.membership)
    ).filter(Customer.id == db_customer.id).first()
    
    return CustomerResponse(
        id=db_customer.id,
        name=db_customer.name,
        phone=db_customer.phone,
        email=db_customer.email,
        address=db_customer.address,
        membership_id=db_customer.membership_id,
        membership_name=db_customer.membership.name if db_customer.membership else None,
        membership_is_active=db_customer.membership.is_active if db_customer.membership else None,
        total_visits=db_customer.total_visits,
        total_spent=db_customer.total_spent,
        last_visit=db_customer.last_visit,
        created_at=db_customer.created_at
    )


@router.get("/", response_model=List[CustomerResponse])
async def list_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    search: Optional[str] = None,
    phone: Optional[str] = None,  # Keep for backward compatibility
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List customers with search by name or phone"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Customer).options(joinedload(Customer.membership))
    if effective_company_id is not None:
        query = query.filter(Customer.company_id == effective_company_id)
    
    # Support both 'search' and 'phone' parameters for backward compatibility
    search_term = search or phone
    if search_term:
        query = query.filter(
            (Customer.phone.contains(search_term)) | 
            (Customer.name.ilike(f"%{search_term}%"))
        )
    
    customers = query.order_by(Customer.name).offset(skip).limit(limit).all()
    
    # Convert to response format with membership name and active status
    return [
        CustomerResponse(
            id=c.id,
            name=c.name,
            phone=c.phone,
            email=c.email,
            address=c.address,
            membership_id=c.membership_id,
            membership_name=c.membership.name if c.membership else None,
            membership_is_active=c.membership.is_active if c.membership else None,
            total_visits=c.total_visits,
            total_spent=c.total_spent,
            last_visit=c.last_visit,
            created_at=c.created_at
        )
        for c in customers
    ]


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get customer by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Customer).options(joinedload(Customer.membership)).filter(Customer.id == customer_id)
    if effective_company_id is not None:
        query = query.filter(Customer.company_id == effective_company_id)
    customer = query.first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    return CustomerResponse(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        membership_id=customer.membership_id,
        membership_name=customer.membership.name if customer.membership else None,
        membership_is_active=customer.membership.is_active if customer.membership else None,
        total_visits=customer.total_visits,
        total_spent=customer.total_spent,
        last_visit=customer.last_visit,
        created_at=customer.created_at
    )


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    customer_update: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update customer"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Customer).filter(Customer.id == customer_id)
    if effective_company_id is not None:
        query = query.filter(Customer.company_id == effective_company_id)
    customer = query.first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    # Validate membership if being updated
    if customer_update.membership_id is not None:
        if customer_update.membership_id:
            mq = db.query(Membership).filter(
                Membership.id == customer_update.membership_id,
                Membership.is_active == True
            )
            if effective_company_id is not None:
                mq = mq.filter(Membership.company_id == effective_company_id)
            membership = mq.first()
            if not membership:
                raise HTTPException(status_code=404, detail="Membership not found")
            if not membership.is_active:
                raise HTTPException(status_code=400, detail="Membership is not active")
    
    update_data = customer_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)
    
    db.commit()
    db.refresh(customer)
    
    # Reload with membership relationship
    customer = db.query(Customer).options(
        joinedload(Customer.membership)
    ).filter(Customer.id == customer_id).first()
    
    return CustomerResponse(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        email=customer.email,
        address=customer.address,
        membership_id=customer.membership_id,
        membership_name=customer.membership.name if customer.membership else None,
        membership_is_active=customer.membership.is_active if customer.membership else None,
        total_visits=customer.total_visits,
        total_spent=customer.total_spent,
        last_visit=customer.last_visit,
        created_at=customer.created_at
    )


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete customer"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Customer).filter(Customer.id == customer_id)
    if effective_company_id is not None:
        query = query.filter(Customer.company_id == effective_company_id)
    customer = query.first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Check if customer has invoices or appointments
    if customer.invoices:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete customer with existing invoices. Please delete invoices first."
        )
    
    if customer.appointments:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete customer with existing appointments. Please delete appointments first."
        )
    
    db.delete(customer)
    db.commit()
    return None
