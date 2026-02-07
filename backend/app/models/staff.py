from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Boolean, Enum as SQLEnum, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class StaffRoleEnum(str, enum.Enum):
    STYLIST = "stylist"
    THERAPIST = "therapist"
    MANAGER = "manager"
    ASSISTANT = "assistant"


class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False)
    email = Column(String(255), nullable=True)
    role = Column(SQLEnum(StaffRoleEnum, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=False, default=StaffRoleEnum.STYLIST)
    commission_percentage = Column(Numeric(5, 2), default=0.00)
    is_active = Column(Boolean, default=True)
    joining_date = Column(DateTime(timezone=True), nullable=True)
    standard_weekly_off = Column(Integer, nullable=True)
    standard_in_time = Column(Time, nullable=True)
    standard_out_time = Column(Time, nullable=True)
    image_url = Column(String(500), nullable=True)  # Staff photo URL
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    branch = relationship("Branch", back_populates="staff")
    week_offs = relationship("StaffWeekOff", back_populates="staff", cascade="all, delete-orphan")
    leaves = relationship("StaffLeave", back_populates="staff", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="staff")
    invoice_items = relationship("InvoiceItem", back_populates="staff")
    attendance = relationship("Attendance", back_populates="staff", cascade="all, delete-orphan")


class StaffWeekOff(Base):
    __tablename__ = "staff_week_offs"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    staff = relationship("Staff", back_populates="week_offs")


class StaffLeave(Base):
    __tablename__ = "staff_leaves"

    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=False, index=True)
    leave_date = Column(DateTime(timezone=True), nullable=False, index=True)
    leave_from = Column(DateTime(timezone=True), nullable=True, index=True)
    leave_to = Column(DateTime(timezone=True), nullable=True, index=True)
    reason = Column(String(255), nullable=True)
    is_planned = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    staff = relationship("Staff", back_populates="leaves")
