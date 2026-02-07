"""
Discount codes: validate (for users at checkout) and generate (admin API for Postman).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.discount_code import DiscountCode, DiscountTypeEnum
from app.schemas.discount_code import (
    DiscountCodeValidateRequest,
    DiscountCodeValidateResponse,
    DiscountCodeGenerateRequest,
    DiscountCodeGenerateResponse,
)

router = APIRouter()


def require_admin_api_key(x_admin_api_key: str | None = Header(None, alias="X-Admin-API-Key")) -> None:
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key is not configured. Set ADMIN_API_KEY in environment.",
        )
    if x_admin_api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-API-Key header.",
        )


@router.get("/license/price")
def get_license_price():
    """Return current license price in INR (for display in desktop app)."""
    return {"amount_inr": settings.LICENSE_PRICE_INR}


@router.post("/validate", response_model=DiscountCodeValidateResponse)
def validate_discount_code(
    body: DiscountCodeValidateRequest,
    amount_inr: int | None = None,  # optional override; default from config
    db: Session = Depends(get_db),
):
    """
    Validate a discount code and return original, discount, and final amount in INR.
    Call this when the user enters a discount code at checkout.
    If amount_inr is not provided, uses LICENSE_PRICE_INR from config (0 for now).
    """
    original = amount_inr if amount_inr is not None else settings.LICENSE_PRICE_INR
    code_str = body.code
    if not code_str:
        return DiscountCodeValidateResponse(
            valid=False,
            message="Please enter a discount code.",
            original_amount_inr=original,
            discount_amount_inr=0,
            final_amount_inr=original,
            discount_code=None,
        )

    row = db.query(DiscountCode).filter(
        DiscountCode.code == code_str,
        DiscountCode.is_active == True,
    ).first()
    if not row:
        return DiscountCodeValidateResponse(
            valid=False,
            message="Invalid or inactive discount code.",
            original_amount_inr=original,
            discount_amount_inr=0,
            final_amount_inr=original,
            discount_code=None,
        )

    now = datetime.now(timezone.utc)
    if row.valid_from and now < row.valid_from:
        return DiscountCodeValidateResponse(
            valid=False,
            message="This discount code is not yet valid.",
            original_amount_inr=original,
            discount_amount_inr=0,
            final_amount_inr=original,
            discount_code=None,
        )
    if row.valid_until and now > row.valid_until:
        return DiscountCodeValidateResponse(
            valid=False,
            message="This discount code has expired.",
            original_amount_inr=original,
            discount_amount_inr=0,
            final_amount_inr=original,
            discount_code=None,
        )
    if row.max_uses is not None and row.used_count >= row.max_uses:
        return DiscountCodeValidateResponse(
            valid=False,
            message="This discount code has reached its maximum uses.",
            original_amount_inr=original,
            discount_amount_inr=0,
            final_amount_inr=original,
            discount_code=None,
        )

    if row.discount_type == DiscountTypeEnum.PERCENT.value:
        discount = int(original * row.value / 100)
    else:
        discount = min(row.value, original)

    final = max(0, original - discount)
    return DiscountCodeValidateResponse(
        valid=True,
        message="Discount applied.",
        original_amount_inr=original,
        discount_amount_inr=discount,
        final_amount_inr=final,
        discount_code=row.code,
    )


@router.post("/admin/generate", response_model=DiscountCodeGenerateResponse)
def generate_discount_code(
    body: DiscountCodeGenerateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_api_key),
):
    """
    Create a new discount code. Call from Postman with header:
    X-Admin-API-Key: <your ADMIN_API_KEY from .env>

    Example body (percent):
      { "code": "SAVE10", "discount_type": "percent", "value": 10, "max_uses": 100 }
    Example body (fixed INR):
      { "code": "FLAT100", "discount_type": "fixed", "value": 100, "max_uses": 50 }
    """
    code_str = body.code.strip().upper()
    if not code_str:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="code is required")

    existing = db.query(DiscountCode).filter(DiscountCode.code == code_str).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Discount code '{code_str}' already exists.",
        )

    discount_type = body.discount_type.strip().lower()
    if discount_type not in ("percent", "fixed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="discount_type must be 'percent' or 'fixed'",
        )
    if discount_type == "percent" and (body.value < 1 or body.value > 100):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="value for percent must be between 1 and 100",
        )
    if discount_type == "fixed" and body.value < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="value for fixed must be >= 0",
        )

    dc = DiscountCode(
        code=code_str,
        discount_type=DiscountTypeEnum.PERCENT if discount_type == "percent" else DiscountTypeEnum.FIXED,
        value=body.value,
        max_uses=body.max_uses,
        used_count=0,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        is_active=True,
    )
    db.add(dc)
    db.commit()
    db.refresh(dc)

    return DiscountCodeGenerateResponse(
        message=f"Discount code '{dc.code}' created.",
        code=dc.code,
        discount_type=dc.discount_type.value,
        value=dc.value,
        max_uses=dc.max_uses,
    )
