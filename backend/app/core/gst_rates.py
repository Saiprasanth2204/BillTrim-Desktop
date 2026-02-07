"""
Hardcoded GST rates (reference data). IDs 1–5 match legacy DB ids for compatibility.
"""
from decimal import Decimal
from typing import List, Optional

# (id, name, cgst_rate, sgst_rate, igst_rate)
_GST_RATES: List[tuple] = [
    (1, "GST 0%", Decimal("0"), Decimal("0"), Decimal("0")),
    (2, "GST 5%", Decimal("2.5"), Decimal("2.5"), Decimal("5")),
    (3, "GST 12%", Decimal("6"), Decimal("6"), Decimal("12")),
    (4, "GST 18%", Decimal("9"), Decimal("9"), Decimal("18")),
    (5, "GST 28%", Decimal("14"), Decimal("14"), Decimal("28")),
]


class GSTRateRow:
    """Simple value object for GST rate (used for API response serialization)."""
    __slots__ = ("id", "name", "cgst_rate", "sgst_rate", "igst_rate")

    def __init__(
        self,
        id: int,
        name: str,
        cgst_rate: Decimal,
        sgst_rate: Decimal,
        igst_rate: Decimal,
    ):
        self.id = id
        self.name = name
        self.cgst_rate = cgst_rate
        self.sgst_rate = sgst_rate
        self.igst_rate = igst_rate


def get_gst_rates() -> List[GSTRateRow]:
    """Return all GST rates."""
    return [
        GSTRateRow(id=r[0], name=r[1], cgst_rate=r[2], sgst_rate=r[3], igst_rate=r[4])
        for r in _GST_RATES
    ]


def get_gst_rate_by_id(gst_rate_id: int) -> Optional[GSTRateRow]:
    """Return the GST rate for the given id, or None if not found."""
    for r in _GST_RATES:
        if r[0] == gst_rate_id:
            return GSTRateRow(id=r[0], name=r[1], cgst_rate=r[2], sgst_rate=r[3], igst_rate=r[4])
    return None


def get_valid_gst_rate_ids() -> List[int]:
    """Return list of valid GST rate ids (for validation)."""
    return [r[0] for r in _GST_RATES]
