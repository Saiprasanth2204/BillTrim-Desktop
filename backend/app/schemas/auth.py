from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.user import RoleEnum


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    phone: Optional[str]
    role: RoleEnum
    company_id: Optional[int] = None
    branch_id: Optional[int]
    is_active: bool
    is_superuser: bool = False
    last_login: Optional[datetime]

    class Config:
        from_attributes = True
