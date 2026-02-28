import { useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { Dashboard } from "./components/Dashboard";

function App() {
  const [refreshCounter, setRefreshCounter] = useState(0);
  function triggerRefresh() {
    setRefreshCounter((c) => c + 1);
  }

  return (
    /* Full-viewport shell — overflow-hidden on desktop, scrollable on mobile */
    <div className="flex h-screen flex-col overflow-hidden bg-[#05050a]">

      {/* Ambient background gradient */}
      <div className="pointer-events-none fixed inset-0 bg-gradient-to-br from-indigo-950/25 via-transparent to-violet-950/15" />

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="relative z-10 flex flex-shrink-0 items-center justify-between border-b border-white/[0.05] px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-600 text-sm font-bold text-white shadow-lg shadow-indigo-600/40">
            ₿
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight text-slate-50">
              LLM Expense Console
            </h1>
            <p className="text-[0.62rem] text-slate-500">AI-native financial auditor</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="live-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
          <span className="font-medium text-emerald-400">Live</span>
          <span className="text-slate-700">·</span>
          <span className="text-slate-500">GPT</span>
        </div>
      </header>

      {/* ── Bento Grid ─────────────────────────────────────────────────── */}
      {/* Desktop: [40% Chat | 60% Intelligence Hub] — no page scroll       */}
      {/* Mobile : stacked columns, natural vertical scroll                  */}
      <main className="relative z-10 flex flex-1 flex-col gap-4 overflow-y-auto p-4 lg:grid lg:grid-cols-[2fr_3fr] lg:overflow-hidden">
        {/* Left — Chat Console (40%) */}
        <ChatPanel triggerRefresh={triggerRefresh} />

        {/* Right — Intelligence Hub (60%) */}
        <Dashboard refreshCounter={refreshCounter} triggerRefresh={triggerRefresh} />
      </main>
    </div>
  );
}

export default App;
