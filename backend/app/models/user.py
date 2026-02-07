from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class RoleEnum(str, enum.Enum):
    OWNER = "owner"
    MANAGER = "manager"
    STAFF = "staff"
    BILLING_OPERATOR = "billing_operator"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    phone = Column(String(20), index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SQLEnum(RoleEnum, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=False, default=RoleEnum.STAFF)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company", back_populates="users")
    branch = relationship("Branch")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
