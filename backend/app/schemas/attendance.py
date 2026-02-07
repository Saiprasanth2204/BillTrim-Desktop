from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import enum


class AttendanceStatusEnum(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    HALF_DAY = "half_day"
    LEAVE = "leave"


class AttendanceCreate(BaseModel):
    staff_id: int
    attendance_date: datetime
    status: AttendanceStatusEnum
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    notes: Optional[str] = None


class AttendanceUpdate(BaseModel):
    status: Optional[AttendanceStatusEnum] = None
    check_in_time: Optional[datetime] = None
    check_out_time: Optional[datetime] = None
    notes: Optional[str] = None


class AttendanceResponse(BaseModel):
    id: int
    staff_id: int
    attendance_date: datetime
    status: str
    check_in_time: Optional[datetime]
    check_out_time: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
