from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.models.user import User
from app.models.invoice import Invoice, InvoiceItem, Payment, InvoiceStatusEnum
from app.models.customer import Customer
from app.models.membership import Membership
from app.api.v1.endpoints.auth import get_current_user, get_effective_branch_id, get_effective_company_id
from app.schemas.invoice import InvoiceCreate, InvoiceResponse, InvoiceItemResponse, PaymentResponse
from app.services.invoice_service import generate_invoice_number, calculate_gst
from app.services.sms_service import send_invoice_sms, send_invoice_sms_async
from app.core.config import settings

router = APIRouter()


@router.post("/", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    invoice: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new invoice"""
    from app.models.company import Branch
    
    # Determine branch_id
    branch_id = invoice.branch_id or current_user.branch_id
    
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
        Branch.company_id == current_user.company_id,
        Branch.is_active == True
    ).first()
    if not branch:
        raise HTTPException(status_code=403, detail="Branch not found, inactive, or access denied")
    
    # Handle walk-in customer: create customer if name and phone provided
    customer_id = invoice.customer_id
    if not customer_id and invoice.customer_name and invoice.customer_phone:
        # Check if customer with phone already exists
        existing_customer = db.query(Customer).filter(
            Customer.phone == invoice.customer_phone,
            Customer.company_id == current_user.company_id
        ).first()
        
        if existing_customer:
            customer_id = existing_customer.id
        else:
            # Create new walk-in customer
            new_customer = Customer(
                company_id=current_user.company_id,
                branch_id=branch_id,
                name=invoice.customer_name,
                phone=invoice.customer_phone
            )
            db.add(new_customer)
            db.flush()
            customer_id = new_customer.id
    
    if not customer_id:
        raise HTTPException(status_code=400, detail="Customer name and phone are required")
    
    # Get customer with membership
    db_customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Generate invoice number
    invoice_number = generate_invoice_number(db, current_user.company_id, branch_id)
    
    # Calculate totals
    subtotal = Decimal("0.00")
    total_tax = Decimal("0.00")
    
    for item in invoice.items:
        item_subtotal = item.unit_price * item.quantity - item.discount_amount
        item_tax = item_subtotal * (item.tax_rate / Decimal("100"))
        total_tax += item_tax
        subtotal += item_subtotal
    
    # Calculate membership discount if customer has active membership
    membership_discount = Decimal("0.00")
    if db_customer.membership_id:
        db_membership = db.query(Membership).filter(
            Membership.id == db_customer.membership_id,
            Membership.is_active == True
        ).first()
        
        if db_membership:
            # Apply membership discount percentage to subtotal
            membership_discount = subtotal * (db_membership.discount_percentage / Decimal("100"))
    
    # Total discount = manual discount + membership discount
    total_discount = invoice.discount_amount + membership_discount
    total_amount = subtotal + total_tax - total_discount
    paid_amount = sum(p.amount for p in invoice.payments)
    
    # Determine status
    if paid_amount >= total_amount:
        status = InvoiceStatusEnum.PAID
    elif paid_amount > 0:
        status = InvoiceStatusEnum.PARTIAL
    else:
        status = InvoiceStatusEnum.PENDING
    
    # Create invoice
    db_invoice = Invoice(
        company_id=current_user.company_id,
        branch_id=branch_id,
        customer_id=customer_id,
        appointment_id=invoice.appointment_id,
        invoice_number=invoice_number,
        invoice_date=invoice.invoice_date or datetime.utcnow(),
        subtotal=subtotal,
        discount_amount=total_discount,  # Include membership discount
        tax_amount=total_tax,
        total_amount=total_amount,
        paid_amount=paid_amount,
        status=status,
        notes=invoice.notes,
        created_by=current_user.id
    )
    db.add(db_invoice)
    db.flush()
    
    # Create invoice items
    for item in invoice.items:
        item_subtotal = item.unit_price * item.quantity - item.discount_amount
        item_tax = item_subtotal * (item.tax_rate / Decimal("100"))
        item_total = item_subtotal + item_tax
        
        db_item = InvoiceItem(
            invoice_id=db_invoice.id,
            service_id=item.service_id,
            product_id=item.product_id,
            staff_id=item.staff_id,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount_amount=item.discount_amount,
            tax_rate=item.tax_rate,
            tax_amount=item_tax,
            total_amount=item_total,
            hsn_sac_code=item.hsn_sac_code
        )
        db.add(db_item)
    
    # Create payments
    for payment in invoice.payments:
        db_payment = Payment(
            invoice_id=db_invoice.id,
            amount=payment.amount,
            payment_mode=payment.payment_mode,
            transaction_id=payment.transaction_id,
            notes=payment.notes,
            created_by=current_user.id
        )
        db.add(db_payment)
    
    # Commit transaction with error handling
    from app.core.db_transaction import safe_commit
    from app.core.logging_config import get_logger
    
    logger = get_logger("invoices")
    if not safe_commit(db, "create_invoice"):
        logger.error("Failed to create invoice", extra={
            "user_id": current_user.id,
            "company_id": current_user.company_id,
            "branch_id": branch_id,
        })
        raise HTTPException(
            status_code=500,
            detail="Failed to create invoice. Please try again."
        )
    
    # Reload invoice with all relationships
    db_invoice = db.query(Invoice).filter(Invoice.id == db_invoice.id).options(
        joinedload(Invoice.customer),
        joinedload(Invoice.items),
        joinedload(Invoice.payments)
    ).first()
    
    # Send SMS notification to customer (async via Celery if enabled, else sync)
    if db_invoice and db_invoice.customer_id and db_invoice.customer:
        try:
            if settings.USE_CELERY_FOR_SMS:
                send_invoice_sms_async(db_invoice.id)
            else:
                send_invoice_sms(db_invoice, db)
        except Exception as e:
            # Log error but don't fail invoice creation
            from app.core.logging_config import get_logger
            logger = get_logger("invoices")
            logger.warning(
                f"Failed to send invoice SMS for invoice {db_invoice.id}",
                exc_info=True,
                extra={
                    "invoice_id": db_invoice.id,
                    "invoice_number": db_invoice.invoice_number,
                    "customer_id": db_invoice.customer_id,
                    "error": str(e)
                }
            )
    
    # Manually construct InvoiceResponse with customer_name
    return InvoiceResponse(
        id=db_invoice.id,
        invoice_number=db_invoice.invoice_number,
        invoice_date=db_invoice.invoice_date,
        customer_id=db_invoice.customer_id,
        customer_name=db_invoice.customer.name if db_invoice.customer else None,
        subtotal=db_invoice.subtotal,
        discount_amount=db_invoice.discount_amount,
        tax_amount=db_invoice.tax_amount,
        total_amount=db_invoice.total_amount,
        paid_amount=db_invoice.paid_amount,
        status=db_invoice.status,
        items=[InvoiceItemResponse.model_validate(item) for item in db_invoice.items],
        payments=[PaymentResponse.model_validate(payment) for payment in db_invoice.payments],
        created_at=db_invoice.created_at
    )


@router.get("/", response_model=List[InvoiceResponse])
async def list_invoices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    customer_id: Optional[int] = None,
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List invoices"""
    effective_company_id = get_effective_company_id(current_user)
    effective_branch_id = get_effective_branch_id(current_user, branch_id)
    
    query = db.query(Invoice)
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    if effective_branch_id is not None:
        query = query.filter(Invoice.branch_id == effective_branch_id)
    
    if start_date:
        query = query.filter(Invoice.invoice_date >= start_date)
    if end_date:
        query = query.filter(Invoice.invoice_date <= end_date)
    if customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    
    invoices = query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.items),
        joinedload(Invoice.payments)
    ).order_by(Invoice.invoice_date.desc()).offset(skip).limit(limit).all()
    
    # Manually construct InvoiceResponse with customer_name
    return [
        InvoiceResponse(
            id=inv.id,
            invoice_number=inv.invoice_number,
            invoice_date=inv.invoice_date,
            customer_id=inv.customer_id,
            customer_name=inv.customer.name if inv.customer else None,
            subtotal=inv.subtotal,
            discount_amount=inv.discount_amount,
            tax_amount=inv.tax_amount,
            total_amount=inv.total_amount,
            paid_amount=inv.paid_amount,
            status=inv.status,
            items=[InvoiceItemResponse.model_validate(item) for item in inv.items],
            payments=[PaymentResponse.model_validate(payment) for payment in inv.payments],
            created_at=inv.created_at
        )
        for inv in invoices
    ]


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get invoice by ID"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Invoice).filter(Invoice.id == invoice_id)
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    invoice = query.options(
        joinedload(Invoice.customer),
        joinedload(Invoice.items),
        joinedload(Invoice.payments)
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Manually construct InvoiceResponse with customer_name
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        customer_id=invoice.customer_id,
        customer_name=invoice.customer.name if invoice.customer else None,
        subtotal=invoice.subtotal,
        discount_amount=invoice.discount_amount,
        tax_amount=invoice.tax_amount,
        total_amount=invoice.total_amount,
        paid_amount=invoice.paid_amount,
        status=invoice.status,
        items=[InvoiceItemResponse.model_validate(item) for item in invoice.items],
        payments=[PaymentResponse.model_validate(payment) for payment in invoice.payments],
        created_at=invoice.created_at
    )


