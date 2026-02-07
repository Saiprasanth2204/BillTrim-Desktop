"""
Desktop: Onboard new salon with immediate approval (no pending/approval flow).
"""
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.company import Company, Branch, ApprovalStatusEnum
from app.models.user import User, RoleEnum
from app.core.security import get_password_hash
from app.core.logging_config import get_logger
from app.core.db_transaction import safe_commit
from app.core.config import settings
from app.schemas.onboarding import SalonOnboardingRequest, SalonOnboardingResponse

logger = get_logger("onboarding_service")


def validate_onboarding_request(request: SalonOnboardingRequest, db: Session) -> None:
    if not request.branches or len(request.branches) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one branch is required"
        )
    existing_user = db.query(User).filter(
        User.email == request.username,
        User.is_active == True
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    if request.salon_gstin:
        existing_company = db.query(Company).filter(Company.gstin == request.salon_gstin).first()
        if existing_company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GSTIN already registered"
            )


def create_salon_from_onboarding(request: SalonOnboardingRequest, db: Session) -> SalonOnboardingResponse:
    validate_onboarding_request(request, db)

    company_email = request.salon_email or request.username
    
    # Use sender_id from request, or fallback to default from settings
    sender_id = request.sender_id or settings.MESSAGEBOT_SENDER_ID
    
    # Desktop: create approved and active immediately (no approval process)
    company = Company(
        name=request.salon_name,
        email=company_email,
        phone=request.salon_phone,
        address=request.salon_address,
        gstin=request.salon_gstin,
        place_of_supply=request.place_of_supply,
        state_code=request.state_code,
        sender_id=sender_id,  # Set sender ID for this salon
        sms_enabled=request.sms_enabled,  # Set SMS opt-in preference
        approval_status=ApprovalStatusEnum.APPROVED,
        is_active=True
    )
    db.add(company)
    db.flush()

    branches = []
    first_branch = None
    for branch_data in request.branches:
        branch = Branch(
            company_id=company.id,
            name=branch_data.name,
            address=branch_data.address,
            phone=branch_data.phone,
            email=branch_data.email,
            gstin=branch_data.gstin,
            state=branch_data.state,
            state_code=branch_data.state_code,
            max_logins_per_branch=5,
            approval_status=ApprovalStatusEnum.APPROVED,
            is_active=True
        )
        db.add(branch)
        db.flush()
        branches.append(branch)
        if first_branch is None:
            first_branch = branch

    user_phone = request.phone if request.phone and request.phone.strip() else None
    user = User(
        company_id=company.id,
        branch_id=first_branch.id if first_branch else None,
        email=request.username,
        phone=user_phone,
        hashed_password=get_password_hash(request.password),
        full_name=request.full_name,
        role=RoleEnum.OWNER,
        is_active=True,
        is_superuser=False
    )
    db.add(user)

    if not safe_commit(db, "onboard_salon"):
        logger.error("Failed to commit onboarding", extra={"salon_name": request.salon_name})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again."
        )

    return SalonOnboardingResponse(
        message="Salon created successfully. You can log in now.",
        salon_name=request.salon_name,
        status="approved"
    )
