# CLAUDE.md

This file helps Claude Code understand the project structure and get started quickly.

## Development Commands

### Backend
```bash
# From project root
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn backend.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev       # dev server
npm run build     # production build
```

### Tests
```bash
# From project root with venv active
pytest
```

## Architecture

Full-stack AI expense tracker:
- **Backend**: FastAPI (Python) with SQLite (`expenses.db` auto-created at project root)
- **Frontend**: React + TypeScript + Vite, styled with Tailwind CSS, charts via Recharts
- **LLM**: OpenAI integration for natural language expense parsing
- **Config**: `backend/.env` (requires `OPENAI_API_KEY`)

## Backend Structure (`backend/`)

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, CORS middleware, startup hook, 3 routes: `POST /chat`, `GET /expenses/recent`, `GET /dashboard/summary` |
| `llm_client.py` | OpenAI API wrapper with graceful error handling |
| `expense_parser.py` | Pipeline: user message → LLM → Pydantic validation → ORM objects |
| `models.py` | SQLAlchemy `Expense` ORM model |
| `schemas.py` | Pydantic request/response models (`ChatMessage`, `ChatResponse`, `DashboardSummary`, etc.) |
| `database.py` | SQLite engine and `get_db` session factory |
| `config.py` | Settings loaded via pydantic-settings from `backend/.env` |

## Frontend Structure (`frontend/src/`)

| File | Purpose |
|---|---|
| `App.tsx` | Root layout; owns `refreshToken` state passed to Dashboard |
| `components/ChatPanel.tsx` | Chat UI; sends `POST /chat`, calls `onExpenseAdded` to trigger dashboard refresh |
| `components/Dashboard.tsx` | Summary cards + Recharts bar chart; refetches when `refreshToken` changes |
| `api.ts` | Axios client for all backend calls |
| `types.ts` | TypeScript interfaces matching backend schemas |

## Data Flow

```
User message → POST /chat → LLM parses expenses → saved to SQLite → refreshToken bumped → Dashboard refetches
```

## Testing

`tests/test_chat.py` uses FastAPI `TestClient` with monkeypatched LLM — no real OpenAI calls needed to run the test suite.
