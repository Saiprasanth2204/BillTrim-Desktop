"""
Branding settings and company settings endpoints (logo, SMS, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Any, Optional
from app.core.database import get_db
from app.models.user import User, RoleEnum
from app.models.settings import BrandingSettings
from app.models.company import Company
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()


class BrandingResponse(BaseModel):
    logo_url: Optional[str] = None
    primary_color: str = "#000000"
    secondary_color: Optional[str] = None
    invoice_footer_text: Optional[str] = None
    invoice_footer_logo_url: Optional[str] = None
    is_white_label: bool = False

    class Config:
        from_attributes = True


@router.get("/branding", response_model=BrandingResponse)
async def get_branding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get branding settings for current user's company."""
    branding = db.query(BrandingSettings).filter(
        BrandingSettings.company_id == current_user.company_id
    ).first()
    
    if not branding:
        return BrandingResponse()
    
    return BrandingResponse(
        logo_url=branding.logo_url,
        primary_color=branding.primary_color,
        secondary_color=branding.secondary_color,
        invoice_footer_text=branding.invoice_footer_text,
        invoice_footer_logo_url=branding.invoice_footer_logo_url,
        is_white_label=branding.is_white_label,
    )


# --- Company SMS settings (opt-in/opt-out for owner, readable by all) ---

class CompanySmsResponse(BaseModel):
    sms_enabled: bool
    sender_id: Optional[str] = None


class CompanySmsUpdate(BaseModel):
    sms_enabled: Optional[bool] = None
    sender_id: Optional[str] = None


def require_owner_or_superuser(current_user: Any) -> None:
    """Dependency: raise if not owner or superuser. Do not use User as return type (not a Pydantic type)."""
    if current_user.role != RoleEnum.OWNER and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the salon owner can change SMS settings",
        )
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No company associated with this account",
        )


@router.get("/company-sms", response_model=CompanySmsResponse)
async def get_company_sms(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get SMS settings for the current user's company (salon)."""
    if not current_user.company_id:
        return CompanySmsResponse(sms_enabled=False, sender_id=None)
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        return CompanySmsResponse(sms_enabled=False, sender_id=None)
    return CompanySmsResponse(
        sms_enabled=bool(company.sms_enabled),
        sender_id=company.sender_id,
    )


def _normalize_sender_id(value: Optional[str]) -> Optional[str]:
    """Normalize sender_id: strip, uppercase, alphanumeric only. Return None if empty. Raise if invalid."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    s = str(value).strip().upper()
    s = "".join(c for c in s if c.isalnum())
    if not s:
        return None
    if len(s) != 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sender ID must be exactly 6 characters (letters and numbers only)",
        )
    if not s.isalnum():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sender ID must contain only letters and numbers",
        )
    return s


@router.patch("/company-sms", response_model=CompanySmsResponse)
async def update_company_sms(
    body: CompanySmsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update SMS opt-in and optional sender ID for the salon. Owner only."""
    require_owner_or_superuser(current_user)
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if body.sms_enabled is not None:
        company.sms_enabled = body.sms_enabled
    if body.sender_id is not None:
        company.sender_id = _normalize_sender_id(body.sender_id)
    db.commit()
    db.refresh(company)
    return CompanySmsResponse(
        sms_enabled=bool(company.sms_enabled),
        sender_id=company.sender_id,
    )
