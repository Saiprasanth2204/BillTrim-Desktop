"""
File upload endpoints for images (logo, staff photos).
Stores files locally in uploads/ directory for desktop app.
"""
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()

# Ensure upload directory exists
UPLOAD_DIR = Path(settings.UPLOAD_DIR_ABS)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOGO_DIR = UPLOAD_DIR / "logos"
STAFF_DIR = UPLOAD_DIR / "staff"
LOGO_DIR.mkdir(exist_ok=True)
STAFF_DIR.mkdir(exist_ok=True)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def validate_image(file: UploadFile) -> None:
    """Validate image file type (by Content-Type or filename) and size."""
    content_type = (file.content_type or "").strip().lower()
    # Accept if Content-Type is in allowed list
    if content_type in ALLOWED_IMAGE_TYPES:
        return
    # Accept missing/generic Content-Type if filename has image extension (e.g. browser sent wrong header)
    if file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext in ALLOWED_IMAGE_EXTENSIONS:
            return
    # Accept application/octet-stream with image extension
    if content_type in ("application/octet-stream", "") and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext in ALLOWED_IMAGE_EXTENSIONS:
            return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)} or extensions {', '.join(ALLOWED_IMAGE_EXTENSIONS)}. Got: {content_type or 'none'!r}, filename={getattr(file, 'filename', '')!r}"
    )


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload salon logo (owner only). Returns URL path."""
    if current_user.role.value != "owner" and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only salon owners can upload logos"
        )
    
    validate_image(file)
    
    # Read file content
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
        )
    
    # Generate unique filename
    ext = Path(file.filename).suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    filepath = LOGO_DIR / filename
    
    # Save file
    with open(filepath, "wb") as f:
        f.write(content)
    
    # Update branding settings
    from app.models.settings import BrandingSettings
    branding = db.query(BrandingSettings).filter(
        BrandingSettings.company_id == current_user.company_id
    ).first()
    
    if branding:
        # Delete old logo if exists
        if branding.logo_url:
            old_path = UPLOAD_DIR / branding.logo_url.lstrip("/")
            if old_path.exists():
                old_path.unlink()
        branding.logo_url = f"/uploads/logos/{filename}"
    else:
        branding = BrandingSettings(
            company_id=current_user.company_id,
            logo_url=f"/uploads/logos/{filename}"
        )
        db.add(branding)
    
    db.commit()
    
    return {"url": f"/uploads/logos/{filename}", "message": "Logo uploaded successfully"}


@router.post("/staff-photo")
async def upload_staff_photo(
    staff_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload staff photo. Returns URL path. Expects multipart/form-data with field 'file'."""
    from app.models.staff import Staff
    
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided. Send multipart/form-data with a 'file' field.",
        )
    
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")
    
    # Verify access: owner/manager of same company, or staff themselves
    if current_user.company_id != staff.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    validate_image(file)
    
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
        )
    
    ext = Path(file.filename).suffix or ".jpg"
    filename = f"{staff_id}_{uuid.uuid4()}{ext}"
    filepath = STAFF_DIR / filename
    
    # Delete old photo if exists
    if staff.image_url:
        old_path = UPLOAD_DIR / staff.image_url.lstrip("/")
        if old_path.exists():
            old_path.unlink()
    
    # Save file
    with open(filepath, "wb") as f:
        f.write(content)
    
    staff.image_url = f"/uploads/staff/{filename}"
    db.commit()
    
    return {"url": f"/uploads/staff/{filename}", "message": "Staff photo uploaded successfully"}


@router.delete("/staff-photo/{staff_id}")
async def delete_staff_photo(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete staff photo."""
    from app.models.staff import Staff
    
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")
    
    # Verify access: owner/manager of same company, or staff themselves
    if current_user.company_id != staff.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Delete file if exists
    if staff.image_url:
        old_path = UPLOAD_DIR / staff.image_url.lstrip("/")
        if old_path.exists():
            old_path.unlink()
    
    # Clear image_url in database
    staff.image_url = None
    db.commit()
    
    return {"message": "Staff photo deleted successfully"}


# Catch-all route for serving files - must be last to avoid matching API routes
# Exclude API endpoints from file serving
@router.get("/{filepath:path}")
async def serve_uploaded_file(filepath: str):
    """Serve uploaded files (logos, staff photos)."""
    # Don't serve API endpoints as files
    if filepath.startswith("staff-photo") or filepath.startswith("logo"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    full_path = UPLOAD_DIR / filepath
    if not full_path.exists() or not str(full_path).startswith(str(UPLOAD_DIR)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(full_path)
