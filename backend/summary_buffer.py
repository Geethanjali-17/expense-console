from __future__ import annotations
import json
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from .models import Expense


def get_spending_summary(db: Session) -> str:
    """Returns compact JSON string (<600 tokens) of recent spending for LLM context."""
    cutoff = date.today() - timedelta(days=30)

    # Category totals
    category_rows = (
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(Expense.expense_date >= cutoff)
        .group_by(Expense.category)
        .all()
    )
    category_totals = {cat or "Uncategorized": round(total, 2) for cat, total in category_rows}

    # Merchant stats (top 20 by frequency)
    merchant_rows = (
        db.query(
            Expense.merchant,
            func.count(Expense.id),
            func.avg(Expense.amount),
            func.max(Expense.expense_date),
        )
        .filter(Expense.expense_date >= cutoff)
        .group_by(Expense.merchant)
        .order_by(func.count(Expense.id).desc())
        .limit(20)
        .all()
    )
    merchant_stats = {
        merchant: {"count": count, "avg_amount": round(avg, 2), "last_seen": str(last)}
        for merchant, count, avg, last in merchant_rows
    }

    return json.dumps({
        "period": "last_30_days",
        "category_totals": category_totals,
        "merchant_stats": merchant_stats,
    })
