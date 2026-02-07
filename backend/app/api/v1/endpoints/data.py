"""
Export and import salon data for backup/restore (e.g. when changing computer).
Automatically handles database migrations during import.
"""
import json
import os
from datetime import datetime, date, time
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_user
from alembic.config import Config
from alembic import command

router = APIRouter()


def _role_value(role) -> str:
    if role is None:
        return ""
    if hasattr(role, "value"):
        return getattr(role, "value", "") or ""
    return str(role).lower()


def _serialize(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def _row_to_dict(row: Any) -> dict:
    return {c.key: _serialize(getattr(row, c.key)) for c in row.__table__.columns}


@router.get("/export")
async def export_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export all salon data for the current user's company (or all if superuser).
    Returns a single JSON object suitable for backup and later import.
    """
    # Export scope: single company for owner/manager/staff, all for superuser
    company_id = current_user.company_id if not current_user.is_superuser else None

    # Get current database migration version
    migration_version = None
    try:
        from sqlalchemy import text as sql_text
        result = db.execute(sql_text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.fetchone()
        if row:
            migration_version = row[0]
    except Exception:
        # Alembic version table might not exist yet, that's okay
        pass
    
    out = {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat(),
        "migration_version": migration_version,  # Track schema version
        "companies": [],
        "branches": [],
        "users": [],
        "staff": [],
        "staff_week_offs": [],
        "staff_leaves": [],
        "customers": [],
        "memberships": [],
        "services": [],
        "products": [],
        "appointments": [],
        "appointment_services": [],
        "invoices": [],
        "invoice_items": [],
        "payments": [],
        "attendance": [],
        "settings_branding": [],
    }

    from app.models import (
        Company, Branch, User as UserModel,
        Staff, StaffWeekOff, StaffLeave,
        Customer, Membership, Service, Product,
        Appointment, AppointmentService,
        Invoice, InvoiceItem, Payment,
        Attendance,
    )
    from app.models.settings import BrandingSettings

    q_company = db.query(Company)
    if company_id is not None:
        q_company = q_company.filter(Company.id == company_id)
    companies = q_company.all()
    company_ids = [c.id for c in companies]

    for c in companies:
        out["companies"].append(_row_to_dict(c))

    if not company_ids:
        return out

    branches = db.query(Branch).filter(Branch.company_id.in_(company_ids)).all()
    branch_ids = [b.id for b in branches]
    for b in branches:
        out["branches"].append(_row_to_dict(b))

    users = db.query(UserModel).filter(UserModel.company_id.in_(company_ids)).all()
    user_ids = [u.id for u in users]
    for u in users:
        out["users"].append(_row_to_dict(u))

    staff_list = db.query(Staff).filter(Staff.company_id.in_(company_ids)).all()
    staff_ids = [s.id for s in staff_list]
    for s in staff_list:
        out["staff"].append(_row_to_dict(s))

    for row in db.query(StaffWeekOff).filter(StaffWeekOff.staff_id.in_(staff_ids)).all():
        out["staff_week_offs"].append(_row_to_dict(row))
    for row in db.query(StaffLeave).filter(StaffLeave.staff_id.in_(staff_ids)).all():
        out["staff_leaves"].append(_row_to_dict(row))

    for row in db.query(Customer).filter(Customer.company_id.in_(company_ids)).all():
        out["customers"].append(_row_to_dict(row))
    for row in db.query(Membership).filter(Membership.company_id.in_(company_ids)).all():
        out["memberships"].append(_row_to_dict(row))
    for row in db.query(Service).filter(Service.company_id.in_(company_ids)).all():
        out["services"].append(_row_to_dict(row))
    for row in db.query(Product).filter(Product.company_id.in_(company_ids)).all():
        out["products"].append(_row_to_dict(row))

    appointments = db.query(Appointment).filter(Appointment.company_id.in_(company_ids)).all()
    appointment_ids = [a.id for a in appointments]
    for a in appointments:
        out["appointments"].append(_row_to_dict(a))
    for row in db.query(AppointmentService).filter(AppointmentService.appointment_id.in_(appointment_ids)).all():
        out["appointment_services"].append(_row_to_dict(row))

    invoices = db.query(Invoice).filter(Invoice.company_id.in_(company_ids)).all()
    invoice_ids = [i.id for i in invoices]
    for i in invoices:
        out["invoices"].append(_row_to_dict(i))
    for row in db.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(invoice_ids)).all():
        out["invoice_items"].append(_row_to_dict(row))
    for row in db.query(Payment).filter(Payment.invoice_id.in_(invoice_ids)).all():
        out["payments"].append(_row_to_dict(row))

    for row in db.query(Attendance).filter(Attendance.staff_id.in_(staff_ids)).all():
        out["attendance"].append(_row_to_dict(row))
    for row in db.query(BrandingSettings).filter(BrandingSettings.company_id.in_(company_ids)).all():
        out["settings_branding"].append(_row_to_dict(row))

    return out


@router.post("/wipe-salon", status_code=200)
async def wipe_salon(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete all data for the current user's company (owner only).
    Use when the owner wants to completely remove the salon from the database.
    After this, the license should be cleared on the client so the user must re-enter it on restart.
    """
    from app.models.user import RoleEnum
    if _role_value(current_user.role) != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only salon owners can delete salon data.",
        )
    company_id = current_user.company_id
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No company associated with this account.",
        )

    from app.models import (
        Company, Branch,
        User as UserModel, UserSession,
        Staff, StaffWeekOff, StaffLeave,
        Customer, Membership, Service, Product,
        Appointment, AppointmentService,
        Invoice, InvoiceItem, Payment,
        Attendance,
    )
    from app.models.settings import BrandingSettings

    branch_ids = [b.id for b in db.query(Branch).filter(Branch.company_id == company_id).all()]
    staff_ids = [s.id for s in db.query(Staff).filter(Staff.company_id == company_id).all()]
    invoice_ids = [i.id for i in db.query(Invoice).filter(Invoice.company_id == company_id).all()]
    appointment_ids = [a.id for a in db.query(Appointment).filter(Appointment.company_id == company_id).all()]

    try:
        if invoice_ids:
            db.query(Payment).filter(Payment.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
        db.query(Invoice).filter(Invoice.company_id == company_id).delete(synchronize_session=False)
        if appointment_ids:
            db.query(AppointmentService).filter(AppointmentService.appointment_id.in_(appointment_ids)).delete(synchronize_session=False)
        db.query(Appointment).filter(Appointment.company_id == company_id).delete(synchronize_session=False)
        if staff_ids:
            db.query(Attendance).filter(Attendance.staff_id.in_(staff_ids)).delete(synchronize_session=False)
            db.query(StaffLeave).filter(StaffLeave.staff_id.in_(staff_ids)).delete(synchronize_session=False)
            db.query(StaffWeekOff).filter(StaffWeekOff.staff_id.in_(staff_ids)).delete(synchronize_session=False)
        db.query(Staff).filter(Staff.company_id == company_id).delete(synchronize_session=False)
        db.query(Customer).filter(Customer.company_id.in_([company_id])).delete(synchronize_session=False)
        db.query(Membership).filter(Membership.company_id == company_id).delete(synchronize_session=False)
        db.query(Service).filter(Service.company_id == company_id).delete(synchronize_session=False)
        db.query(Product).filter(Product.company_id == company_id).delete(synchronize_session=False)
        if branch_ids:
            db.query(UserSession).filter(UserSession.branch_id.in_(branch_ids)).delete(synchronize_session=False)
        db.query(UserModel).filter(UserModel.company_id == company_id).delete(synchronize_session=False)
        db.query(Branch).filter(Branch.company_id == company_id).delete(synchronize_session=False)
        db.query(BrandingSettings).filter(BrandingSettings.company_id == company_id).delete(synchronize_session=False)
        db.query(Company).filter(Company.id == company_id).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete salon data: {str(e)}",
        )
    return {"message": "Salon data deleted successfully. Please clear the license and restart the application."}


