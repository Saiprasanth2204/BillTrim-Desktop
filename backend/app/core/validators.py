"""
Reusable validators for common validation patterns
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.company import Branch, Company
from app.models.user import User
from app.core.logging_config import get_logger

logger = get_logger("validators")


def validate_branch_access(
    db: Session,
    branch_id: int,
    user: User,
    allow_none: bool = False
) -> Branch:
    """
    Validate that a branch exists and belongs to the user's company.
    
    Args:
        db: Database session
        branch_id: Branch ID to validate
        user: Current user
        allow_none: If True, return None when branch_id is None
    
    Returns:
        Branch object if valid
    
    Raises:
        HTTPException: If branch is invalid or access denied
    """
    if branch_id is None:
        if allow_none:
            return None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Branch ID is required"
        )
    
    # Super admin has no company_id; allow access to any branch by id and active
    if user.is_superuser:
        branch = db.query(Branch).filter(
            Branch.id == branch_id,
            Branch.is_active == True
        ).first()
    else:
        branch = db.query(Branch).filter(
            Branch.id == branch_id,
            Branch.company_id == user.company_id,
            Branch.is_active == True
        ).first()
    
    if not branch:
        logger.warning(
            f"Branch access denied: branch_id={branch_id}, user_id={user.id}, company_id={user.company_id}",
            extra={
                "branch_id": branch_id,
                "user_id": user.id,
                "company_id": user.company_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Branch not found, inactive, or access denied"
        )
    
    return branch


def get_user_branch_or_first_active(
    db: Session,
    user: User,
    requested_branch_id: int = None
) -> Branch:
    """
    Get the effective branch for a user.
    - If requested_branch_id provided, validate and return it
    - Otherwise, use user's branch_id
    - If user has no branch (e.g., owner), get first active branch
    
    Args:
        db: Database session
        user: Current user
        requested_branch_id: Optional branch ID from request
    
    Returns:
        Branch object
    
    Raises:
        HTTPException: If no valid branch found
    """
    # Super admin has no company_id/branch_id; can access any branch
    if user.is_superuser:
        if requested_branch_id:
            return validate_branch_access(db, requested_branch_id, user)
        # Super admin without branch_id - get first active branch (any company)
        branch = db.query(Branch).filter(Branch.is_active == True).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active branch found"
            )
        return branch
    
    # Owners can switch between branches or view all
    if user.role.value == "owner":
        if requested_branch_id:
            return validate_branch_access(db, requested_branch_id, user)
        # Owner without branch assignment - get first active branch for company
        branch = db.query(Branch).filter(
            Branch.company_id == user.company_id,
            Branch.is_active == True
        ).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active branch found for your company"
            )
        return branch
    
    # Managers and staff are locked to their branch
    if user.branch_id:
        return validate_branch_access(db, user.branch_id, user)
    
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No branch assigned to your account"
    )


def validate_company_access(db: Session, company_id: int, user: User) -> Company:
    """
    Validate that a company exists and user has access.
    
    Args:
        db: Database session
        company_id: Company ID to validate
        user: Current user
    
    Returns:
        Company object if valid
    
    Raises:
        HTTPException: If company is invalid or access denied
    """
    # Super admin can access all companies
    if user.is_superuser:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )
        return company
    
    # Regular users can only access their own company
    if user.company_id != company_id:
        logger.warning(
            f"Company access denied: company_id={company_id}, user_id={user.id}, user_company_id={user.company_id}",
            extra={
                "requested_company_id": company_id,
                "user_id": user.id,
                "user_company_id": user.company_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this company"
        )
    
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    return company
