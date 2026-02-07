from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: Decimal
    duration_minutes: Optional[int] = 30
    hsn_sac_code: Optional[str] = None
    gst_rate_id: int  # Required field
    branch_id: Optional[int] = None


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    duration_minutes: Optional[int] = None
    hsn_sac_code: Optional[str] = None
    gst_rate_id: Optional[int] = None
    is_active: Optional[bool] = None


class GSTRateResponse(BaseModel):
    id: int
    name: str
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal

    class Config:
        from_attributes = True


class ServiceResponse(BaseModel):
    id: int
    company_id: int
    branch_id: int
    name: str
    description: Optional[str]
    price: Decimal
    duration_minutes: int
    hsn_sac_code: Optional[str]
    gst_rate_id: int
    gst_rate: Optional[GSTRateResponse] = None  # Include GST rate details
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
