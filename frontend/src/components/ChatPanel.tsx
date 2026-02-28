import axios from "axios";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { sendChatMessage } from "../api";
import type { ChatMessage } from "../types";

interface ChatPanelProps {
  triggerRefresh?: () => void;
}

export function ChatPanel({ triggerRefresh }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hi! Tell me what you spent \u2014 in your own words. For example: \u201cI spent $70 at Walmart and $20 on Apple subscriptions yesterday.\u201d",
      createdAt: new Date().toISOString(),
    },
  ]);
  const [input, setInput]                     = useState("");
  const [isSending, setIsSending]             = useState(false);
  const [pendingExpenseId, setPendingExpenseId] = useState<number | null>(null);
  const scrollRef  = useRef<HTMLDivElement | null>(null);
  const submitting = useRef(false);

  const orderedMessages = useMemo(
    () => [...messages].sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    [messages],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, isSending]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || submitting.current) return;

    submitting.current = true;
    setIsSending(true);

    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: trimmed, createdAt: new Date().toISOString() },
    ]);
    setInput("");

    try {
      const history = [...messages]
        .slice(-10)
        .filter((m) => m.id !== "welcome")
        .map((m) => ({ role: m.role, content: m.content }));

      const response = await sendChatMessage(trimmed, history, pendingExpenseId);
      const replyText =
        typeof response?.assistant_message === "string" && response.assistant_message.length > 0
          ? response.assistant_message
          : "Done! I\u2019ve recorded that for you.";

      // Track the in-progress expense ID so the next message can update it
      // instead of creating a duplicate entry.
      if (response.needs_clarification && response.pending_expense_id) {
        setPendingExpenseId(response.pending_expense_id);
      } else {
        setPendingExpenseId(null);
      }

      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: replyText, createdAt: new Date().toISOString() },
      ]);
      triggerRefresh?.();
    } catch (err: unknown) {
      setPendingExpenseId(null);
      let msg = "Something went wrong. Please try again in a moment.";
      if (axios.isAxiosError(err)) {
        if (!err.response) {
          msg = "Can\u2019t reach the expense brain. Make sure the backend server is running.";
        } else if (err.response.status < 500) {
          msg =
            err.response.data?.detail ||
            err.response.data?.assistant_message ||
            "I had trouble with that request. Please try again.";
        }
      }
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: msg, createdAt: new Date().toISOString() },
      ]);
    } finally {
      submitting.current = false;
      setIsSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }

  return (
    <section className="glass-panel flex h-full flex-col">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-white/[0.05] px-5 py-3.5">
        <div>
          <p className="text-sm font-semibold tracking-tight text-slate-100">Chat Console</p>
          <p className="text-[0.62rem] text-slate-600">
            Speak naturally \u2014 I\u2019ll handle categories, dates &amp; reports.
          </p>
        </div>
        <span className="rounded-full bg-emerald-950/60 px-2.5 py-1 text-[0.65rem] font-medium text-emerald-400 ring-1 ring-emerald-500/20">
          Live
        </span>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="scroll-thin flex-1 space-y-3 px-5 py-4">
        {orderedMessages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-[0.8rem] leading-relaxed whitespace-pre-line ${
                msg.role === "user"
                  ? "bg-indigo-600/90 text-white shadow-lg shadow-indigo-600/20"
                  : "bg-white/[0.06] text-slate-200 ring-1 ring-white/[0.06]"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {isSending && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-white/[0.06] px-4 py-2.5 text-[0.8rem] text-slate-500 ring-1 ring-white/[0.05]">
              <span className="animate-pulse">Auditing\u2026</span>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex-shrink-0 border-t border-white/[0.05] p-4">
        <div className="flex items-end gap-3">
          <textarea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder='e.g. "spent $45 at Loblaws and $6 at Tim Hortons"'
            className="min-h-[44px] flex-1 resize-none rounded-xl border border-white/[0.07] bg-white/[0.04] px-3.5 py-2.5 text-[0.8rem] text-slate-100 outline-none placeholder:text-slate-600 focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/30 transition-all"
          />
          <button
            type="submit"
            disabled={isSending || !input.trim()}
            className="flex h-[44px] w-[44px] flex-shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-lg shadow-indigo-600/30 hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-white/[0.06] disabled:text-slate-600 transition-all"
          >
            {isSending ? (
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            ) : (
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            )}
          </button>
        </div>
        <p className="mt-1.5 text-center text-[0.58rem] text-slate-700">
          Enter to send \u00b7 Shift+Enter for new line
        </p>
      </form>
    </section>
  );
}
