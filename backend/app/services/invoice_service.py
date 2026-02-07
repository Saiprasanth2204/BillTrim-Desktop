"""
Invoice Service for BillTrim Desktop

Provides utility functions for invoice operations including:
- Invoice number generation
- GST calculation
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.invoice import Invoice
from app.core.gst_rates import get_gst_rate_by_id, GSTRateRow
from app.core.logging_config import get_logger

logger = get_logger("invoice_service")


def generate_invoice_number(db: Session, company_id: int, branch_id: int) -> str:
    """
    Generate a unique invoice number for a company/branch.
    
    Format: INV-YYYYMMDD-XXX
    Where:
    - INV: Invoice prefix
    - YYYYMMDD: Date in format YYYYMMDD
    - XXX: Sequential number for that day (001, 002, etc.)
    
    Args:
        db: Database session
        company_id: Company ID
        branch_id: Branch ID
        
    Returns:
        Unique invoice number string
    """
    try:
        today = datetime.utcnow().date()
        date_prefix = today.strftime("%Y%m%d")
        
        # Find the highest sequential number for today's invoices for this company/branch
        # Query invoices that start with INV-YYYYMMDD-
        prefix_pattern = f"INV-{date_prefix}-"
        
        # Get all invoice numbers for today for this company/branch
        existing_invoices = db.query(Invoice.invoice_number).filter(
            Invoice.company_id == company_id,
            Invoice.branch_id == branch_id,
            Invoice.invoice_number.like(f"{prefix_pattern}%")
        ).all()
        
        # Extract sequential numbers and find the max
        max_seq = 0
        for inv_num_tuple in existing_invoices:
            inv_num = inv_num_tuple[0]
            try:
                # Extract the sequential part after the last dash
                seq_part = inv_num.split("-")[-1]
                seq_num = int(seq_part)
                max_seq = max(max_seq, seq_num)
            except (ValueError, IndexError):
                # If parsing fails, skip this invoice number
                logger.warning(f"Could not parse invoice number: {inv_num}")
                continue
        
        # Generate next sequential number
        next_seq = max_seq + 1
        invoice_number = f"{prefix_pattern}{next_seq:03d}"
        
        logger.info(
            f"Generated invoice number: {invoice_number}",
            extra={
                "company_id": company_id,
                "branch_id": branch_id,
                "date_prefix": date_prefix,
                "sequence": next_seq
            }
        )
        
        return invoice_number
        
    except Exception as e:
        logger.error(
            f"Error generating invoice number: {str(e)}",
            exc_info=True,
            extra={"company_id": company_id, "branch_id": branch_id}
        )
        # Fallback: use timestamp-based number if generation fails
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        fallback_number = f"INV-{timestamp}"
        logger.warning(f"Using fallback invoice number: {fallback_number}")
        return fallback_number


def calculate_gst(
    amount: Decimal,
    gst_rate_id: Optional[int] = None,
    tax_rate: Optional[Decimal] = None,
    use_igst: bool = False
) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Calculate GST (CGST, SGST, IGST) for a given amount.
    
    Args:
        amount: Base amount (before tax)
        gst_rate_id: GST rate ID from gst_rates (optional, takes precedence over tax_rate)
        tax_rate: Tax rate as percentage (e.g., 18.0 for 18%) (optional)
        use_igst: If True, use IGST instead of CGST+SGST (for inter-state transactions)
        
    Returns:
        Tuple[Decimal, Decimal, Decimal]: (cgst_amount, sgst_amount, igst_amount)
        - For intra-state: (cgst, sgst, 0)
        - For inter-state: (0, 0, igst)
        
    Note:
        If gst_rate_id is provided, it takes precedence over tax_rate.
        If neither is provided, returns (0, 0, 0).
    """
    try:
        cgst_amount = Decimal("0.00")
        sgst_amount = Decimal("0.00")
        igst_amount = Decimal("0.00")
        
        # Get GST rate from ID if provided
        if gst_rate_id:
            gst_rate = get_gst_rate_by_id(gst_rate_id)
            if gst_rate:
                if use_igst:
                    # Inter-state: use IGST
                    igst_rate = gst_rate.igst_rate
                    igst_amount = amount * (igst_rate / Decimal("100"))
                else:
                    # Intra-state: use CGST + SGST
                    cgst_amount = amount * (gst_rate.cgst_rate / Decimal("100"))
                    sgst_amount = amount * (gst_rate.sgst_rate / Decimal("100"))
        elif tax_rate is not None:
            # Use provided tax_rate (assumed to be total GST rate)
            tax_rate_decimal = Decimal(str(tax_rate))
            if use_igst:
                # Inter-state: use IGST
                igst_amount = amount * (tax_rate_decimal / Decimal("100"))
            else:
                # Intra-state: split equally between CGST and SGST
                half_rate = tax_rate_decimal / Decimal("2")
                cgst_amount = amount * (half_rate / Decimal("100"))
                sgst_amount = amount * (half_rate / Decimal("100"))
        
        return (cgst_amount, sgst_amount, igst_amount)
        
    except Exception as e:
        logger.error(
            f"Error calculating GST: {str(e)}",
            exc_info=True,
            extra={
                "amount": str(amount),
                "gst_rate_id": gst_rate_id,
                "tax_rate": str(tax_rate) if tax_rate else None,
                "use_igst": use_igst
            }
        )
        # Return zero GST on error
        return (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
