import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  decideApproval,
  fetchDashboardSummary,
  fetchDriftInsights,
  fetchPendingApprovals,
  searchExpenses,
  updateExpenseCategory,
} from "../api";
import type { DashboardSummary, DriftInsight, Expense } from "../types";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface DashboardProps {
  refreshCounter: number;
  triggerRefresh?: () => void;
}

/* ── Tiny helpers ─────────────────────────────────────────────────────── */
function ImpactBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  const cls =
    score > 70
      ? "bg-red-950/80 text-red-400 ring-1 ring-red-500/30"
      : score >= 40
      ? "bg-amber-950/80 text-amber-400 ring-1 ring-amber-500/30"
      : "bg-emerald-950/80 text-emerald-400 ring-1 ring-emerald-500/30";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[0.62rem] font-semibold ${cls}`}>
      {score}
    </span>
  );
}

function AnomalyChip({ flag }: { flag: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    duplicate_charge:    { label: "Double Charge?", cls: "bg-red-950/80 text-red-400 ring-1 ring-red-500/25" },
    zombie_subscription: { label: "Zombie Sub",     cls: "bg-violet-950/80 text-violet-400 ring-1 ring-violet-500/25" },
    price_creep:         { label: "Price Creep",    cls: "bg-amber-950/80 text-amber-400 ring-1 ring-amber-500/25" },
  };
  const { label, cls } = map[flag] ?? { label: flag, cls: "bg-slate-800 text-slate-400" };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[0.6rem] font-medium ${cls}`}>
      {label}
    </span>
  );
}

function SparkleIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
    </svg>
  );
}

const DRIFT_STATUS: Record<string, { bg: string; border: string; pctColor: string; dot: string }> = {
  warning:   { bg: "bg-red-950/50",     border: "border-red-500/15",     pctColor: "text-red-400",     dot: "bg-red-400"     },
  improving: { bg: "bg-emerald-950/50", border: "border-emerald-500/15", pctColor: "text-emerald-400", dot: "bg-emerald-400" },
  stable:    { bg: "bg-slate-900/60",   border: "border-white/[0.06]",   pctColor: "text-slate-400",   dot: "bg-slate-400"   },
};

/* ── Category picker ─────────────────────────────────────────────────── */
const CATEGORIES = [
  "groceries", "restaurants", "subscriptions", "entertainment",
  "travel", "healthcare", "shopping", "apparel",
  "home & hardware", "utilities", "transport", "education",
] as const;

interface CategoryPickerProps {
  expenseId: number;
  currentCategory: string | null | undefined;
  anchorRect: DOMRect;
  onSelect: (id: number, category: string) => Promise<void>;
  onClose: () => void;
}

