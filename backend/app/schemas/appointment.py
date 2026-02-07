from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.models.appointment import AppointmentStatusEnum


class AppointmentServiceCreate(BaseModel):
    service_id: int
    quantity: int = 1


class AppointmentCreate(BaseModel):
    customer_id: int
    staff_id: int
    appointment_date: datetime
    services: List[AppointmentServiceCreate]
    notes: Optional[str] = None
    branch_id: Optional[int] = None


class AppointmentUpdate(BaseModel):
    appointment_date: Optional[datetime] = None
    staff_id: Optional[int] = None
    status: Optional[AppointmentStatusEnum] = None
    notes: Optional[str] = None


class AppointmentServiceResponse(BaseModel):
    id: int
    service_id: int
    service_name: str
    quantity: int
    price: int

    class Config:
        from_attributes = True


class AppointmentResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    customer_phone: str
    staff_id: int
    staff_name: str
    appointment_date: datetime
    status: AppointmentStatusEnum
    services: List[AppointmentServiceResponse]
    checked_in_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    invoice_id: Optional[int] = None  # ID of associated invoice if exists

    class Config:
        from_attributes = True


class StaffAvailabilityResponse(BaseModel):
    staff_id: int
    staff_name: str
    is_available: bool
    reason: Optional[str] = None  # Reason if not available
    conflicting_appointment_id: Optional[int] = None  # If there's a conflicting appointment


class AvailabilityCheckRequest(BaseModel):
    appointment_date: datetime
    duration_minutes: Optional[int] = 30  # Default 30 minutes if not specified
    branch_id: Optional[int] = None
    service_ids: Optional[List[int]] = None  # Optional: to calculate duration from services


class AvailableSlotResponse(BaseModel):
    slot_datetime: datetime
    formatted_date: str  # e.g., "2026-02-05"
    formatted_time: str  # e.g., "14:30"
    formatted_display: str  # e.g., "Feb 5, 2026 at 2:30 PM"


class StaffAvailableSlotsRequest(BaseModel):
    from_datetime: datetime  # Start searching from this datetime
    duration_minutes: Optional[int] = 30
    branch_id: Optional[int] = None
    service_ids: Optional[List[int]] = None
    max_slots: Optional[int] = 3  # Number of slots to return


class TimeSlot(BaseModel):
    start_time: str  # Format: "HH:MM"
    end_time: str  # Format: "HH:MM"


class StaffAvailabilityDayStaff(BaseModel):
    staff_id: int
    staff_name: str
    is_available: bool
    reasons: List[str]
    available_time_slots: List[TimeSlot] = []  # Available time slots for the day


class StaffAvailabilityDayResponse(BaseModel):
    date: str
    day_of_week: int
    staff_availability: List[StaffAvailabilityDayStaff]
