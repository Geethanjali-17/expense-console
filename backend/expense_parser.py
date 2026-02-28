from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from . import anomaly_detector as anomaly_detector_module
from .llm_client import llm_client
from .models import Expense as ExpenseModel
from .schemas import ParsedExpense
from .summary_buffer import get_spending_summary


def _lifestyle_insight(merchant: str, category: str) -> str:
    """Return a friendly lifestyle observation for repeat high-frequency visits."""
    m = merchant.lower()
    if any(kw in m for kw in ("coffee", "starbucks", "tim horton", "second cup", "dunkin", "tims")):
        return (
            "Double caffeine hit today \u2014 your wallet noticed, even if you needed it! "
            "Two coffee runs a day adds up to ~$1,800/year."
        )
    if any(kw in m for kw in ("mcdonald", "burger king", "wendy", "harvey", "taco bell",
                               "popeyes", "chipotle", "subway")):
        return (
            "Two quick meals out today \u2014 happens to the best of us. "
            "Meal prepping a few days a week can cut this cost in half."
        )
    if any(kw in m for kw in ("uber", "lyft", "ttc", "presto", "transit", "translink")):
        return (
            "Two rides today \u2014 you're on the move! "
            "Check if a daily pass would have saved you money."
        )
    if any(kw in m for kw in ("petro", "esso", "shell", "bp", "gas", "ultramar")):
        return "Two gas stops today \u2014 long day on the road?"
    return (
        f"Looks like you visited {merchant} twice today \u2014 "
        "totally fine, just keeping tabs for your records."
    )

logger = logging.getLogger(__name__)

# ── Savings-advice intent detection ──────────────────────────────────────────

_SAVINGS_RE = re.compile(
    r'save\s+money|saving\s+money|'
    r'cut\s+(?:back|down|spending|costs?)|'
    r'reduce\s+(?:my\s+)?(?:spending|expenses?|costs?)|'
    r'where\s+(?:can|should|am|do)\s+i\s+(?:save|cut|reduce|spend\s+less)|'
    r'how\s+(?:can|should|do)\s+i\s+(?:save|reduce|cut|spend\s+less)|'
    r'(?:biggest|largest|top)\s+expenses?|most\s+expensive|'
    r'where\s+(?:does|is|are)\s+(?:my\s+)?(?:money|spending|expenses?)\s+go|'
    r'where\s+(?:does|is)\s+my\s+money|money\s+going|'
    r'(?:spending|expense)\s+(?:breakdown|analysis|report|summary|review)|'
    r'(?:financial|budget)\s+(?:advice|tips?|help|review)|'
    r'overspend|too\s+much\s+on|spend\s+less|audit\s+my\s+spend',
    re.IGNORECASE,
)


def _is_savings_question(message: str) -> bool:
    """Return True when the message is asking for financial advice, not logging an expense."""
    # If there's a clear monetary amount it's almost certainly an expense log
    if re.search(r'\$\s*\d|\b\d+\s*(?:dollars?|bucks?|cad|usd)\b', message, re.IGNORECASE):
        return False
    return bool(_SAVINGS_RE.search(message))


