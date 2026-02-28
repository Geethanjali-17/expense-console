from datetime import date
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.main import app  # type: ignore  # noqa: E402
from backend import llm_client as llm_module  # type: ignore  # noqa: E402
from backend import anomaly_detector  # type: ignore  # noqa: E402


async def fake_audit_expense(expense: dict, spending_summary: str) -> dict:
    return {
        "financial_impact_score": 30,
        "strategic_insight": "Test insight.",
        "ai_reasoning_path": "CoT.",
    }


def fake_detect_anomalies(merchant: str, amount: float, db) -> list:
    return []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(llm_module.llm_client, "audit_expense", fake_audit_expense)
    monkeypatch.setattr(anomaly_detector, "detect_anomalies", fake_detect_anomalies)
    with TestClient(app) as c:
        yield c


def test_chat_parses_and_saves_expenses(client, monkeypatch):
    async def fake_extract_expenses(message: str, history=None):
        return {
            "expenses": [
                {
                    "merchant": "Walmart",
                    "amount": 70,
                    "currency": "USD",
                    "category": "groceries",
                    "note": "weekly groceries",
                    "expense_date": date.today().isoformat(),
                },
                {
                    "merchant": "Apple",
                    "amount": 20,
                    "currency": "USD",
                    "category": "subscriptions",
                    "note": "Apple subscriptions",
                    "expense_date": date.today().isoformat(),
                },
            ],
            "assistant_message": "I've added these expenses for you!",
            "needs_clarification": False,
            "follow_up_question": None,
        }

    monkeypatch.setattr(llm_module.llm_client, "extract_expenses", fake_extract_expenses)

    resp = client.post(
        "/chat",
        json={"message": "I spent 70 dollars at Walmart and 20 on Apple subscriptions"},
    )

    assert resp.status_code == 200
    body = resp.json()

    # The assistant should confirm and persist both expenses.
    assert len(body["assistant_message"]) > 0
    assert len(body["expenses"]) == 2
    merchants = {e["merchant"] for e in body["expenses"]}
    assert {"Walmart", "Apple"}.issubset(merchants)
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)


def test_chat_gracefully_handles_llm_rate_limits(client, monkeypatch):
    async def fake_extract_expenses(_message: str, history=None):
        return {
            "expenses": [],
            "assistant_message": "I didn't clearly see any expenses in that message.",
            "needs_clarification": False,
            "follow_up_question": None,
        }

    monkeypatch.setattr(llm_module.llm_client, "extract_expenses", fake_extract_expenses)

    resp = client.post(
        "/chat",
        json={"message": "Just chatting, no real expenses here"},
    )

    assert resp.status_code == 200
    body = resp.json()

    # When no expenses are found, we should respond clearly but not error.
    assert body["expenses"] == []
    assert len(body["assistant_message"]) > 0


def test_vague_input_returns_pending_and_clarification(client, monkeypatch):
    """Vague amount-only message → Pending expense saved + needs_clarification=True."""
    async def fake_extract_expenses(message: str, history=None):
        return {
            "expenses": [
                {
                    "merchant": "Pending",
                    "amount": 200,
                    "currency": "USD",
                    "category": "Uncategorized",
                    "note": "merchant unknown",
                    "expense_date": date.today().isoformat(),
                }
            ],
            "assistant_message": "I've noted the $200! What store or service was that at?",
            "needs_clarification": True,
            "follow_up_question": "What store or service was the $200 for?",
        }

    monkeypatch.setattr(llm_module.llm_client, "extract_expenses", fake_extract_expenses)

    resp = client.post("/chat", json={"message": "I just spent $200", "history": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_clarification"] is True
    assert len(body["expenses"]) == 1
    assert body["expenses"][0]["merchant"] == "Pending"
    assert "200" in body["assistant_message"]


def test_high_value_expense_flags_for_approval(client, monkeypatch):
    """Expenses >= $1000 should be flagged for approval."""
    async def fake_extract_expenses(message: str, history=None):
        return {
            "expenses": [
                {
                    "merchant": "Apple Store",
                    "amount": 1500,
                    "currency": "USD",
                    "category": "electronics",
                    "note": "",
                    "expense_date": date.today().isoformat(),
                }
            ],
            "assistant_message": "Logged $1500 at Apple Store.",
            "needs_clarification": False,
            "follow_up_question": None,
        }

    monkeypatch.setattr(llm_module.llm_client, "extract_expenses", fake_extract_expenses)

    resp = client.post("/chat", json={"message": "$1500 at Apple Store"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["expenses"]) == 1
    assert body["expenses"][0]["requires_approval"] is True


def test_approve_expense(client, monkeypatch):
    """POST /approvals/{id}/decide approve → approved=True, requires_approval=False."""
    async def fake_extract_expenses(message: str, history=None):
        return {
            "expenses": [
                {
                    "merchant": "Costco",
                    "amount": 1200,
                    "currency": "USD",
                    "category": "groceries",
                    "note": "",
                    "expense_date": date.today().isoformat(),
                }
            ],
            "assistant_message": "Logged $1200 at Costco.",
            "needs_clarification": False,
            "follow_up_question": None,
        }

    monkeypatch.setattr(llm_module.llm_client, "extract_expenses", fake_extract_expenses)

    chat_resp = client.post("/chat", json={"message": "$1200 at Costco"})
    assert chat_resp.status_code == 200
    expense_id = chat_resp.json()["expenses"][0]["id"]

    decide_resp = client.post(
        f"/approvals/{expense_id}/decide",
        json={"decision": "approve"},
    )
    assert decide_resp.status_code == 200
    body = decide_resp.json()
    assert body["approved"] is True
    assert body["requires_approval"] is False


def test_reject_expense_deletes_record(client, monkeypatch):
    """POST /approvals/{id}/decide reject → record is deleted from the DB."""
    async def fake_extract_expenses(message: str, history=None):
        return {
            "expenses": [
                {
                    "merchant": "BestBuy",
                    "amount": 1500,
                    "currency": "USD",
                    "category": "electronics",
                    "note": "",
                    "expense_date": date.today().isoformat(),
                }
            ],
            "assistant_message": "Logged $1500 at BestBuy.",
            "needs_clarification": False,
            "follow_up_question": None,
        }

    monkeypatch.setattr(llm_module.llm_client, "extract_expenses", fake_extract_expenses)

    chat_resp = client.post("/chat", json={"message": "$1500 at BestBuy"})
    assert chat_resp.status_code == 200
    expense_id = chat_resp.json()["expenses"][0]["id"]

    decide_resp = client.post(
        f"/approvals/{expense_id}/decide",
        json={"decision": "reject"},
    )
    assert decide_resp.status_code == 200

    # Verify the record is gone — a second decide should 404
    gone_resp = client.post(
        f"/approvals/{expense_id}/decide",
        json={"decision": "approve"},
    )
    assert gone_resp.status_code == 404
