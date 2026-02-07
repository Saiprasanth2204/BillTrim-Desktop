from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class DiscountTypeEnum(str, enum.Enum):
    PERCENT = "percent"   # value is 1-100
    FIXED = "fixed"       # value is amount in INR (paise if you prefer; we use INR for clarity)


class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, nullable=False, index=True)  # e.g. SAVE10, WELCOME100
    discount_type = Column(
        SQLEnum(DiscountTypeEnum, values_callable=lambda x: [e.value for e in x], native_enum=False),
        nullable=False,
    )
    value = Column(Integer, nullable=False)  # percent (1-100) or fixed amount in INR
    max_uses = Column(Integer, nullable=True)  # None = unlimited
    used_count = Column(Integer, default=0, nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=True)  # None = from now
    valid_until = Column(DateTime(timezone=True), nullable=True)  # None = no expiry
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
