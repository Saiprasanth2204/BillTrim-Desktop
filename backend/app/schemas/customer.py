from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CustomerCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = None
    notes: Optional[str] = None
    branch_id: Optional[int] = None
    membership_id: Optional[int] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = None
    notes: Optional[str] = None
    membership_id: Optional[int] = None


class CustomerResponse(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str]
    address: Optional[str]
    membership_id: Optional[int]
    membership_name: Optional[str] = None
    membership_is_active: Optional[bool] = None  # False when membership has been deactivated
    total_visits: int
    total_spent: int
    last_visit: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
