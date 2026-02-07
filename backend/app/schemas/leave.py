from pydantic import BaseModel, model_validator, field_validator
from typing import Optional
from datetime import datetime, timezone


class StaffLeaveCreate(BaseModel):
    staff_id: int
    leave_date: Optional[datetime] = None  # Kept for backward compatibility
    leave_from: datetime
    leave_to: datetime
    reason: Optional[str] = None
    is_planned: bool = True
    is_approved: bool = False

    @field_validator('leave_from', 'leave_to', mode='before')
    @classmethod
    def ensure_utc_timezone(cls, v):
        """Ensure datetime is timezone-aware and in UTC"""
        if isinstance(v, datetime):
            if v.tzinfo is None:
                # Naive datetime - assume it's UTC (from ISO string with Z)
                return v.replace(tzinfo=timezone.utc)
            elif v.tzinfo != timezone.utc:
                # Convert to UTC
                return v.astimezone(timezone.utc)
        return v

    @model_validator(mode='after')
    def validate_leave_dates(self):
        if self.leave_to < self.leave_from:
            raise ValueError('leave_to must be greater than or equal to leave_from')
        return self


class StaffLeaveUpdate(BaseModel):
    leave_date: Optional[datetime] = None
    leave_from: Optional[datetime] = None
    leave_to: Optional[datetime] = None
    reason: Optional[str] = None
    is_planned: Optional[bool] = None
    is_approved: Optional[bool] = None


class StaffLeaveResponse(BaseModel):
    id: int
    staff_id: int
    staff_name: Optional[str] = None  # Denormalized for display when staff is deleted/inactive
    leave_date: datetime
    leave_from: Optional[datetime] = None
    leave_to: Optional[datetime] = None
    reason: Optional[str]
    is_planned: bool
    is_approved: bool
    created_at: datetime

    class Config:
        from_attributes = True
