import axios from "axios";
import type {
  ChatResponse,
  DashboardSummary,
  DriftResponse,
  Expense,
  SearchResponse,
} from "./types";

const API_BASE = "http://localhost:8000";

export async function sendChatMessage(
  message: string,
  history: { role: string; content: string }[] = [],
  pendingExpenseId?: number | null
): Promise<ChatResponse> {
  const { data } = await axios.post<ChatResponse>(`${API_BASE}/chat`, {
    message,
    history,
    pending_expense_id: pendingExpenseId ?? null,
  });
  return data;
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const { data } = await axios.get<DashboardSummary>(
    `${API_BASE}/dashboard/summary`
  );
  return data;
}

export async function fetchPendingApprovals(): Promise<Expense[]> {
  const { data } = await axios.get<Expense[]>(`${API_BASE}/approvals`);
  return data;
}

export async function decideApproval(
  id: number,
  decision: "approve" | "reject"
): Promise<Expense> {
  const { data } = await axios.post<Expense>(
    `${API_BASE}/approvals/${id}/decide`,
    { decision }
  );
  return data;
}

export async function updateExpenseCategory(id: number, category: string): Promise<Expense> {
  const { data } = await axios.patch<Expense>(`${API_BASE}/expenses/${id}/category`, { category });
  return data;
}

export async function searchExpenses(query: string): Promise<SearchResponse> {
  const { data } = await axios.post<SearchResponse>(`${API_BASE}/search`, {
    query,
  });
  return data;
}

export async function fetchDriftInsights(): Promise<DriftResponse> {
  const { data } = await axios.get<DriftResponse>(`${API_BASE}/drift`);
  return data;
}


