from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class DiscountCodeValidateRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def code_trim_upper(cls, v: str) -> str:
        return v.strip().upper() if v else ""


class DiscountCodeValidateResponse(BaseModel):
    valid: bool
    message: str
    original_amount_inr: int
    discount_amount_inr: int
    final_amount_inr: int
    discount_code: Optional[str] = None  # echo back the code if valid


class DiscountCodeGenerateRequest(BaseModel):
    code: str  # e.g. SAVE10, WELCOME100
    discount_type: str  # "percent" or "fixed"
    value: int  # 1-100 for percent, or INR amount for fixed
    max_uses: Optional[int] = None  # None = unlimited
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    @field_validator("code")
    @classmethod
    def code_trim_upper(cls, v: str) -> str:
        return v.strip().upper() if v else ""

    @field_validator("discount_type")
    @classmethod
    def discount_type_lower(cls, v: str) -> str:
        return v.strip().lower() if v else ""


class DiscountCodeGenerateResponse(BaseModel):
    message: str
    code: str
    discount_type: str
    value: int
    max_uses: Optional[int] = None