function CategoryPicker({ expenseId, currentCategory, anchorRect, onSelect, onClose }: CategoryPickerProps) {
  const [saving, setSaving] = useState<string | null>(null);

  // Position: below the trigger, left-aligned, clamped to viewport
  const top  = Math.min(anchorRect.bottom + 6, window.innerHeight - 260);
  const left = Math.min(anchorRect.left,       window.innerWidth  - 192);

  // Close on outside click (deferred so the opening click doesn't immediately close)
  useEffect(() => {
    const id = setTimeout(() => {
      function onOutside(e: MouseEvent) {
        onClose();
        window.removeEventListener("mousedown", onOutside);
      }
      window.addEventListener("mousedown", onOutside);
      return () => window.removeEventListener("mousedown", onOutside);
    }, 0);
    return () => clearTimeout(id);
  }, [onClose]);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function pick(cat: string) {
    if (cat === currentCategory || saving) return;
    setSaving(cat);
    await onSelect(expenseId, cat);
    onClose();
  }

  return (
    <div
      style={{
        position: "fixed", top, left, zIndex: 200,
        background: "rgba(10,10,18,0.96)",
        backdropFilter: "blur(16px)",
        border: "1px solid rgba(255,255,255,0.09)",
        borderRadius: "0.75rem",
        boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
        width: "12rem",
        overflow: "hidden",
      }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <p className="border-b border-white/[0.06] px-3 py-2 text-[0.6rem] font-semibold uppercase tracking-widest text-slate-600">
        Set Category
      </p>
      {CATEGORIES.map((cat) => {
        const isActive = cat === currentCategory?.toLowerCase();
        return (
          <button
            key={cat}
            onClick={() => pick(cat)}
            disabled={!!saving}
            className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-[0.72rem] capitalize transition-colors disabled:opacity-50 ${
              isActive
                ? "bg-indigo-600/25 text-indigo-300"
                : "text-slate-300 hover:bg-white/[0.06] hover:text-slate-100"
            }`}
          >
            {cat}
            {saving === cat && (
              <svg className="h-3 w-3 animate-spin text-indigo-400" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            )}
            {isActive && !saving && (
              <svg className="h-3 w-3 text-indigo-400" viewBox="0 0 24 24" fill="currentColor">
                <path fillRule="evenodd" d="M19.916 4.626a.75.75 0 01.208 1.04l-9 13.5a.75.75 0 01-1.154.114l-6-6a.75.75 0 011.06-1.06l5.353 5.353 8.493-12.739a.75.75 0 011.04-.208z" clipRule="evenodd" />
              </svg>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ── Auditor explanation builder ─────────────────────────────────────── */
function buildAuditorExplanation(d: DriftInsight, txns: Expense[]): string {
  const { category, current_total, median_total, drift_pct } = d;
  const direction = drift_pct > 0 ? "up" : "down";
  const base = `You've spent $${current_total.toFixed(2)} on ${category} this month — ${Math.abs(drift_pct).toFixed(0)}% ${direction} from your $${median_total.toFixed(2)} monthly average.`;

  if (!txns.length) return base + (d.insight ? " " + d.insight : "");

  const biggest = [...txns].sort((a, b) => b.amount - a.amount)[0];
  const withoutBiggest = current_total - biggest.amount;
  const adjDrift = median_total > 0
    ? ((withoutBiggest - median_total) / median_total) * 100
    : withoutBiggest > 0 ? 100 : 0;
  const adjPhrase = adjDrift > 0
    ? `still ${adjDrift.toFixed(0)}% above`
    : `${Math.abs(adjDrift).toFixed(0)}% below`;

  const dateFmt = new Date(biggest.expense_date + "T12:00:00").toLocaleDateString("en-CA", {
    month: "short", day: "numeric",
  });

  let explanation = `${base} The spike is primarily driven by a $${biggest.amount.toFixed(2)} purchase at ${biggest.merchant} on ${dateFmt}.`;
  if (txns.length > 1) {
    explanation += ` Without that single transaction, you'd be ${adjPhrase} your average.`;
  }
  return explanation;
}

/* ── Deep-Dive Modal ─────────────────────────────────────────────────── */
interface DeepDiveProps {
  drift: DriftInsight;
  expenses: Expense[];
  onClose: () => void;
}

function DeepDiveModal({ drift, expenses, onClose }: DeepDiveProps) {
  const cfg = DRIFT_STATUS[drift.status] ?? DRIFT_STATUS.stable;
  const arrow = drift.drift_pct > 0 ? "↑" : drift.drift_pct < 0 ? "↓" : "→";
  const explanation = useMemo(
    () => buildAuditorExplanation(drift, expenses),
    [drift, expenses],
  );

  // Close on Escape key
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Lock body scroll
  useEffect(() => {
    document.body.classList.add("modal-open");
    return () => document.body.classList.remove("modal-open");
  }, []);

  return (
    /* Backdrop */
    <div
      className="modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.72)", backdropFilter: "blur(6px)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Panel */}
      <div
        className="modal-panel relative flex w-full max-w-lg flex-col overflow-hidden rounded-2xl"
        style={{
          background: "rgba(12, 12, 18, 0.92)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(255,255,255,0.09)",
          maxHeight: "90vh",
        }}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-white/[0.06] text-slate-400 hover:bg-white/[0.12] hover:text-slate-200 transition-all"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {/* Header */}
        <div className="flex-shrink-0 border-b border-white/[0.06] px-6 pb-5 pt-6">
          <div className="flex items-start justify-between pr-8">
            <div>
              <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[0.65rem] font-medium capitalize text-slate-400 ring-1 ring-white/[0.06]">
                {drift.category}
              </span>
              <div className="mt-3 flex items-baseline gap-2">
                <span className={`text-4xl font-bold tracking-tight ${cfg.pctColor}`}>
                  {drift.drift_pct > 0 ? "+" : ""}{drift.drift_pct.toFixed(0)}%
                </span>
                <span className={`text-2xl ${cfg.pctColor}`}>{arrow}</span>
              </div>
              <div className="mt-1 flex items-center gap-3 text-sm">
                <span className="font-semibold text-slate-100">
                  ${drift.current_total.toFixed(2)} this month
                </span>
                <span className="text-slate-700">/</span>
                <span className="text-slate-500">
                  ${drift.median_total.toFixed(2)} avg
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="scroll-hidden flex-1 overflow-y-auto px-6 py-5 space-y-5">

          {/* Auditor's Explanation */}
          <div className="rounded-xl bg-white/[0.04] p-4 ring-1 ring-white/[0.06]">
            <div className="mb-2 flex items-center gap-2">
              <svg className="h-3.5 w-3.5 text-indigo-400" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
              <span className="text-[0.65rem] font-semibold uppercase tracking-widest text-slate-500">
                Auditor's Analysis
              </span>
            </div>
            <p className="text-[0.82rem] leading-relaxed text-slate-300">{explanation}</p>
            {drift.action && (
              <p className="mt-2.5 text-[0.75rem] font-medium text-indigo-400">
                → {drift.action}
              </p>
            )}
          </div>

          {/* Transaction Evidence */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />
                <span className="text-[0.65rem] font-semibold uppercase tracking-widest text-slate-500">
                  Evidence — {expenses.length} transaction{expenses.length !== 1 ? "s" : ""}
                </span>
              </div>
              <span className="text-[0.65rem] font-semibold text-slate-300">
                ${drift.current_total.toFixed(2)} total
              </span>
            </div>

            {expenses.length === 0 ? (
              <p className="text-[0.75rem] text-slate-600">No transactions found for this category this month.</p>
            ) : (
              <div className="space-y-1">
                {expenses.map((e) => {
                  const pct = drift.current_total > 0
                    ? (e.amount / drift.current_total) * 100
                    : 0;
                  const dateFmt = new Date(e.expense_date + "T12:00:00").toLocaleDateString("en-CA", {
                    month: "short", day: "numeric",
                  });
                  return (
                    <div
                      key={e.id}
                      className="flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-white/[0.04]"
                    >
                      {/* Date */}
                      <span className="w-14 flex-shrink-0 text-[0.65rem] text-slate-600">{dateFmt}</span>

                      {/* Bar + merchant */}
                      <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <span className="truncate text-[0.75rem] font-medium text-slate-200">{e.merchant}</span>
                        <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.05]">
                          <div
                            className={`h-full rounded-full transition-all ${cfg.pctColor.replace("text-", "bg-")}`}
                            style={{ width: `${Math.min(pct, 100)}%`, opacity: 0.6 }}
                          />
                        </div>
                      </div>

                      {/* Amount */}
                      <span className="flex-shrink-0 text-sm font-semibold text-slate-100">
                        ${e.amount.toFixed(2)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-white/[0.05] px-6 py-4">
          <button
            onClick={onClose}
            className="w-full rounded-xl bg-white/[0.06] py-2.5 text-sm font-medium text-slate-300 ring-1 ring-white/[0.07] hover:bg-white/[0.1] hover:text-slate-100 transition-all"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────────────── */
export function Dashboard({ refreshCounter, triggerRefresh }: DashboardProps) {
  /* Dashboard summary */
  const [summary, setSummary]     = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [highlight, setHighlight] = useState(false);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* Approvals */
  const [approvals, setApprovals]   = useState<Expense[]>([]);
  const [decidingId, setDecidingId] = useState<number | null>(null);

  /* Drift insights */
  const [driftInsights, setDriftInsights] = useState<DriftInsight[]>([]);
  const [driftPeriod, setDriftPeriod]     = useState("");
  const [driftLoading, setDriftLoading]   = useState(true);

  /* Deep-dive modal */
  const [selectedDrift, setSelectedDrift] = useState<DriftInsight | null>(null);

  /* Search */
  const [searchInput,   setSearchInput]   = useState("");
  const [searchResults, setSearchResults] = useState<Expense[] | null>(null);
  const [searchSummary, setSearchSummary] = useState("");
  const [isSearching,   setIsSearching]   = useState(false);

  /* Category picker */
  const [categoryPicker, setCategoryPicker] = useState<{
    expenseId: number;
    anchorRect: DOMRect;
    currentCategory: string | null | undefined;
  } | null>(null);

  /* ── Data fetching ─────────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      try {
        const data = await fetchDashboardSummary();
        if (!cancelled) {
          setSummary(data);
          setHighlight(true);
          if (highlightTimer.current) clearTimeout(highlightTimer.current);
          highlightTimer.current = setTimeout(() => setHighlight(false), 800);
        }
      } catch { /* keep existing */ }
      finally { if (!cancelled) setIsLoading(false); }
    }
    load();
    return () => { cancelled = true; };
  }, [refreshCounter]);

  useEffect(() => {
    let cancelled = false;
    async function loadApprovals() {
      try {
        const data = await fetchPendingApprovals();
        if (!cancelled) setApprovals(data);
      } catch { /* silent */ }
    }
    loadApprovals();
    return () => { cancelled = true; };
  }, [refreshCounter]);

  useEffect(() => {
    let cancelled = false;
    async function loadDrift() {
      setDriftLoading(true);
      try {
        const data = await fetchDriftInsights();
        if (!cancelled) {
          setDriftInsights(data.insights);
          setDriftPeriod(data.period);
        }
      } catch { /* silent */ }
      finally { if (!cancelled) setDriftLoading(false); }
    }
    loadDrift();
    return () => { cancelled = true; };
  }, [refreshCounter]);

  /* ── Derived data ──────────────────────────────────────────────────── */
  const displayExpenses = useMemo(
    () => searchResults ?? summary?.recent_expenses ?? [],
    [searchResults, summary],
  );

  const dailySeries = useMemo(() => {
    if (!displayExpenses.length) return [];
    const byDate = new Map<string, number>();
    displayExpenses.forEach((e) => byDate.set(e.expense_date, (byDate.get(e.expense_date) ?? 0) + e.amount));
    return Array.from(byDate.entries())
      .map(([date, total]) => ({ date, total }))
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-14); // last 14 days max
  }, [displayExpenses]);

  const insightExpenses = useMemo(
    () => (summary?.recent_expenses ?? []).filter((e) => e.strategic_insight).slice(0, 8),
    [summary],
  );

  // Transactions for the currently selected deep-dive category (current month only)
  const currentMonth = new Date().toISOString().slice(0, 7); // "2026-02"
  const deepDiveExpenses = useMemo(() => {
    if (!selectedDrift) return [];
    return (summary?.recent_expenses ?? [])
      .filter(
        (e) =>
          e.category?.toLowerCase() === selectedDrift.category.toLowerCase() &&
          e.expense_date.startsWith(currentMonth),
      )
      .sort((a, b) => b.expense_date.localeCompare(a.expense_date));
  }, [selectedDrift, summary, currentMonth]);

  const closeDeepDive = useCallback(() => setSelectedDrift(null), []);

  /* ── Handlers ──────────────────────────────────────────────────────── */
  async function handleDecide(id: number, decision: "approve" | "reject") {
    setDecidingId(id);
    try {
      await decideApproval(id, decision);
      triggerRefresh?.();
    } catch { alert("Could not process that decision. Please try again."); }
    finally { setDecidingId(null); }
  }

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    const q = searchInput.trim();
    if (!q || isSearching) return;
    setIsSearching(true);
    try {
      const res = await searchExpenses(q);
      setSearchResults(res.expenses);
      setSearchSummary(res.summary_text);
    } catch {
      setSearchResults([]);
      setSearchSummary("Search failed — please try again.");
    } finally { setIsSearching(false); }
  }

  function clearSearch() {
    setSearchInput(""); setSearchResults(null); setSearchSummary("");
  }

  function openCategoryPicker(ev: React.MouseEvent, expense: Expense) {
    ev.stopPropagation();
    const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    setCategoryPicker({ expenseId: expense.id, anchorRect: rect, currentCategory: expense.category });
  }

  async function handleCategorySelect(id: number, category: string) {
    try {
      const updated = await updateExpenseCategory(id, category);
      // Update in-place in summary + search results so the UI reflects immediately
      const patch = (list: Expense[]) =>
        list.map((e) => (e.id === id ? { ...e, category: updated.category } : e));
      setSummary((prev) =>
        prev ? { ...prev, recent_expenses: patch(prev.recent_expenses) } : prev
      );
      setSearchResults((prev) => (prev ? patch(prev) : prev));
    } catch {
      // silent — user can retry
    }
  }

  /* ── Render ────────────────────────────────────────────────────────── */
  return (
    <section className="flex h-full flex-col gap-4 overflow-hidden">
      {/* Deep-Dive Modal */}
      {selectedDrift && (
        <DeepDiveModal
          drift={selectedDrift}
          expenses={deepDiveExpenses}
          onClose={closeDeepDive}
        />
      )}

      {/* Category Picker Popover */}
      {categoryPicker && (
        <CategoryPicker
          expenseId={categoryPicker.expenseId}
          currentCategory={categoryPicker.currentCategory}
          anchorRect={categoryPicker.anchorRect}
          onSelect={handleCategorySelect}
          onClose={() => setCategoryPicker(null)}
        />
      )}

      {/* ── TOP: Stats + Chart ───────────────────────────────────────── */}
      <div className="glass-panel flex-shrink-0 p-5">
        {/* Stat cards */}
        <div className="mb-4 grid grid-cols-2 gap-3">
          {[
            { label: "Today's Spend", value: summary?.today_total ?? 0 },
            { label: "This Month",    value: summary?.month_total ?? 0 },
          ].map(({ label, value }) => (
            <div
              key={label}
              className={`rounded-xl p-4 transition-all duration-500 ${
                highlight
                  ? "bg-indigo-950/60 ring-1 ring-indigo-500/30"
                  : "bg-white/[0.03] ring-1 ring-white/[0.05]"
              }`}
            >
              <p className="text-[0.65rem] font-medium uppercase tracking-widest text-slate-500">
                {label}
              </p>
              <p className={`mt-1.5 text-2xl font-bold tracking-tight transition-colors duration-500 ${
                highlight ? "text-indigo-300" : "text-slate-50"
              }`}>
                ${value.toFixed(2)}
              </p>
            </div>
          ))}
        </div>

        {/* Chart */}
        <div className={`transition-opacity duration-300 ${isLoading || isSearching ? "opacity-50" : "opacity-100"}`}>
          <div className="mb-1.5 flex items-center gap-2">
            <p className="text-[0.62rem] font-medium uppercase tracking-widest text-slate-600">
              {searchResults ? "Filtered — Daily Totals" : "Daily Spending"}
            </p>
            {searchResults && (
              <span className="rounded-full bg-amber-950/70 px-2 py-0.5 text-[0.58rem] font-medium text-amber-400 ring-1 ring-amber-500/20">
                Filtered
              </span>
            )}
          </div>
          <div className="h-[100px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart key={refreshCounter} data={dailySeries}>
                <defs>
                  <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#6366F1" stopOpacity={0.5} />
                    <stop offset="95%" stopColor="#6366F1" stopOpacity={0}   />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="date" stroke="#374151" tick={{ fill: "#6B7280", fontSize: 10 }} tickLine={false} />
                <YAxis stroke="#374151" tick={{ fill: "#6B7280", fontSize: 10 }} tickLine={false} tickFormatter={(v) => `$${v}`} width={40} />
                <Tooltip
                  contentStyle={{ background: "#0a0a12", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "0.75rem", fontSize: "0.72rem" }}
                  formatter={(v) => [`$${v}`, "Spend"]}
                />
                <Area type="monotone" dataKey="total" stroke="#6366F1" strokeWidth={2} fill="url(#grad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ── BOTTOM: Intelligence Hub ─────────────────────────────────── */}
      <div className="glass-panel flex min-h-0 flex-1 flex-col overflow-hidden">
        {/* Hub header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-white/[0.05] px-5 py-3">
          <div className="flex items-center gap-2">
            <SparkleIcon className="h-3.5 w-3.5 text-indigo-400" />
            <span className="text-xs font-semibold tracking-tight text-slate-200">
              Financial Intelligence
            </span>
            {driftPeriod && (
              <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[0.6rem] text-slate-500">
                {driftPeriod}
              </span>
            )}
          </div>
          {(isLoading || driftLoading) && (
            <span className="text-[0.65rem] text-slate-600">Refreshing…</span>
          )}
        </div>

        {/* AI Search bar */}
        <form onSubmit={handleSearch} className="flex-shrink-0 border-b border-white/[0.05] px-5 py-2.5">
          <div className="flex items-center gap-2">
            <SparkleIcon className="h-3.5 w-3.5 flex-shrink-0 text-amber-500/70" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder='Ask your spending… "coffee this month" or "biggest purchases"'
              className="min-w-0 flex-1 bg-transparent text-[0.72rem] text-slate-300 outline-none placeholder:text-slate-600"
            />
            {searchResults && (
              <button type="button" onClick={clearSearch}
                className="flex-shrink-0 rounded-md bg-white/[0.06] px-2.5 py-1 text-[0.62rem] text-slate-400 hover:text-slate-200 transition-colors">
                Clear
              </button>
            )}
            <button type="submit" disabled={isSearching || !searchInput.trim()}
              className="flex-shrink-0 rounded-md bg-amber-600/60 px-2.5 py-1 text-[0.62rem] font-semibold text-amber-100 hover:bg-amber-500/70 disabled:opacity-30 transition-colors">
              {isSearching ? "…" : "Search"}
            </button>
          </div>
          {searchSummary && searchResults && (
            <p className="mt-1.5 text-[0.62rem] text-amber-400/80">{searchSummary}</p>
          )}
        </form>

        {/* ── Scrollable insights body ──────────────────────────────── */}
        <div className="scroll-hidden flex-1 space-y-5 px-5 pb-5 pt-4">

          {/* Pending Approvals */}
          {approvals.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                <p className="text-[0.65rem] font-semibold uppercase tracking-widest text-red-400">
                  Pending Approvals
                </p>
                <span className="rounded-full bg-red-950/70 px-1.5 py-0.5 text-[0.58rem] font-bold text-red-400 ring-1 ring-red-500/25">
                  {approvals.length}
                </span>
              </div>
              <div className="space-y-2">
                {approvals.map((e) => {
                  const flags: string[] = JSON.parse(e.anomaly_flags ?? "[]");
                  return (
                    <div key={e.id} className="rounded-xl bg-red-950/20 p-3 ring-1 ring-red-500/15">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <p className="text-xs font-semibold text-slate-100">{e.merchant}</p>
                            <ImpactBadge score={e.financial_impact_score} />
                            {flags.map((f) => <AnomalyChip key={f} flag={f} />)}
                          </div>
                          <p className="mt-0.5 text-sm font-bold text-emerald-400">${e.amount.toFixed(2)}</p>
                          {e.strategic_insight && (
                            <p className="mt-1 text-[0.68rem] leading-relaxed text-slate-500">{e.strategic_insight}</p>
                          )}
                        </div>
                      </div>
                      <div className="mt-2 flex gap-2">
                        <button onClick={() => handleDecide(e.id, "approve")} disabled={decidingId === e.id}
                          className="flex-1 rounded-lg bg-emerald-900/50 py-1.5 text-[0.7rem] font-semibold text-emerald-300 ring-1 ring-emerald-500/20 hover:bg-emerald-900/80 disabled:opacity-40 transition-colors">
                          {decidingId === e.id ? "…" : "Accept"}
                        </button>
                        <button onClick={() => handleDecide(e.id, "reject")} disabled={decidingId === e.id}
                          className="flex-1 rounded-lg bg-red-900/50 py-1.5 text-[0.7rem] font-semibold text-red-300 ring-1 ring-red-500/20 hover:bg-red-900/80 disabled:opacity-40 transition-colors">
                          {decidingId === e.id ? "…" : "Reject"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Financial Drift Cards (staggered animation) */}
          {(driftLoading || driftInsights.length > 0) && (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
                  <p className="text-[0.65rem] font-semibold uppercase tracking-widest text-slate-500">
                    Category Drift
                  </p>
                </div>
                <span className="text-[0.58rem] text-slate-700">click a card to deep-dive</span>
              </div>
              {driftLoading ? (
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="animate-pulse rounded-xl bg-white/[0.03] p-4 ring-1 ring-white/[0.05]">
                      <div className="h-3 w-16 rounded bg-white/[0.06]" />
                      <div className="mt-3 h-6 w-12 rounded bg-white/[0.06]" />
                      <div className="mt-2 h-2 w-20 rounded bg-white/[0.04]" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
                  {driftInsights.map((d) => {
                    const cfg = DRIFT_STATUS[d.status] ?? DRIFT_STATUS.stable;
                    const arrow = d.drift_pct > 0 ? "↑" : d.drift_pct < 0 ? "↓" : "→";
                    return (
                      <div
                        key={d.category}
                        onClick={() => setSelectedDrift(d)}
                        className={`insight-card cursor-pointer rounded-xl p-4 ring-1 ${cfg.bg} ${cfg.border}`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[0.6rem] font-medium capitalize text-slate-400">
                            {d.category}
                          </span>
                          <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
                        </div>
                        <div className="mt-3 flex items-baseline gap-1">
                          <span className={`text-2xl font-bold tracking-tight ${cfg.pctColor}`}>
                            {d.drift_pct > 0 ? "+" : ""}{d.drift_pct.toFixed(0)}%
                          </span>
                          <span className={`text-base ${cfg.pctColor}`}>{arrow}</span>
                        </div>
                        <div className="mt-1 flex gap-2 text-[0.62rem] text-slate-600">
                          <span>${d.current_total.toFixed(0)} now</span>
                          <span>/</span>
                          <span>${d.median_total.toFixed(0)} avg</span>
                        </div>
                        {d.insight && (
                          <p className="mt-2.5 text-[0.67rem] leading-relaxed text-slate-400">{d.insight}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* AI Expense Insights */}
          {insightExpenses.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                <p className="text-[0.65rem] font-semibold uppercase tracking-widest text-slate-500">
                  AI Audit Insights
                </p>
              </div>
              <div className="space-y-1.5">
                {insightExpenses.map((e) => {
                  const flags: string[] = JSON.parse(e.anomaly_flags ?? "[]");
                  return (
                    <div key={e.id} className="flex items-start gap-2.5 rounded-lg bg-white/[0.025] px-3 py-2.5 ring-1 ring-white/[0.04]">
                      <ImpactBadge score={e.financial_impact_score} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <p className="text-[0.72rem] font-semibold text-slate-200">{e.merchant}</p>
                          <span className="text-[0.62rem] text-slate-600">${e.amount.toFixed(2)}</span>
                          <button
                            onClick={(ev) => openCategoryPicker(ev, e)}
                            title="Click to change category"
                            className={`rounded px-1 py-0.5 text-[0.6rem] transition-colors ${
                              !e.category || e.category === "Uncategorized"
                                ? "cursor-pointer text-amber-500/80 ring-1 ring-amber-500/20 hover:bg-amber-950/40 hover:text-amber-300"
                                : "cursor-pointer capitalize text-slate-600 hover:bg-white/[0.06] hover:text-slate-400"
                            }`}
                          >
                            {!e.category || e.category === "Uncategorized" ? "✎ Uncategorized" : e.category}
                          </button>
                          {flags.map((f) => <AnomalyChip key={f} flag={f} />)}
                        </div>
                        <p className="mt-0.5 text-[0.67rem] leading-relaxed text-slate-500">{e.strategic_insight}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Expense List */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />
                <p className="text-[0.65rem] font-semibold uppercase tracking-widest text-slate-500">
                  {searchResults ? "Search Results" : "All Expenses"}
                </p>
              </div>
              {displayExpenses.length > 0 && (
                <span className="text-[0.6rem] text-slate-600">
                  {displayExpenses.length} {searchResults ? "found" : "logged"}
                </span>
              )}
            </div>
            {displayExpenses.length ? (
              <div className={`space-y-0.5 transition-opacity duration-200 ${isLoading || isSearching ? "opacity-40" : "opacity-100"}`}>
                {displayExpenses.map((e) => (
                  <div key={e.id}
                    className="flex items-center justify-between rounded-lg px-3 py-2 transition-colors hover:bg-white/[0.03]">
                    <div className="min-w-0">
                      <p className="text-[0.72rem] font-medium text-slate-200 truncate">{e.merchant}</p>
                      <div className="flex items-center gap-1 text-[0.62rem]">
                        <button
                          onClick={(ev) => openCategoryPicker(ev, e)}
                          title="Click to change category"
                          className={`rounded px-1 py-0.5 transition-colors ${
                            !e.category || e.category === "Uncategorized"
                              ? "cursor-pointer text-amber-500/80 ring-1 ring-amber-500/20 hover:bg-amber-950/40 hover:text-amber-300"
                              : "cursor-pointer capitalize text-slate-500 hover:bg-white/[0.05] hover:text-slate-300"
                          }`}
                        >
                          {!e.category || e.category === "Uncategorized" ? "✎ Uncategorized" : e.category}
                        </button>
                        <span className="text-slate-700">·</span>
                        <span className="text-slate-600">{e.expense_date}</span>
                      </div>
                    </div>
                    <p className="ml-3 flex-shrink-0 text-sm font-semibold text-emerald-400">
                      ${e.amount.toFixed(2)}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="px-3 py-2 text-[0.72rem] text-slate-600">
                {searchResults
                  ? "No expenses match your search."
                  : "Add expenses in the chat — they'll appear here instantly."}
              </p>
            )}
          </div>

        </div>{/* end scroll body */}
      </div>{/* end intelligence hub */}
    </section>
  );
}
