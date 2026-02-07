from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    data,
    customers,
    appointments,
    invoices,
    staff,
    reports,
    services,
    attendance,
    leave,
    memberships,
    branches,
    users,
    uploads,
    settings,
    discount_codes,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(data.router, prefix="/data", tags=["data"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
api_router.include_router(appointments.router, prefix="/appointments", tags=["appointments"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
api_router.include_router(staff.router, prefix="/staff", tags=["staff"])
api_router.include_router(services.router, prefix="/services", tags=["services"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(attendance.router, prefix="/attendance", tags=["attendance"])
api_router.include_router(leave.router, prefix="/leaves", tags=["leaves"])
api_router.include_router(memberships.router, prefix="/memberships", tags=["memberships"])
api_router.include_router(branches.router, prefix="/branches", tags=["branches"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(discount_codes.router, prefix="/discount-codes", tags=["discount-codes"])
