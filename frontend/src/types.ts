export interface Expense {
  id: number;
  merchant: string;
  amount: number;
  currency: string;
  category?: string | null;
  note?: string | null;
  expense_date: string;
  created_at: string;
  financial_impact_score?: number | null;
  strategic_insight?: string | null;
  ai_reasoning_path?: string | null;
  anomaly_flags?: string | null;   // JSON string
  requires_approval?: boolean;
  approved?: boolean | null;
}

export interface StrategicRecommendation {
  expense_id: number;
  insight: string;
  anomaly_flags: string[];
  requires_approval: boolean;
}

export interface ChatResponse {
  success: boolean;
  assistant_message: string;
  expenses: Expense[];
  recommendations: StrategicRecommendation[];
  needs_clarification: boolean;
}


export interface DashboardSummary {
  today_total: number;
  month_total: number;
  recent_expenses: Expense[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: string;
}

export interface SearchResponse {
  expenses: Expense[];
  summary_text: string;
}

export interface DriftInsight {
  category: string;
  current_total: number;
  median_total: number;
  drift_pct: number;
  insight: string;
  action: string;
  status: "warning" | "stable" | "improving";
}

export interface DriftResponse {
  insights: DriftInsight[];
  period: string;
}
