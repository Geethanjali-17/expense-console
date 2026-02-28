from __future__ import annotations

import calendar
import json
import statistics
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, extract, or_, text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .expense_parser import parse_expenses_from_message
from .llm_client import llm_client
from .models import Expense
from .schemas import (
    ApprovalDecision,
    CategoryUpdate,
    ChatMessage,
    ChatResponse,
    DashboardSummary,
    DriftInsight,
    DriftResponse,
    ExpenseCreate,
    ExpenseRead,
    SearchQuery,
    SearchResponse,
    StrategicRecommendation,
)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NEW_COLUMNS = [
    ("financial_impact_score", "REAL"),
    ("strategic_insight",      "TEXT"),
    ("ai_reasoning_path",      "TEXT"),
    ("anomaly_flags",          "TEXT"),
    ("requires_approval",      "INTEGER DEFAULT 0"),
    ("approved",               "INTEGER"),
]


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for col, definition in NEW_COLUMNS:
            try:
                conn.execute(text(f"ALTER TABLE expenses ADD COLUMN {col} {definition}"))
                conn.commit()
            except Exception:
                pass  # column already exists


def _find_updatable_expense(
    db: Session,
    pe_amount: float,
    pe_merchant: str,
    pending_id: Optional[int],
) -> Optional[Expense]:
    """
    Return an existing Expense to UPDATE rather than inserting a duplicate.

    Three-priority lookup:
      1. Explicit pending_id supplied by the frontend (most reliable).
      2. Any 'Pending' draft with the same amount created in the last 5 minutes
         — handles the case where the user answers a clarification question.
      3. Exact same merchant + amount created in the last 60 seconds
         — catches re-extraction duplicates from the LLM or regex path.
    """
    # Priority 1: frontend sent back the exact ID of the in-progress expense
    if pending_id:
        row = db.get(Expense, pending_id)
        if row and row.merchant == "Pending":
            return row

    if pe_merchant == "Pending":
        # A new Pending record is intentional; skip the remaining checks.
        return None

    # Priority 2: orphaned Pending draft (same amount, last 5 min)
    cutoff5 = datetime.utcnow() - timedelta(minutes=5)
    draft = (
        db.query(Expense)
        .filter(
            Expense.merchant == "Pending",
            Expense.amount == pe_amount,
            Expense.created_at >= cutoff5,
        )
        .order_by(Expense.created_at.desc())
        .first()
    )
    if draft:
        return draft

    # Priority 3: exact duplicate (same merchant + amount, last 60 s)
    cutoff60 = datetime.utcnow() - timedelta(seconds=60)
    dupe = (
        db.query(Expense)
        .filter(
            func.lower(Expense.merchant) == pe_merchant.lower(),
            Expense.amount == pe_amount,
            Expense.created_at >= cutoff60,
        )
        .order_by(Expense.created_at.desc())
        .first()
    )
    return dupe


