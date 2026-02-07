from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class BrandingSettings(Base):
    __tablename__ = "settings_branding"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, unique=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    logo_url = Column(String(500), nullable=True)
    primary_color = Column(String(7), default="#000000")
    secondary_color = Column(String(7), nullable=True)
    invoice_footer_text = Column(Text, nullable=True)
    invoice_footer_logo_url = Column(String(500), nullable=True)
    is_white_label = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