def _build_savings_analytics(db: Session) -> dict:
    """
    Gather category drift, top merchants, and subscription data from the DB.
    Returns a compact dict passed to the LLM (or local fallback) for advice.
    """
    today = date.today()
    cur_y, cur_m = today.year, today.month

    # Category totals this month
    current_rows = (
        db.query(ExpenseModel.category, func.sum(ExpenseModel.amount))
        .filter(
            extract("year", ExpenseModel.expense_date) == cur_y,
            extract("month", ExpenseModel.expense_date) == cur_m,
            ExpenseModel.requires_approval == False,  # noqa: E712
        )
        .group_by(ExpenseModel.category)
        .all()
    )

    # Previous 3 calendar months
    prev_months: list[tuple[int, int]] = []
    for i in range(1, 4):
        m = cur_m - i
        y = cur_y
        while m <= 0:
            m += 12
            y -= 1
        prev_months.append((y, m))

    category_breakdown: list[dict] = []
    month_total = 0.0
    for cat, cur_total in current_rows:
        if not cat:
            continue
        month_total += float(cur_total)
        prev_totals: list[float] = []
        for py, pm in prev_months:
            val = (
                db.query(func.coalesce(func.sum(ExpenseModel.amount), 0.0))
                .filter(
                    extract("year", ExpenseModel.expense_date) == py,
                    extract("month", ExpenseModel.expense_date) == pm,
                    ExpenseModel.category == cat,
                    ExpenseModel.requires_approval == False,  # noqa: E712
                )
                .scalar()
            ) or 0.0
            prev_totals.append(float(val))
        median_val = statistics.median(prev_totals) if prev_totals else 0.0
        drift_pct = (
            ((float(cur_total) - median_val) / median_val * 100) if median_val > 0 else 0.0
        )
        category_breakdown.append({
            "category": cat,
            "this_month": round(float(cur_total), 2),
            "3mo_median": round(median_val, 2),
            "drift_pct": round(drift_pct, 1),
        })
    category_breakdown.sort(key=lambda x: x["this_month"], reverse=True)

    # Top 5 merchants this month by total
    month_start = date(cur_y, cur_m, 1)
    top_merchants = (
        db.query(
            ExpenseModel.merchant,
            func.sum(ExpenseModel.amount),
            func.count(ExpenseModel.id),
        )
        .filter(
            ExpenseModel.expense_date >= month_start,
            ExpenseModel.requires_approval == False,  # noqa: E712
        )
        .group_by(ExpenseModel.merchant)
        .order_by(func.sum(ExpenseModel.amount).desc())
        .limit(5)
        .all()
    )

    # Active subscriptions this month
    subscriptions = (
        db.query(ExpenseModel.merchant, ExpenseModel.amount)
        .filter(
            ExpenseModel.category == "subscriptions",
            extract("year", ExpenseModel.expense_date) == cur_y,
            extract("month", ExpenseModel.expense_date) == cur_m,
        )
        .all()
    )

    return {
        "period": today.strftime("%B %Y"),
        "month_total": round(month_total, 2),
        "category_breakdown": category_breakdown,
        "top_merchants": [
            {"merchant": m, "total": round(float(t), 2), "visits": int(v)}
            for m, t, v in top_merchants
        ],
        "subscriptions": [
            {"merchant": m, "amount": round(float(a), 2)} for m, a in subscriptions
        ],
        "subscriptions_total": round(sum(float(a) for _, a in subscriptions), 2),
        "drift_warnings": [
            {
                "category": c["category"],
                "drift_pct": c["drift_pct"],
                "this_month": c["this_month"],
                "3mo_median": c["3mo_median"],
            }
            for c in category_breakdown
            if abs(c["drift_pct"]) >= 15 and c["3mo_median"] > 0
        ],
    }


async def _run_savings_pipeline(message: str, db: Session) -> "ParseResult":
    """Query the DB for real analytics and ask the LLM for personalised advice."""
    try:
        analytics = _build_savings_analytics(db)
        advice = await llm_client.get_savings_advice(message, analytics)
    except Exception as exc:
        logger.exception("Savings pipeline error: %s", exc)
        advice = "I had trouble pulling your spending data. Try asking again in a moment."
    return ParseResult(
        expenses=[],
        reply=advice,
        needs_clarification=False,
        follow_up_question=None,
    )


@dataclass
class ParseResult:
    expenses: List[ParsedExpense]
    reply: str
    needs_clarification: bool = False
    follow_up_question: Optional[str] = None


def _safe_fallback(message: str = "") -> ParseResult:
    """Return a graceful ParseResult when the whole pipeline fails unexpectedly."""
    return ParseResult(
        expenses=[],
        reply=message or "I had trouble processing that. Could you rephrase it?",
        needs_clarification=True,
        follow_up_question=None,
    )


async def parse_expenses_from_message(
    message: str,
    history: List[Dict[str, Any]],
    db: Session,
) -> ParseResult:
    """
    Full pipeline:
      1. Ask LLM to extract expenses + generate a conversational reply.
      2. Enrich each expense with anomaly flags and an AI financial audit.
      3. Return a ParseResult with the enriched expenses and the LLM reply.

    The outer try-except guarantees that no uncaught exception ever propagates
    to FastAPI as a 500 — the user always receives a graceful message.
    """
    try:
        return await _run_pipeline(message, history, db)
    except Exception as exc:
        logger.exception("Unexpected error in parse_expenses_from_message: %s", exc)
        return _safe_fallback()


