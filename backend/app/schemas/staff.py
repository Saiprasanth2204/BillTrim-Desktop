from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, time
from decimal import Decimal
from app.models.staff import StaffRoleEnum


class StaffWeekOffCreate(BaseModel):
    day_of_week: int  # 0=Monday, 6=Sunday


class StaffCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    role: StaffRoleEnum = StaffRoleEnum.STYLIST
    commission_percentage: Decimal = Decimal("0.00")
    branch_id: int
    week_offs: Optional[List[StaffWeekOffCreate]] = None
    standard_weekly_off: Optional[int] = None  # 0=Monday, 6=Sunday, None=no weekly off
    standard_in_time: Optional[time] = None  # Standard start time (e.g., 09:00)
    standard_out_time: Optional[time] = None  # Standard end time (e.g., 19:00)


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[StaffRoleEnum] = None
    commission_percentage: Optional[Decimal] = None
    is_active: Optional[bool] = None
    standard_weekly_off: Optional[int] = None  # 0=Monday, 6=Sunday, None=no weekly off
    standard_in_time: Optional[time] = None  # Standard start time (e.g., 09:00)
    standard_out_time: Optional[time] = None  # Standard end time (e.g., 19:00)


class StaffWeekOffResponse(BaseModel):
    id: int
    day_of_week: int
    is_active: bool

    class Config:
        from_attributes = True


class StaffResponse(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str]
    role: StaffRoleEnum
    commission_percentage: Decimal
    is_active: bool
    branch_id: int
    image_url: Optional[str] = None
    week_offs: List[StaffWeekOffResponse]
    standard_weekly_off: Optional[int] = None
    standard_in_time: Optional[time] = None
    standard_out_time: Optional[time] = None

    class Config:
        from_attributes = True
