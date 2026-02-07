from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List


class BranchData(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    gstin: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None

    @field_validator('email', mode='before')
    @classmethod
    def validate_email(cls, v):
        if v == '' or v is None:
            return None
        return v

    @field_validator('address', 'phone', 'gstin', 'state', 'state_code', mode='before')
    @classmethod
    def validate_optional_string(cls, v):
        if v == '' or v is None:
            return None
        return v


class SalonOnboardingRequest(BaseModel):
    salon_name: str
    salon_email: Optional[EmailStr] = None
    salon_phone: Optional[str] = None
    salon_address: Optional[str] = None
    salon_gstin: Optional[str] = None
    place_of_supply: Optional[str] = None
    state_code: Optional[str] = None
    sender_id: Optional[str] = None  # MessageBot sender ID for this salon
    sms_enabled: bool = False  # Whether SMS service is enabled for this salon
    branches: List[BranchData]
    username: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None

    @field_validator('salon_email', mode='before')
    @classmethod
    def validate_salon_email(cls, v):
        if v == '' or v is None:
            return None
        return v

    @field_validator('salon_phone', 'salon_address', 'salon_gstin', 'place_of_supply', 'state_code', 'phone', 'sender_id', mode='before')
    @classmethod
    def validate_optional_string(cls, v):
        if v == '' or v is None:
            return None
        return v
    
    @field_validator('sender_id')
    @classmethod
    def validate_sender_id(cls, v):
        if v is not None:
            # Remove spaces and convert to uppercase
            v = v.replace(' ', '').upper()
            # Validate length (should be 6 characters for MessageBot)
            if len(v) != 6:
                raise ValueError('Sender ID must be exactly 6 characters')
            # Validate alphanumeric
            if not v.isalnum():
                raise ValueError('Sender ID must contain only letters and numbers')
        return v


class SalonOnboardingResponse(BaseModel):
    message: str
    salon_name: str
    status: str


class SalonListItem(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    approval_status: str
    is_active: bool
    created_at: Optional[str] = None


class BranchManagerInfo(BaseModel):
    id: int
    full_name: str
    email: str
    phone: Optional[str]
    is_active: bool


class BranchHierarchyInfo(BaseModel):
    id: int
    name: str
    address: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    approval_status: str
    is_active: bool
    managers: List[BranchManagerInfo]


class SalonHierarchyResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    address: Optional[str]
    gstin: Optional[str]
    approval_status: str
    is_active: bool
    created_at: Optional[str] = None
    owner: dict
    branches: List[BranchHierarchyInfo]
