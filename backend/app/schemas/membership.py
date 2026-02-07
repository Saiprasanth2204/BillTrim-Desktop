from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class MembershipCreate(BaseModel):
    name: str
    description: Optional[str] = None
    discount_percentage: Decimal
    is_active: bool = True
    branch_id: int


class MembershipUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    discount_percentage: Optional[Decimal] = None
    is_active: Optional[bool] = None
    branch_id: Optional[int] = None


class MembershipResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    discount_percentage: Decimal
    is_active: bool
    branch_id: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