@app.post("/chat", response_model=ChatResponse)
async def chat_with_assistant(
    payload: ChatMessage,
    db: Session = Depends(get_db),
):
    """
    Core chat endpoint.
    - Uses LLM reasoning to interpret the message and extract expenses.
    - Runs AI audit and anomaly detection per expense.
    - Persists those expenses with audit metadata.
    - Returns a friendly natural-language confirmation plus structured records.
    """
    history = [h.model_dump() for h in payload.history]
    parse_result = await parse_expenses_from_message(payload.message, history, db)

    saved_expenses: List[Expense] = []

    for pe in parse_result.expenses:
        pe_flags = json.loads(pe.anomaly_flags or "[]")
        requires_approval = (
            pe.amount >= settings.approval_threshold
            or "duplicate_charge" in pe_flags
            or "zombie_subscription" in pe_flags
        )
        # Pending expenses start with approved=False so the approval gate can
        # distinguish them from intentionally-null normal expenses.
        initial_approved = False if requires_approval else None

        # Update-or-create: prefer patching an existing Pending/duplicate record
        existing = _find_updatable_expense(
            db, pe.amount, pe.merchant, payload.pending_expense_id
        )
        if existing:
            existing.merchant = pe.merchant
            existing.category = pe.category or existing.category
            if pe.note:
                existing.note = pe.note
            existing.financial_impact_score = pe.financial_impact_score
            existing.strategic_insight = pe.strategic_insight
            existing.ai_reasoning_path = pe.ai_reasoning_path
            existing.anomaly_flags = pe.anomaly_flags
            existing.requires_approval = requires_approval
            if existing.approved is None:
                existing.approved = initial_approved
            saved_expenses.append(existing)
        else:
            expense = Expense(
                merchant=pe.merchant,
                amount=pe.amount,
                currency=pe.currency or "USD",
                category=pe.category,
                note=pe.note,
                expense_date=pe.expense_date or date.today(),
                financial_impact_score=pe.financial_impact_score,
                strategic_insight=pe.strategic_insight,
                ai_reasoning_path=pe.ai_reasoning_path,
                anomaly_flags=pe.anomaly_flags,
                requires_approval=requires_approval,
                approved=initial_approved,
            )
            db.add(expense)
            saved_expenses.append(expense)

    db.commit()

    for e in saved_expenses:
        db.refresh(e)

    # Build recommendations for expenses with insights
    recommendations: List[StrategicRecommendation] = []
    flagged_expenses: List[Expense] = []
    for e in saved_expenses:
        e_flags = json.loads(e.anomaly_flags or "[]")
        if e.requires_approval:
            flagged_expenses.append(e)
        if e.strategic_insight:
            recommendations.append(
                StrategicRecommendation(
                    expense_id=e.id,
                    insight=e.strategic_insight,
                    anomaly_flags=e_flags,
                    requires_approval=bool(e.requires_approval),
                )
            )

    # Flagged-expense alert takes priority over the generic LLM reply
    if flagged_expenses:
        merchants = ", ".join(e.merchant for e in flagged_expenses)
        e_flags_first = json.loads(flagged_expenses[0].anomaly_flags or "[]")
        if "duplicate_charge" in e_flags_first:
            reason = "a potential duplicate charge"
        elif "zombie_subscription" in e_flags_first:
            reason = "a recurring subscription you may want to review"
        else:
            reason = "a high-value transaction that needs review"
        assistant_message = (
            f"Hold on \u2014 I\u2019ve flagged {merchants} as {reason}. "
            f"It\u2019s been moved to \u2018Pending Approvals\u2019 and won\u2019t count toward your totals until you approve it. "
            f"Head to the Pending Approvals section to Accept or Reject it."
        )
    elif parse_result.reply:
        assistant_message = parse_result.reply
    elif saved_expenses:
        names = ", ".join(
            f"${e.amount:.2f} at {e.merchant}" for e in saved_expenses
        )
        assistant_message = (
            f"Done! I\u2019ve updated the app with your expense\u2014{names}. "
            "Is there anything else you\u2019d like to log?"
        )
    else:
        assistant_message = (
            "I didn\u2019t catch a clear expense in that message. "
            "Try something like \u201cI spent $30 at Starbucks.\u201d "
            "Is there anything else I can help with?"
        )

    # Surface the pending expense ID so the frontend can pass it back
    # with the next message — enabling the explicit update path.
    pending_expense_id: Optional[int] = None
    if parse_result.needs_clarification:
        pending_ids = [e.id for e in saved_expenses if e.merchant == "Pending"]
        pending_expense_id = pending_ids[0] if pending_ids else None

    return ChatResponse(
        success=True,
        assistant_message=assistant_message,
        expenses=[ExpenseRead.from_orm(e) for e in saved_expenses],
        recommendations=recommendations,
        needs_clarification=parse_result.needs_clarification,
        pending_expense_id=pending_expense_id,
    )


@app.get("/expenses/recent", response_model=List[ExpenseRead])
def get_recent_expenses(limit: int = 20, db: Session = Depends(get_db)):
    q = (
        db.query(Expense)
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .limit(limit)
    )
    return [ExpenseRead.from_orm(e) for e in q.all()]  # type: ignore[arg-type]


