from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from app.models.invoice import PaymentModeEnum, InvoiceStatusEnum


class InvoiceItemCreate(BaseModel):
    service_id: Optional[int] = None
    product_id: Optional[int] = None
    staff_id: Optional[int] = None
    description: str
    quantity: int = 1
    unit_price: Decimal
    discount_amount: Decimal = Decimal("0.00")
    tax_rate: Decimal
    hsn_sac_code: Optional[str] = None


class PaymentCreate(BaseModel):
    amount: Decimal
    payment_mode: PaymentModeEnum
    transaction_id: Optional[str] = None
    notes: Optional[str] = None


class InvoiceCreate(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None  # For walk-in customers
    customer_phone: Optional[str] = None  # For walk-in customers
    appointment_id: Optional[int] = None
    invoice_date: Optional[datetime] = None
    items: List[InvoiceItemCreate]
    discount_amount: Decimal = Decimal("0.00")
    payments: List[PaymentCreate]
    notes: Optional[str] = None
    branch_id: Optional[int] = None


class InvoiceItemResponse(BaseModel):
    id: int
    description: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    hsn_sac_code: Optional[str]

    class Config:
        from_attributes = True


class PaymentResponse(BaseModel):
    id: int
    amount: Decimal
    payment_mode: PaymentModeEnum
    transaction_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str
    invoice_date: datetime
    customer_id: Optional[int]
    customer_name: Optional[str] = None
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    status: InvoiceStatusEnum
    items: List[InvoiceItemResponse]
    payments: List[PaymentResponse]
    created_at: datetime

    class Config:
        from_attributes = True