@router.post("/{invoice_id}/refund", response_model=InvoiceResponse)
async def refund_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Refund an invoice"""
    effective_company_id = get_effective_company_id(current_user)
    query = db.query(Invoice).filter(Invoice.id == invoice_id)
    if effective_company_id is not None:
        query = query.filter(Invoice.company_id == effective_company_id)
    invoice = query.first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Only allow refunding paid or partial invoices
    if invoice.status not in [InvoiceStatusEnum.PAID, InvoiceStatusEnum.PARTIAL]:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot refund invoice with status '{invoice.status}'. Only paid or partial invoices can be refunded."
        )
    
    # Check if already refunded
    if invoice.status == InvoiceStatusEnum.REFUNDED:
        raise HTTPException(status_code=400, detail="Invoice is already refunded")
    
    # Update invoice status to refunded
    invoice.status = InvoiceStatusEnum.REFUNDED
    
    try:
        db.commit()
        db.refresh(invoice)
        # Reload invoice with all relationships
        invoice = db.query(Invoice).filter(Invoice.id == invoice.id).options(
            joinedload(Invoice.customer),
            joinedload(Invoice.items),
            joinedload(Invoice.payments)
        ).first()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to refund invoice: {str(e)}")
    
    # Manually construct InvoiceResponse with customer_name
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        customer_id=invoice.customer_id,
        customer_name=invoice.customer.name if invoice.customer else None,
        subtotal=invoice.subtotal,
        discount_amount=invoice.discount_amount,
        tax_amount=invoice.tax_amount,
        total_amount=invoice.total_amount,
        paid_amount=invoice.paid_amount,
        status=invoice.status,
        items=[InvoiceItemResponse.model_validate(item) for item in invoice.items],
        payments=[PaymentResponse.model_validate(payment) for payment in invoice.payments],
        created_at=invoice.created_at
    )