async def _run_pipeline(
    message: str,
    history: List[Dict[str, Any]],
    db: Session,
) -> ParseResult:
    """Inner pipeline — called by parse_expenses_from_message inside a safety net."""
    # Savings / advice intent — skip expense extraction and query the DB directly
    if _is_savings_question(message):
        return await _run_savings_pipeline(message, db)

    try:
        llm_result = await llm_client.extract_expenses(message, history)
    except Exception as exc:
        logger.exception("LLM extract_expenses raised unexpectedly: %s", exc)
        return _safe_fallback()

    raw_expenses: List[dict] = llm_result.get("expenses") or []
    # Accept both 'assistant_message' (current) and 'reply' (legacy key)
    assistant_message: str = (
        llm_result.get("assistant_message")
        or llm_result.get("reply")
        or ""
    )
    needs_clarification: bool = bool(llm_result.get("needs_clarification", False))
    follow_up_question: Optional[str] = llm_result.get("follow_up_question") or None

    if not raw_expenses:
        return ParseResult(
            expenses=[],
            reply=assistant_message,
            needs_clarification=needs_clarification,
            follow_up_question=follow_up_question,
        )

    # Get one spending summary to reuse for all expenses in this message
    try:
        summary = get_spending_summary(db)
    except Exception as exc:
        logger.warning("get_spending_summary failed: %s", exc)
        summary = "{}"

    today = date.today()
    parsed: List[ParsedExpense] = []

    for item in raw_expenses:
        try:
            pe = ParsedExpense(
                merchant=item.get("merchant") or "Pending",
                amount=float(item.get("amount") or 0),
                currency=item.get("currency") or "USD",
                category=item.get("category") or "Uncategorized",
                note=item.get("note"),
                expense_date=item.get("expense_date") or today,
            )
            # Coerce string dates
            if isinstance(pe.expense_date, str):
                try:
                    pe.expense_date = date.fromisoformat(pe.expense_date)
                except ValueError:
                    pe.expense_date = today
            if not pe.expense_date:
                pe.expense_date = today

            # Anomaly detection
            try:
                flags = anomaly_detector_module.detect_anomalies(pe.merchant, pe.amount, db)
            except Exception:
                flags = []
            pe.anomaly_flags = json.dumps(flags)

            # Duplicate charge — hardcode high-severity audit; skip LLM call
            if "duplicate_charge" in flags:
                pe.financial_impact_score = 80
                pe.strategic_insight = (
                    "Duplicate charges detected. This is a common 'financial leak' "
                    "that costs users an average of $150/year in unused services."
                )
                pe.ai_reasoning_path = (
                    "Rule-based: same merchant with similar amount already logged today."
                )
            elif "lifestyle_repeat" in flags:
                # High-frequency repeat that is NOT a duplicate — give a friendly nudge,
                # not an alert.  Clear the flag so it never triggers the approval gate.
                pe.financial_impact_score = 15
                pe.strategic_insight = _lifestyle_insight(pe.merchant, pe.category or "")
                pe.ai_reasoning_path = "lifestyle_repeat"
                pe.anomaly_flags = json.dumps([])   # no chip, no approval needed
            else:
                # AI audit
                try:
                    audit = await llm_client.audit_expense(item, summary)
                except Exception:
                    audit = {"financial_impact_score": 0, "strategic_insight": "", "ai_reasoning_path": ""}
                pe.financial_impact_score = audit["financial_impact_score"]
                pe.strategic_insight = audit["strategic_insight"]
                pe.ai_reasoning_path = audit["ai_reasoning_path"]

                # If Uncategorized, nudge via strategic_insight
                if pe.category == "Uncategorized" and not pe.strategic_insight:
                    pe.strategic_insight = (
                        "Category is unset — consider updating it so your reports stay accurate."
                    )

            parsed.append(pe)
        except Exception as exc:
            logger.warning("Skipping malformed expense item %s: %s", item, exc)
            continue

    return ParseResult(
        expenses=parsed,
        reply=assistant_message,
        needs_clarification=needs_clarification,
        follow_up_question=follow_up_question,
    )
