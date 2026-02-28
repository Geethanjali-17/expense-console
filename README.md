## LLM Expense Tracker

AI‑powered, chat‑first expense tracker with a modern React dashboard and a FastAPI backend.

You talk to the assistant in plain English (e.g. _“I spent 70 dollars at Walmart and 20 on Apple subscriptions yesterday”_).  
The backend uses an LLM to interpret your message, extract structured expenses, save them to a database, and update a live dashboard.

---

## Features

- **Chat‑first input**: Capture expenses in natural language via a conversational UI.
- **LLM‑powered parsing**: Uses an LLM (e.g. OpenAI GPT) to extract merchant, amount, currency, category, notes, and date from free‑form text.
- **Persistent storage**: Expenses are stored in a relational database (SQLite by default) via SQLAlchemy.
- **Live dashboard**:
  - **Today’s spend** and **this month’s total**.
  - Recent daily totals visualized with an area chart (Recharts).
  - Scrollable list of the most recent expenses.
- **Resilient to LLM issues**:
  - Gracefully handles missing API keys and transient LLM/network errors.
  - Includes tests with LLM calls fully mocked out.
- **Modern UI**: React 18, Vite, Tailwind CSS, and glassmorphism‑style panels.

---

## Tech Stack

- **Backend**
  - Python, FastAPI
  - SQLAlchemy 2.x (ORM)
  - Pydantic 2.x for schemas
  - httpx for async HTTP calls to the LLM API
  - SQLite (default) or any SQLAlchemy‑compatible database
- **Frontend**
  - React 18 (TypeScript)
  - Vite
  - Tailwind CSS
  - Recharts for charts
- **Tooling & Tests**
  - pytest
  - uvicorn (development server)

---

## Project Structure

```text
backend/          # FastAPI app, DB models, LLM client, expense parsing
  config.py       # Environment configuration (API key, model, DB URL)
  database.py     # SQLAlchemy engine and session management
  expense_parser.py  # LLM-based message → structured expenses
  llm_client.py   # Thin wrapper around the OpenAI Chat Completions API
  main.py         # FastAPI app, routes, and startup logic
  models.py       # SQLAlchemy ORM models (Expense)
  schemas.py      # Pydantic models (API contracts and parsed expense types)

frontend/         # React + Vite SPA
  src/
    api.ts        # Axios client for backend endpoints
    App.tsx       # Root layout, wiring chat + dashboard
    main.tsx      # React entry point
    styles.css    # Tailwind base + custom utility classes
    types.ts      # Frontend TypeScript interfaces
    components/
      ChatPanel.tsx   # Chat UI and message handling
      Dashboard.tsx   # Metrics, chart, and recent expenses list

tests/
  test_chat.py    # End‑to‑end style tests for /chat using a mocked LLM client

requirements.txt  # Python backend dependencies
expenses.db       # Default SQLite DB (created automatically on startup)
```

---

## Backend Overview

### API Endpoints

- **POST `/chat`**
  - **Request body** (`ChatMessage`):
    - `message: string` – user’s natural‑language message.
  - **Behavior**:
    - Calls `parse_expenses_from_message()` in `expense_parser.py`.
    - That function calls `llm_client.extract_expenses()` to ask the LLM for a JSON list of expenses.
    - Successfully parsed expenses are mapped to the `Expense` SQLAlchemy model and persisted.
    - Returns a friendly confirmation message plus the saved expenses.
  - **Response** (`ChatResponse`):
    - `reply: string` – natural‑language confirmation / guidance.
    - `expenses: ExpenseRead[]` – list of structured expenses just saved.

- **GET `/expenses/recent`**
  - Returns the most recent expenses, ordered by `expense_date` and `created_at`.
  - Response model: `List[ExpenseRead]`.

- **GET `/dashboard/summary`**
  - Computes:
    - `today_total` – sum of all expenses for today.
    - `month_total` – sum of all expenses in the current calendar month.
    - `recent_expenses` – up to 10 most recent expenses.
  - Response model: `DashboardSummary`.

### Data Model

