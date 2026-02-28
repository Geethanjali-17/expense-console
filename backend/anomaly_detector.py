from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .models import Expense

# ---------------------------------------------------------------------------
# Merchants that legitimately visit multiple times per day.
# For these, only flag a duplicate if the amount is IDENTICAL and the gap is
# under 5 minutes (classic accidental double-tap).  Any other same-day repeat
# is treated as a "lifestyle_repeat" — an insight, not an alert.
# ---------------------------------------------------------------------------
_HIGH_FREQUENCY_MERCHANTS: frozenset[str] = frozenset({
    # Coffee
    "tim hortons", "starbucks", "second cup", "dunkin", "dunkin donuts",
    "coffee fellows", "blenz", "tims", "timmies",
    # Fast food
    "mcdonald's", "mcdonalds", "mcdonald", "burger king", "wendy's", "wendys",
    "harvey's", "harveys", "a&w", "a&w canada",
    "taco bell", "subway", "chipotle", "popeyes",
    # Ride-share / transit
    "uber", "lyft", "ttc", "presto", "translink", "octranspo", "stm",
    # Gas / convenience
    "7-eleven", "7 eleven", "circle k",
    "petro-canada", "petro canada", "esso", "shell", "bp", "ultramar",
})

_HIGH_FREQ_KEYWORDS: tuple[str, ...] = (
    "coffee", "cafe", "cafè", "transit", "presto", "parking",
)

# Merchant names to skip entirely — they are parser placeholders, not real merchants.
_PLACEHOLDER_MERCHANTS: frozenset[str] = frozenset({
    "pending", "unknown", "n/a", "tbd", "",
})


def _is_high_frequency(merchant_lower: str) -> bool:
    """Return True if this merchant legitimately appears multiple times a day."""
    if merchant_lower in _HIGH_FREQUENCY_MERCHANTS:
        return True
    return any(kw in merchant_lower for kw in _HIGH_FREQ_KEYWORDS)


def detect_anomalies(merchant: str, amount: float, db: Session) -> list[str]:
    """
    Returns a list of anomaly flags for a single *new* (not-yet-saved) expense.

    Flags:
      duplicate_charge   — accidental double entry (same merchant + close amount + recent)
      lifestyle_repeat   — intentional repeat at a high-freq place (coffee, fast food, …)
      zombie_subscription— recurring fixed-price service appearing 2+ times in 30 days
      price_creep        — current amount is >10 % above the historic median
    """
    stripped = merchant.strip()

    # Skip placeholder / empty merchants to avoid false positives
    if not stripped or len(stripped) < 3 or stripped.lower() in _PLACEHOLDER_MERCHANTS:
        return []

    today = date.today()
    now = datetime.utcnow()          # matches models.py: created_at = datetime.utcnow
    merchant_lower = stripped.lower()
    is_hf = _is_high_frequency(merchant_lower)

    # All charges at this merchant made today (already in DB)
    same_today = (
        db.query(Expense)
        .filter(Expense.merchant.ilike(f"%{stripped}%"))
        .filter(Expense.expense_date == today)
        .all()
    )

    flags: list[str] = []

    # ── HIGH-FREQUENCY branch ────────────────────────────────────────────────
    if is_hf:
        for existing in same_today:
            if existing.created_at is None:
                continue
            minutes_apart = abs((now - existing.created_at).total_seconds()) / 60
            # Only a true duplicate if the amount is identical and gap ≤ 5 min
            if abs(amount - existing.amount) < 0.01 and minutes_apart <= 5:
                flags.append("duplicate_charge")
                break

        # Same-day repeat that is NOT an exact duplicate → lifestyle insight
        if not flags and same_today:
            flags.append("lifestyle_repeat")

        return flags

    # ── REGULAR MERCHANT branch ──────────────────────────────────────────────
    # Duplicate: similar amount (within 15 %) logged within the last 2 hours
    for existing in same_today:
        if existing.created_at is None:
            continue
        hours_apart = abs((now - existing.created_at).total_seconds()) / 3600
        if (
            hours_apart <= 2
            and amount > 0
            and abs(existing.amount - amount) / amount <= 0.15
        ):
            flags.append("duplicate_charge")
            break

    # If already flagged as duplicate, skip the rest
    if flags:
        return flags

    # Zombie subscription: 2+ charges in last 30 days with consistent pricing
    cutoff_30 = today - timedelta(days=30)
    recent = (
        db.query(Expense)
        .filter(Expense.merchant.ilike(f"%{stripped}%"))
        .filter(Expense.expense_date >= cutoff_30)
        .all()
    )

    if len(recent) >= 2:
        amounts_hist = [e.amount for e in recent]
        med = statistics.median(amounts_hist)
        # Only flag zombie if it looks like a recurring fixed-price charge (within 5 %)
        if med > 0 and all(abs(a - med) / med <= 0.05 for a in amounts_hist):
            flags.append("zombie_subscription")

    # Price creep: current amount > 10 % above the historic median
    if recent:
        med_val = statistics.median([e.amount for e in recent])
        if med_val > 0 and amount > med_val * 1.10:
            flags.append("price_creep")

    return flags