@router.post("/import-restore", status_code=200)
async def import_restore(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Restore from a previously exported backup when there is no salon data in the database
    (e.g. after deleting salon data or on a fresh install). No authentication required.
    Use from the registration/onboard page to recover lost data.
    """
    from app.models import Company
    if db.query(Company).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restore is only allowed when there is no existing salon data. Use Account → Import data when logged in.",
        )
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload a .json file from Export Data.",
        )
    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e}",
        )
    if data.get("version") != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported backup version.",
        )
    _run_import(db, data)
    return {
        "message": "Data restored successfully. You can now log in with your existing credentials.",
        "migration_applied": True,
    }


def _run_import(db: Session, data: dict) -> None:
    """Clear all tables and re-insert from data dict. Used by both /import and /import-restore."""
    from app.models import (
        Company, Branch, User as UserModel,
        Staff, StaffWeekOff, StaffLeave,
        Customer, Membership, Service, Product,
        Appointment, AppointmentService,
        Invoice, InvoiceItem, Payment,
        Attendance,
    )
    from app.models.user_session import UserSession
    from app.models.settings import BrandingSettings

    try:
        db.execute(text("PRAGMA foreign_keys=OFF"))
        db.commit()
    except Exception:
        pass

    def _clear_tables():
        db.query(Payment).delete()
        db.query(InvoiceItem).delete()
        db.query(Invoice).delete()
        db.query(AppointmentService).delete()
        db.query(Appointment).delete()
        db.query(Attendance).delete()
        db.query(StaffLeave).delete()
        db.query(StaffWeekOff).delete()
        db.query(Staff).delete()
        db.query(Customer).delete()
        db.query(Membership).delete()
        db.query(Service).delete()
        db.query(Product).delete()
        db.query(UserSession).delete()
        db.query(UserModel).delete()
        db.query(Branch).delete()
        db.query(Company).delete()
        db.query(BrandingSettings).delete()

    _clear_tables()
    db.commit()

    id_maps = {
        "companies": {},
        "branches": {},
        "users": {},
        "staff": {},
        "customers": {},
        "memberships": {},
        "services": {},
        "products": {},
        "appointments": {},
        "invoices": {},
    }

    def _parse_dt(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    def _parse_date(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except Exception:
            return None

    def _parse_time(s):
        """Convert string or datetime to Python time for SQLite Time columns."""
        if s is None:
            return None
        if isinstance(s, time):
            return s
        if isinstance(s, datetime):
            return s.time()
        if isinstance(s, str):
            s = s.strip()
            if not s:
                return None
            try:
                # "09:00:00" or "09:00"
                parts = s.split(":")
                if len(parts) >= 2:
                    h, m = int(parts[0]), int(parts[1])
                    sec = int(parts[2]) if len(parts) > 2 else 0
                    if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= sec <= 59:
                        return time(h, m, sec)
                # Fallback: full ISO datetime
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return dt.time()
            except Exception:
                return None
        return None

    try:
        for row in data.get("companies", []):
            old_id = row.pop("id", None)
            c = Company(
                name=row["name"],
                email=row.get("email"),
                phone=row.get("phone"),
                address=row.get("address"),
                gstin=row.get("gstin"),
                place_of_supply=row.get("place_of_supply"),
                state_code=row.get("state_code"),
                approval_status=row.get("approval_status", "approved"),
                is_active=row.get("is_active", True),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(c)
            db.flush()
            if old_id is not None:
                id_maps["companies"][old_id] = c.id

        for row in data.get("branches", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            b = Branch(
                company_id=cid,
                name=row["name"],
                address=row.get("address"),
                phone=row.get("phone"),
                email=row.get("email"),
                gstin=row.get("gstin"),
                state=row.get("state"),
                state_code=row.get("state_code"),
                max_logins_per_branch=row.get("max_logins_per_branch", 5),
                approval_status=row.get("approval_status", "approved"),
                is_active=row.get("is_active", True),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(b)
            db.flush()
            if old_id is not None:
                id_maps["branches"][old_id] = b.id

        for row in data.get("users", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row.get("company_id"))
            bid = id_maps["branches"].get(row["branch_id"], row.get("branch_id")) if row.get("branch_id") else None
            u = UserModel(
                company_id=cid,
                branch_id=bid,
                email=row["email"],
                phone=row.get("phone"),
                hashed_password=row["hashed_password"],
                full_name=row["full_name"],
                role=row.get("role", "staff"),
                is_active=row.get("is_active", True),
                is_superuser=row.get("is_superuser", False),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
                last_login=_parse_dt(row.get("last_login")),
            )
            db.add(u)
            db.flush()
            if old_id is not None:
                id_maps["users"][old_id] = u.id

        for row in data.get("staff", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"])
            uid = id_maps["users"].get(row["user_id"], row.get("user_id")) if row.get("user_id") else None
            s = Staff(
                company_id=cid,
                branch_id=bid,
                user_id=uid,
                name=row["name"],
                phone=row["phone"],
                email=row.get("email"),
                role=row.get("role", "stylist"),
                commission_percentage=row.get("commission_percentage", 0),
                standard_weekly_off=row.get("standard_weekly_off"),
                standard_in_time=_parse_time(row.get("standard_in_time")),
                standard_out_time=_parse_time(row.get("standard_out_time")),
                image_url=row.get("image_url"),
                is_active=row.get("is_active", True),
                joining_date=_parse_dt(row.get("joining_date")),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(s)
            db.flush()
            if old_id is not None:
                id_maps["staff"][old_id] = s.id

        for row in data.get("staff_week_offs", []):
            sid = id_maps["staff"].get(row["staff_id"], row["staff_id"])
            db.add(StaffWeekOff(
                staff_id=sid,
                day_of_week=row["day_of_week"],
                is_active=row.get("is_active", True),
                created_at=_parse_dt(row.get("created_at")),
            ))
        for row in data.get("staff_leaves", []):
            sid = id_maps["staff"].get(row["staff_id"], row["staff_id"])
            db.add(StaffLeave(
                staff_id=sid,
                leave_date=_parse_dt(row["leave_date"]),
                leave_from=_parse_dt(row.get("leave_from")),
                leave_to=_parse_dt(row.get("leave_to")),
                reason=row.get("reason"),
                is_planned=row.get("is_planned", True),
                is_approved=row.get("is_approved", False),
                created_at=_parse_dt(row.get("created_at")),
            ))

        for row in data.get("memberships", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"])
            m = Membership(
                company_id=cid,
                branch_id=bid,
                name=row["name"],
                description=row.get("description"),
                discount_percentage=row["discount_percentage"],
                is_active=row.get("is_active", True),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(m)
            db.flush()
            if old_id is not None:
                id_maps["memberships"][old_id] = m.id

        for row in data.get("customers", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"]) if row.get("branch_id") else None
            mid = id_maps["memberships"].get(row["membership_id"], row["membership_id"]) if row.get("membership_id") else None
            cust = Customer(
                company_id=cid,
                branch_id=bid,
                membership_id=mid,
                name=row["name"],
                phone=row["phone"],
                email=row.get("email"),
                address=row.get("address"),
                date_of_birth=_parse_dt(row.get("date_of_birth")),
                gender=row.get("gender"),
                notes=row.get("notes"),
                total_visits=row.get("total_visits", 0),
                total_spent=row.get("total_spent", 0),
                last_visit=_parse_dt(row.get("last_visit")),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(cust)
            db.flush()
            if old_id is not None:
                id_maps["customers"][old_id] = cust.id

        for row in data.get("services", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"])
            svc = Service(
                company_id=cid,
                branch_id=bid,
                name=row["name"],
                description=row.get("description"),
                price=row["price"],
                duration_minutes=row.get("duration_minutes", 30),
                hsn_sac_code=row.get("hsn_sac_code"),
                gst_rate_id=row.get("gst_rate_id"),
                is_active=row.get("is_active", True),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(svc)
            db.flush()
            if old_id is not None:
                id_maps["services"][old_id] = svc.id

        for row in data.get("products", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"])
            p = Product(
                company_id=cid,
                branch_id=bid,
                name=row["name"],
                description=row.get("description"),
                price=row["price"],
                stock_quantity=row.get("stock_quantity", 0),
                hsn_sac_code=row.get("hsn_sac_code"),
                gst_rate_id=row.get("gst_rate_id"),
                is_active=row.get("is_active", True),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(p)
            db.flush()
            if old_id is not None:
                id_maps["products"][old_id] = p.id

        for row in data.get("appointments", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"])
            cust_id = id_maps["customers"].get(row["customer_id"], row["customer_id"])
            staff_id = id_maps["staff"].get(row["staff_id"], row["staff_id"])
            created_by = id_maps["users"].get(row["created_by"], row["created_by"])
            appt = Appointment(
                company_id=cid,
                branch_id=bid,
                customer_id=cust_id,
                staff_id=staff_id,
                appointment_date=_parse_dt(row["appointment_date"]),
                status=row.get("status", "scheduled"),
                notes=row.get("notes"),
                checked_in_at=_parse_dt(row.get("checked_in_at")),
                completed_at=_parse_dt(row.get("completed_at")),
                created_by=created_by,
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(appt)
            db.flush()
            if old_id is not None:
                id_maps["appointments"][old_id] = appt.id

        for row in data.get("appointment_services", []):
            appt_id = id_maps["appointments"].get(row["appointment_id"], row["appointment_id"])
            svc_id = id_maps["services"].get(row["service_id"], row["service_id"])
            db.add(AppointmentService(
                appointment_id=appt_id,
                service_id=svc_id,
                quantity=row.get("quantity", 1),
                price=row["price"],
            ))

        for row in data.get("invoices", []):
            old_id = row.pop("id", None)
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"])
            cust_id = id_maps["customers"].get(row["customer_id"], row["customer_id"]) if row.get("customer_id") else None
            appt_id = id_maps["appointments"].get(row["appointment_id"], row["appointment_id"]) if row.get("appointment_id") else None
            created_by = id_maps["users"].get(row["created_by"], row["created_by"])
            inv = Invoice(
                company_id=cid,
                branch_id=bid,
                customer_id=cust_id,
                appointment_id=appt_id,
                invoice_number=row["invoice_number"],
                invoice_date=_parse_dt(row["invoice_date"]),
                subtotal=row["subtotal"],
                discount_amount=row.get("discount_amount", 0),
                tax_amount=row["tax_amount"],
                total_amount=row["total_amount"],
                paid_amount=row.get("paid_amount", 0),
                status=row.get("status", "draft"),
                notes=row.get("notes"),
                created_by=created_by,
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            )
            db.add(inv)
            db.flush()
            if old_id is not None:
                id_maps["invoices"][old_id] = inv.id

        for row in data.get("invoice_items", []):
            inv_id = id_maps["invoices"].get(row["invoice_id"], row["invoice_id"])
            svc_id = id_maps["services"].get(row["service_id"], row["service_id"]) if row.get("service_id") else None
            prod_id = id_maps["products"].get(row["product_id"], row.get("product_id")) if row.get("product_id") else None
            staff_id = id_maps["staff"].get(row["staff_id"], row["staff_id"]) if row.get("staff_id") else None
            db.add(InvoiceItem(
                invoice_id=inv_id,
                service_id=svc_id,
                product_id=prod_id,
                staff_id=staff_id,
                description=row["description"],
                quantity=row.get("quantity", 1),
                unit_price=row["unit_price"],
                discount_amount=row.get("discount_amount", 0),
                tax_rate=row["tax_rate"],
                tax_amount=row["tax_amount"],
                total_amount=row["total_amount"],
                hsn_sac_code=row.get("hsn_sac_code"),
            ))

        for row in data.get("payments", []):
            inv_id = id_maps["invoices"].get(row["invoice_id"], row["invoice_id"])
            created_by = id_maps["users"].get(row["created_by"], row["created_by"])
            db.add(Payment(
                invoice_id=inv_id,
                amount=row["amount"],
                payment_mode=row["payment_mode"],
                transaction_id=row.get("transaction_id"),
                notes=row.get("notes"),
                created_by=created_by,
                created_at=_parse_dt(row.get("created_at")),
            ))

        for row in data.get("attendance", []):
            staff_id = id_maps["staff"].get(row["staff_id"], row["staff_id"])
            db.add(Attendance(
                staff_id=staff_id,
                attendance_date=_parse_dt(row["attendance_date"]),
                status=row["status"],
                check_in_time=_parse_dt(row.get("check_in_time")),
                check_out_time=_parse_dt(row.get("check_out_time")),
                notes=row.get("notes"),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            ))

        for row in data.get("settings_branding", []):
            cid = id_maps["companies"].get(row["company_id"], row["company_id"])
            bid = id_maps["branches"].get(row["branch_id"], row["branch_id"]) if row.get("branch_id") else None
            db.add(BrandingSettings(
                company_id=cid,
                branch_id=bid,
                logo_url=row.get("logo_url"),
                primary_color=row.get("primary_color", "#000000"),
                secondary_color=row.get("secondary_color"),
                invoice_footer_text=row.get("invoice_footer_text"),
                invoice_footer_logo_url=row.get("invoice_footer_logo_url"),
                is_white_label=row.get("is_white_label", False),
                created_at=_parse_dt(row.get("created_at")),
                updated_at=_parse_dt(row.get("updated_at")),
            ))

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}",
        )
    finally:
        try:
            db.execute(text("PRAGMA foreign_keys=ON"))
            db.commit()
        except Exception:
            pass


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Import previously exported salon data. Replaces all data for the current DB
    (full restore). Use when setting up on a new computer.
    
    Automatically runs database migrations to ensure schema compatibility.
    """
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload a .json file from Export Data.",
        )

    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e}",
        )

    if data.get("version") != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported export version.",
        )
    
    # Automatically run database migrations before importing
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        from app.core.logging_config import get_logger
        logger = get_logger("data_import")
        logger.warning(f"Migration check failed (may already be up to date): {str(e)}")

    _run_import(db, data)
    return {
        "message": "Data imported successfully. Database schema has been automatically updated. You can log in with your existing credentials.",
        "migration_applied": True,
    }