- **`Expense`** (`backend/models.py`):
  - `id: int` (PK)
  - `merchant: str`
  - `amount: float`
  - `currency: str` (default `"USD"`)
  - `category: str | None`
  - `note: str | None`
  - `expense_date: date` (defaults to `date.today`)
  - `created_at: datetime` (defaults to `datetime.utcnow`)

### Expense Parsing Pipeline

- **`LLMClient`** (`backend/llm_client.py`)
  - Wraps the OpenAI Chat Completions endpoint using `httpx.AsyncClient`.
  - Sends a detailed **system prompt** that explains:
    - How to recognize and extract expenses from casual text.
    - How to return strictly valid JSON of the shape `{"expenses": [...]}`.
  - Uses `response_format={"type": "json_object"}` and parses the `expenses` array.
  - **Failure behavior**:
    - If no API key is configured, immediately returns `[]`.
    - On HTTP or network errors, logs a warning and returns `[]`.
    - If the LLM response is malformed, returns `[]`.

- **`parse_expenses_from_message()`** (`backend/expense_parser.py`)
  - Calls `llm_client.extract_expenses(message)` and receives a list of dicts.
  - For each item:
    - Builds a `ParsedExpense` Pydantic model (`schemas.py`).
    - Coerces `amount` to float.
    - Normalizes `expense_date`:
      - If string, parses as ISO date (`YYYY-MM-DD`).
      - If missing, falls back to today’s date.
  - Malformed entries are skipped rather than causing the request to fail.

### Configuration & Environment Variables

Configuration is centralized in `backend/config.py` (`Settings` class):

- **`OPENAI_API_KEY`** (required for real LLM parsing)
  - API key used by `LLMClient` to call the OpenAI API.
  - If omitted, the backend still runs but `/chat` will never create expenses (it will behave as if the LLM always returns an empty list).

- **`OPENAI_MODEL_NAME`** (preferred) / **`OPENAI_MODEL`** (fallback)
  - Name of the OpenAI model to use (e.g. `"gpt-4.1"`, `"gpt-4o-mini"`).
  - Defaults to `"gpt-5.1"` if not provided.

- **`DATABASE_URL`**
  - SQLAlchemy database URL.
  - Defaults to `sqlite:///./expenses.db` (a SQLite file in the project root).
  - You can point this to Postgres, MySQL, etc. if desired.

Environment variables are loaded via `python-dotenv` from `backend/.env` if that file exists.

Example `backend/.env`:

```env
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL_NAME=gpt-4.1-mini
DATABASE_URL=sqlite:///./expenses.db
```

---

## Frontend Overview

The frontend is a Vite‑powered React SPA served separately from the backend. It talks to the API at `http://localhost:8000` by default (see `frontend/src/api.ts`).

- **`ChatPanel`** (`frontend/src/components/ChatPanel.tsx`)
  - Maintains a list of messages (`ChatMessage`).
  - Renders a chat‑style interface with separate styling for user vs assistant messages.
  - Sends the user’s message to `POST /chat` via `sendChatMessage()` in `api.ts`.
  - Appends the assistant’s `reply` as a new chat bubble.
  - If the response contains any expenses, triggers `onExpensesAdded()` so the dashboard refreshes.

- **`Dashboard`** (`frontend/src/components/Dashboard.tsx`)
  - Accepts a `refreshToken` prop from `App.tsx`.  
    When `refreshToken` changes, it refetches `/dashboard/summary`.
  - Displays:
    - Today’s total.
    - This month’s total.
    - An area chart of daily totals using Recharts.
    - A scrollable list of recent expenses.

- **`App`** (`frontend/src/App.tsx`)
  - Hosts a header and a two‑column layout:
    - Left: `ChatPanel`.
    - Right: `Dashboard`.
  - Maintains the `refreshToken` state and passes:
    - `onExpensesAdded` → increments `refreshToken` whenever new expenses are added.
    - `refreshToken` → passed into `Dashboard` to trigger refetches.

- **Styling**
  - Tailwind CSS is configured in `tailwind.config.cjs` and used in `styles.css`.
  - Custom utility classes like `.glass-panel` and `.scroll-thin` give the UI a modern glassmorphism look and slim scrollbars.