@app.get("/dashboard/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    today = date.today()

    # Only count expenses that are not sitting in the approval queue.
    # requires_approval=False covers both normal expenses (approved=None)
    # and previously-flagged ones that the user has since approved (approved=True).
    def approved_only(q):
        return q.filter(Expense.requires_approval == False)  # noqa: E712

    today_total = (
        approved_only(
            db.query(func.coalesce(func.sum(Expense.amount), 0.0))
            .filter(Expense.expense_date == today)
        )
        .scalar()
        or 0.0
    )

    month_total = (
        approved_only(
            db.query(func.coalesce(func.sum(Expense.amount), 0.0))
            .filter(extract("year", Expense.expense_date) == today.year)
            .filter(extract("month", Expense.expense_date) == today.month)
        )
        .scalar()
        or 0.0
    )

    recent = (
        approved_only(db.query(Expense))
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .limit(200)
        .all()
    )

    return DashboardSummary(
        today_total=today_total,
        month_total=month_total,
        recent_expenses=[ExpenseRead.from_orm(e) for e in recent],  # type: ignore[arg-type]
    )


@app.post("/search", response_model=SearchResponse)
async def search_expenses_route(
    payload: SearchQuery,
    db: Session = Depends(get_db),
):
    """
    AI-powered natural-language search over expenses.
    Translates the query into structured DB filters (via LLM or local
    concept map) and returns matching expenses.
    """
    filters = await llm_client.search_expenses(payload.query)

    q = db.query(Expense).filter(Expense.requires_approval == False)  # noqa: E712

    # Merchant / category OR filter
    merchant_names: list[str] = filters.get("merchants") or []
    cat_names: list[str] = filters.get("categories") or []
    or_conditions = (
        [Expense.merchant.ilike(f"%{m}%") for m in merchant_names]
        + [Expense.category.ilike(f"%{c}%") for c in cat_names]
    )
    if or_conditions:
        q = q.filter(or_(*or_conditions))

    # Date range
    if filters.get("date_from"):
        q = q.filter(Expense.expense_date >= date.fromisoformat(filters["date_from"]))
    if filters.get("date_to"):
        q = q.filter(Expense.expense_date <= date.fromisoformat(filters["date_to"]))

    # Amount range
    if filters.get("amount_min") is not None:
        q = q.filter(Expense.amount >= filters["amount_min"])
    if filters.get("amount_max") is not None:
        q = q.filter(Expense.amount <= filters["amount_max"])

    results = (
        q.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .limit(200)
        .all()
    )

    total = sum(e.amount for e in results)
    base_summary = filters.get("summary_text", "")
    if results:
        n = len(results)
        summary_text = (
            f"{base_summary} — {n} expense{'s' if n != 1 else ''} "
            f"totaling ${total:,.2f}"
        )
    else:
        summary_text = "No expenses found matching your search."

    return SearchResponse(
        expenses=[ExpenseRead.from_orm(e) for e in results],
        summary_text=summary_text,
    )


def _prev_months(year: int, month: int, n: int) -> list[tuple[int, int]]:
    """Return (year, month) tuples for the *n* months before (year, month)."""
    result = []
    for i in range(1, n + 1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        result.append((y, m))
    return result


def _calculate_category_drifts(db: Session) -> list[dict]:
    """
    For every category with current-month spending, compute the drift
    against the median of the previous 3 months.
    """
    today = date.today()
    cur_y, cur_m = today.year, today.month

    current_totals = (
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(
            extract("year", Expense.expense_date) == cur_y,
            extract("month", Expense.expense_date) == cur_m,
            Expense.requires_approval == False,  # noqa: E712
            Expense.category.isnot(None),
        )
        .group_by(Expense.category)
        .all()
    )

    prev = _prev_months(cur_y, cur_m, 3)
    drifts: list[dict] = []

    for category, current_total in current_totals:
        if not category or category == "Uncategorized":
            continue
        monthly_totals: list[float] = []
        for py, pm in prev:
            total = (
                db.query(func.coalesce(func.sum(Expense.amount), 0.0))
                .filter(
                    extract("year", Expense.expense_date) == py,
                    extract("month", Expense.expense_date) == pm,
                    Expense.category == category,
                    Expense.requires_approval == False,  # noqa: E712
                )
                .scalar()
            ) or 0.0
            monthly_totals.append(float(total))

        median_total = statistics.median(monthly_totals)
        if median_total > 0:
            drift_pct = ((current_total - median_total) / median_total) * 100
        elif current_total > 0:
            drift_pct = 100.0
        else:
            drift_pct = 0.0

        drifts.append({
            "category": category,
            "current_total": round(float(current_total), 2),
            "median_total": round(median_total, 2),
            "drift_pct": round(drift_pct, 1),
        })

    drifts.sort(key=lambda d: abs(d["drift_pct"]), reverse=True)
    return drifts


@app.get("/drift", response_model=DriftResponse)
async def get_drift_analysis(db: Session = Depends(get_db)):
    """
    Financial Drift Engine — compare current month spending against
    the median of the previous 3 months per category and return
    LLM-powered (or local-fallback) Wealthsimple-tone insights.
    """
    today = date.today()
    period = f"{calendar.month_name[today.month]} {today.year}"

    drifts = _calculate_category_drifts(db)
    if not drifts:
        return DriftResponse(insights=[], period=period)

    top = drifts[:6]
    llm_insights = await llm_client.analyze_drift(top)

    insights: list[DriftInsight] = []
    for raw, llm_row in zip(top, llm_insights):
        insights.append(DriftInsight(
            category=raw["category"],
            current_total=raw["current_total"],
            median_total=raw["median_total"],
            drift_pct=raw["drift_pct"],
            insight=llm_row.get("insight", ""),
            action=llm_row.get("action", ""),
            status=llm_row.get("status", "stable"),
        ))

    return DriftResponse(insights=insights, period=period)


@app.get("/approvals", response_model=List[ExpenseRead])
def get_pending_approvals(db: Session = Depends(get_db)):
    """Return expenses sitting in the approval queue (flagged but not yet decided)."""
    rows = (
        db.query(Expense)
        .filter(
            Expense.requires_approval == True,  # noqa: E712
            Expense.approved == False,           # noqa: E712
        )
        .order_by(Expense.created_at.desc())
        .all()
    )
    return [ExpenseRead.from_orm(e) for e in rows]


@app.patch("/expenses/{expense_id}/category", response_model=ExpenseRead)
def update_expense_category(
    expense_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
):
    """Update the category of a single expense."""
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")
    expense.category = payload.category
    db.commit()
    db.refresh(expense)
    return ExpenseRead.from_orm(expense)


@app.post("/approvals/{expense_id}/decide", response_model=ExpenseRead)
def decide_approval(
    expense_id: int,
    payload: ApprovalDecision,
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    if payload.decision == "approve":
        # Move into the main list: clear the gate flags.
        expense.approved = True
        expense.requires_approval = False
        db.commit()
        db.refresh(expense)
        return ExpenseRead.from_orm(expense)
    else:
        # Reject — capture data then hard-delete so it never hits charts.
        snapshot = ExpenseRead.from_orm(expense)
        db.delete(expense)
        db.commit()
        return snapshot
