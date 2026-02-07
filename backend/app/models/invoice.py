from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Boolean, Enum as SQLEnum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class PaymentModeEnum(str, enum.Enum):
    CASH = "cash"
    CARD = "card"
    UPI = "upi"
    BANK_TRANSFER = "bank_transfer"
    WALLET = "wallet"
    CREDIT = "credit"


class InvoiceStatusEnum(str, enum.Enum):
    DRAFT = "draft"
    PAID = "paid"
    PARTIAL = "partial"
    PENDING = "pending"
    VOID = "void"
    REFUNDED = "refunded"

    @classmethod
    def normalize(cls, value):
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            value_lower = value.lower()
            mapping = {
                'draft': cls.DRAFT, 'paid': cls.PAID, 'partial': cls.PARTIAL,
                'pending': cls.PENDING, 'void': cls.VOID, 'refunded': cls.REFUNDED,
            }
            if value_lower in mapping:
                return mapping[value_lower]
            try:
                return cls(value)
            except ValueError:
                pass
        raise ValueError(f"Invalid invoice status: {value}")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True, unique=True)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    invoice_date = Column(DateTime(timezone=True), nullable=False, index=True)
    subtotal = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0.00)
    tax_amount = Column(Numeric(12, 2), nullable=False)
    total_amount = Column(Numeric(12, 2), nullable=False)
    paid_amount = Column(Numeric(12, 2), default=0.00)
    status = Column(SQLEnum(InvoiceStatusEnum, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=False, default=InvoiceStatusEnum.DRAFT)
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    branch = relationship("Branch", back_populates="invoices")
    customer = relationship("Customer", back_populates="invoices")
    appointment = relationship("Appointment", back_populates="invoice")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    description = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=False)
    discount_amount = Column(Numeric(10, 2), default=0.00)
    tax_rate = Column(Numeric(5, 2), nullable=False)
    tax_amount = Column(Numeric(10, 2), nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    hsn_sac_code = Column(String(10), nullable=True)

    invoice = relationship("Invoice", back_populates="items")
    service = relationship("Service", back_populates="invoice_items")
    product = relationship("Product", back_populates="invoice_items")
    staff = relationship("Staff", back_populates="invoice_items")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_mode = Column(SQLEnum(PaymentModeEnum, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=False)
    transaction_id = Column(String(100), nullable=True)
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invoice = relationship("Invoice", back_populates="payments")