---

## Running the Project Locally

### 1. Prerequisites

- **Python** 3.11+ (recommended)
- **Node.js** 18+ and **npm**
- An **OpenAI API key** (or compatible hosted model key) if you want real LLM parsing.

---

### 2. Clone the Repository

If you haven’t already:

```bash
git clone <your-repo-url>.git
cd cursor_project
```

On Windows PowerShell you can use the same commands.

---

### 3. Backend Setup

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `backend/.env` file with your configuration (see **Configuration & Environment Variables** above).

Then start the FastAPI server (from the project root):

```bash
uvicorn backend.main:app --reload
```

This will:

- Create the database tables on startup (`Base.metadata.create_all(bind=engine)`).
- Start listening on `http://127.0.0.1:8000` by default.

You can verify it’s running by visiting:

- `http://localhost:8000/docs` – interactive Swagger UI.
- `http://localhost:8000/redoc` – alternative API docs.

---

### 4. Frontend Setup

In a **separate terminal**, from the project root:

```bash
cd frontend
npm install
npm run dev
```

Vite will start the dev server (typically on `http://localhost:5173`).

The frontend is configured to call the backend at `http://localhost:8000` (`API_BASE` in `src/api.ts`).  
If your backend is served elsewhere, update `API_BASE` accordingly or introduce a configuration mechanism.

---

### 5. Using the App

1. Open the frontend in your browser (e.g. `http://localhost:5173`).
2. In the **Expense Assistant** panel, type a natural‑language message such as:
   - `"I spent 70 dollars at Walmart and 20 on Apple subscriptions yesterday."`
3. Submit the message:
   - The assistant will reply confirming the expenses it extracted.
   - The **Spending Overview** dashboard refreshes automatically:
     - Today’s and this month’s totals update.
     - Daily totals chart and recent expenses list include the new entries.

If the LLM is unavailable (e.g. missing API key, rate limiting, network errors), the assistant replies with a generic error message and no new expenses are added. The app is designed not to crash in these scenarios.

---

## Running Tests

From the project root, with your virtual environment active:

```bash
pytest
```

### What the tests cover

- **`tests/test_chat.py`**
  - Uses FastAPI’s `TestClient` against the real `/chat` endpoint.
  - **Unit/integration behavior**:
    - Patches `llm_client.extract_expenses` with `monkeypatch` so tests do **not** call the real OpenAI API.
    - Validates that:
      - A message like _“I spent 70 dollars at Walmart and 20 on Apple subscriptions”_ results in two expenses being created and returned.
      - When the LLM returns an empty list, the API responds with a helpful message and an empty `expenses` array, without raising errors.

---

## Deployment Notes (High Level)

- **Backend**
  - Use a production ASGI server (e.g. `uvicorn` with workers or `gunicorn` + `uvicorn.workers.UvicornWorker`).
  - Configure `DATABASE_URL` for your production database (e.g. Postgres).
  - Set `OPENAI_API_KEY` and `OPENAI_MODEL_NAME` via environment variables or a secure secrets manager.

- **Frontend**
  - Build static assets:
    ```bash
    cd frontend
    npm run build
    ```
  - Serve the `dist` directory via your preferred static host (NGINX, Vercel, Netlify, etc.).
  - Ensure the frontend’s API base URL points to your deployed backend.

---

## Extending the Project

- **Additional fields**: Add columns to `Expense` in `models.py` and corresponding Pydantic fields in `schemas.py`, then update the LLM prompt in `llm_client.py` to request them.
- **Categories / budgets**: Add new models, endpoints, and dashboard widgets to support budgets, category‑level analytics, or recurring expenses.
- **Authentication**: Introduce user accounts and per‑user expense isolation using FastAPI dependencies and database relationships.
- **Alternative LLM providers**: Swap out the OpenAI endpoint in `LLMClient` for other providers or self‑hosted models, keeping the same interface.

---

## License

Add your preferred license information here (e.g. MIT, Apache‑2.0).


