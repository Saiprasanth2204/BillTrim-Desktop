from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class ApprovalStatusEnum(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True)
    phone = Column(String(20))
    address = Column(Text)
    gstin = Column(String(15), unique=True, index=True)
    place_of_supply = Column(String(255), nullable=True)
    state_code = Column(String(10), nullable=True)
    sender_id = Column(String(10), nullable=True)  # MessageBot sender ID for this salon/company
    sms_enabled = Column(Boolean, default=False, nullable=False)  # Whether SMS service is enabled for this salon
    approval_status = Column(SQLEnum(ApprovalStatusEnum, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=False, default=ApprovalStatusEnum.APPROVED)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    branches = relationship("Branch", back_populates="company", cascade="all, delete-orphan")
    users = relationship("User", back_populates="company")
    memberships = relationship("Membership", back_populates="company", cascade="all, delete-orphan")


class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    address = Column(Text)
    phone = Column(String(20))
    email = Column(String(255))
    gstin = Column(String(15), index=True, nullable=True)
    state = Column(String(255), nullable=True)
    state_code = Column(String(10), nullable=True)
    max_logins_per_branch = Column(Integer, default=5, nullable=False)
    approval_status = Column(SQLEnum(ApprovalStatusEnum, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=False, default=ApprovalStatusEnum.APPROVED)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    company = relationship("Company", back_populates="branches")
    staff = relationship("Staff", back_populates="branch")
    services = relationship("Service", back_populates="branch")
    appointments = relationship("Appointment", back_populates="branch")
    invoices = relationship("Invoice", back_populates="branch")
    memberships = relationship("Membership", back_populates="branch", cascade="all, delete-orphan")
    user_sessions = relationship("UserSession", back_populates="branch", cascade="all, delete-orphan")
