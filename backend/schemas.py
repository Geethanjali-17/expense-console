from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    merchant: str
    amount: float
    currency: str = "USD"
    category: Optional[str] = None
    note: Optional[str] = None
    expense_date: date


class ExpenseRead(ExpenseCreate):
    id: int
    created_at: datetime
    financial_impact_score: Optional[float] = None
    strategic_insight: Optional[str] = None
    ai_reasoning_path: Optional[str] = None
    anomaly_flags: Optional[str] = None
    requires_approval: bool = False
    approved: Optional[bool] = None

    class Config:
        from_attributes = True


class ChatHistoryItem(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatMessage(BaseModel):
    message: str = Field(..., description="Raw user message in natural language")
    history: List["ChatHistoryItem"] = Field(default_factory=list)
    pending_expense_id: Optional[int] = None  # ID of the in-progress expense awaiting clarification


class ParsedExpense(BaseModel):
    merchant: str
    amount: float
    currency: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = None
    expense_date: Optional[date] = None
    financial_impact_score: Optional[float] = None
    strategic_insight: Optional[str] = None
    ai_reasoning_path: Optional[str] = None
    anomaly_flags: Optional[str] = None  # JSON string
    needs_clarification: bool = False
    follow_up_question: Optional[str] = None


class StrategicRecommendation(BaseModel):
    expense_id: int
    insight: str
    anomaly_flags: List[str]
    requires_approval: bool


class ChatResponse(BaseModel):
    success: bool = True
    assistant_message: str
    expenses: List[ExpenseRead]
    recommendations: List[StrategicRecommendation]
    needs_clarification: bool = False
    pending_expense_id: Optional[int] = None  # Returned when a clarification is pending


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]


class AnalyticsSummary(BaseModel):
    date: date
    total: float


class DashboardSummary(BaseModel):
    today_total: float
    month_total: float
    recent_expenses: List[ExpenseRead]


class SearchQuery(BaseModel):
    query: str = Field(..., description="Natural language search query about spending")


class SearchResponse(BaseModel):
    expenses: List[ExpenseRead]
    summary_text: str


class DriftInsight(BaseModel):
    category: str
    current_total: float
    median_total: float
    drift_pct: float
    insight: str
    action: str
    status: Literal["warning", "stable", "improving"]


class DriftResponse(BaseModel):
    insights: List[DriftInsight]
    period: str
