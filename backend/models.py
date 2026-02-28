from datetime import datetime, date

from sqlalchemy import Boolean, Column, Integer, String, Date, DateTime, Float

from .database import Base


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    merchant = Column(String, index=True, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    category = Column(String, nullable=True)
    note = Column(String, nullable=True)
    expense_date = Column(Date, default=date.today, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    financial_impact_score = Column(Float, nullable=True)
    strategic_insight = Column(String, nullable=True)
    ai_reasoning_path = Column(String, nullable=True)
    anomaly_flags = Column(String, nullable=True)
    requires_approval = Column(Boolean, default=False)
    approved = Column(Boolean, nullable=True)


