from __future__ import annotations

import json
import logging
import re
from typing import Any, List

import httpx
from httpx import HTTPStatusError, RequestError

from .config import settings

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict[str, Any]:
    """
    Multi-stage extraction so the parser never crashes on impure LLM output.

    Stage 1 — direct JSON parse (happy path, expected path).
    Stage 2 — find the first {...} block via regex (mixed prose + JSON object).
    Stage 3 — find a bare [...] array and wrap it into the expected shape.
    Stage 4 — treat the whole response as a plain-language assistant message
               so the user always sees something useful instead of a crash.
    """
    # Stage 1
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            # Bare array — wrap it
            return {"expenses": parsed, "assistant_message": "", "needs_clarification": False, "follow_up_question": None}
    except json.JSONDecodeError:
        pass

    # Stage 2 — JSON object embedded in prose
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Stage 3 — bare JSON array embedded in prose (e.g. "[{...}, {...}]")
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        try:
            arr = json.loads(arr_match.group())
            if isinstance(arr, list):
                return {"expenses": arr, "assistant_message": "", "needs_clarification": False, "follow_up_question": None}
        except json.JSONDecodeError:
            pass

    # Stage 4 — prose fallback: surface the LLM's text as the assistant message
    return {
        "expenses": [],
        "assistant_message": text.strip(),
        "needs_clarification": True,
        "follow_up_question": text.strip(),
    }


########################################################################
# Alias table — maps casual names / nicknames to canonical merchant names
########################################################################
_MERCHANT_ALIASES: dict[str, str] = {
    # Canadian nicknames
    "timmy's": "Tim Hortons", "timmies": "Tim Hortons", "tims": "Tim Hortons",
    "the bay": "Hudson's Bay", "hbc": "Hudson's Bay",
    "shoppers": "Shoppers Drug Mart", "sdm": "Shoppers Drug Mart",
    "real cdn superstore": "Real Canadian Superstore", "rcss": "Real Canadian Superstore",
    "superstore": "Real Canadian Superstore",
    "mcdonald's": "McDonald's", "mcdonalds": "McDonald's", "mickey d's": "McDonald's",
    "mickey d": "McDonald's",
    "a&w": "A&W Canada",
    "winners": "Winners/Marshalls", "marshalls": "Winners/Marshalls",
    "no frills": "No Frills",
    "food basics": "Food Basics",
    "farm boy": "Farm Boy",
    "second cup": "Second Cup",
    "swiss chalet": "Swiss Chalet",
    "harvey's": "Harvey's", "harveys": "Harvey's",
    "osmow's": "Osmow's", "osmows": "Osmow's",
    "canadian tire": "Canadian Tire",
    "can tire": "Canadian Tire",
    "sport chek": "Sport Chek",
    "loblaws": "Loblaws", "loblaw": "Loblaws",
    "metro": "Metro",
    "sobeys": "Sobeys",
    "dollarama": "Dollarama",
    "rexall": "Rexall",
    # US / global nicknames
    "starbucks": "Starbucks", "sbux": "Starbucks",
    "trader joe's": "Trader Joe's", "trader joes": "Trader Joe's",
    "whole foods": "Whole Foods",
    "costco": "Costco",
}

########################################################################
# Merchant → category lookup (canonical names, lower-cased keys)
########################################################################
_MERCHANT_CATEGORIES: dict[str, str] = {
    # ── Canadian groceries ────────────────────────────────────────────
    "no frills": "groceries",
    "food basics": "groceries",
    "loblaws": "groceries",
    "loblaw": "groceries",
    "sobeys": "groceries",
    "metro": "groceries",
    "real canadian superstore": "groceries",
    "rcss": "groceries",
    "superstore": "groceries",
    "farm boy": "groceries",
    "zehrs": "groceries",
    "freshco": "groceries",
    "highland farms": "groceries",
    "nations fresh foods": "groceries",
    "bulk barn": "groceries",
    "independent grocer": "groceries",
    "valumart": "groceries",
    # ── Canadian coffee & dining ──────────────────────────────────────
    "tim hortons": "restaurants",
    "second cup": "restaurants",
    "swiss chalet": "restaurants",
    "harvey's": "restaurants",
    "harveys": "restaurants",
    "a&w canada": "restaurants",
    "a&w": "restaurants",
    "osmow's": "restaurants",
    "osmows": "restaurants",
    "mary brown's": "restaurants",
    "mary browns": "restaurants",
    "st-hubert": "restaurants",
    "st hubert": "restaurants",
    "boston pizza": "restaurants",
    "the keg": "restaurants",
    "kelsey's": "restaurants",
    "kelseys": "restaurants",
    "pita pit": "restaurants",
    "poutinerie": "restaurants",
    "popeyes": "restaurants",
    # ── Canadian retail & apparel ─────────────────────────────────────
    "hudson's bay": "shopping",
    "hbc": "shopping",
    "roots": "apparel",
    "aritzia": "apparel",
    "lululemon": "apparel",
    "winners/marshalls": "apparel",
    "winners": "apparel",
    "marshalls": "apparel",
    "sport chek": "apparel",
    "reitmans": "apparel",
    "dynamite": "apparel",
    "garage": "apparel",
    "ardene": "apparel",
    "simons": "apparel",
    "bluenotes": "apparel",
    # ── Canadian home & hardware ──────────────────────────────────────
    "canadian tire": "home & hardware",
    "rona": "home & hardware",
    "home hardware": "home & hardware",
    "home depot": "home & hardware",
    "lowes": "home & hardware",
    "lowe's": "home & hardware",
    "ikea": "home & hardware",
    # ── Canadian pharmacy / daily essentials ──────────────────────────
    "shoppers drug mart": "healthcare",
    "shoppers": "healthcare",
    "rexall": "healthcare",
    "dollarama": "shopping",
    "giant tiger": "shopping",
    "jean coutu": "healthcare",
    "familiprix": "healthcare",
    # ── Canadian telecom / utilities ──────────────────────────────────
    "rogers": "utilities",
    "bell": "utilities",
    "telus": "utilities",
    "fido": "utilities",
    "koodo": "utilities",
    "freedom mobile": "utilities",
    "wind mobile": "utilities",
    "videotron": "utilities",
    "shaw": "utilities",
    # ── Canadian transport / fuel ─────────────────────────────────────
    "petro-canada": "transport",
    "petro canada": "transport",
    "esso": "transport",
    "canadian tire gas": "transport",
    "ultramar": "transport",
    "pioneer": "transport",
    # ── Global groceries ─────────────────────────────────────────────
    "walmart": "groceries",
    "costco": "groceries",
    "whole foods": "groceries",
    "trader joe's": "groceries",
    "trader joes": "groceries",
    "trader joe": "groceries",
    "kroger": "groceries",
    "safeway": "groceries",
    "publix": "groceries",
    "aldi": "groceries",
    "wegmans": "groceries",
    "instacart": "groceries",
    # ── Global coffee & dining ────────────────────────────────────────
    "starbucks": "restaurants",
    "mcdonald's": "restaurants",
    "mcdonalds": "restaurants",
    "mcdonald": "restaurants",
    "chipotle": "restaurants",
    "subway": "restaurants",
    "burger king": "restaurants",
    "wendy's": "restaurants",
    "wendys": "restaurants",
    "wendy": "restaurants",
    "taco bell": "restaurants",
    "chick-fil-a": "restaurants",
    "panera": "restaurants",
    "dunkin": "restaurants",
    "domino's": "restaurants",
    "dominos": "restaurants",
    "pizza hut": "restaurants",
    "doordash": "restaurants",
    "uber eats": "restaurants",
    "grubhub": "restaurants",
    "skip the dishes": "restaurants",
    "skipthedishes": "restaurants",
    # ── Global retail ─────────────────────────────────────────────────
    "amazon": "shopping",
    "best buy": "shopping",
    "target": "shopping",
    "zara": "apparel",
    "h&m": "apparel",
    "hm": "apparel",
    "uniqlo": "apparel",
    "shein": "apparel",
    "forever 21": "apparel",
    "nike": "apparel",
    "adidas": "apparel",
    "gap": "apparel",
    "old navy": "apparel",
    "tj maxx": "apparel",
    "banana republic": "apparel",
    "express": "apparel",
    "anthropologie": "apparel",
    "free people": "apparel",
    # ── Global transport ──────────────────────────────────────────────
    "uber": "transport",
    "lyft": "transport",
    "shell": "transport",
    "bp": "transport",
    "exxon": "transport",
    "chevron": "transport",
    "sunoco": "transport",
    "mobil": "transport",
    # ── Global healthcare ─────────────────────────────────────────────
    "cvs": "healthcare",
    "walgreens": "healthcare",
    "rite aid": "healthcare",
    "planet fitness": "healthcare",
    # ── Global utilities ──────────────────────────────────────────────
    "verizon": "utilities",
    "at&t": "utilities",
    "t-mobile": "utilities",
    "comcast": "utilities",
    "xfinity": "utilities",
    "spectrum": "utilities",
    # ── Subscriptions ─────────────────────────────────────────────────
    "netflix": "subscriptions",
    "spotify": "subscriptions",
    "hulu": "subscriptions",
    "disney+": "subscriptions",
    "disney": "subscriptions",
    "apple": "subscriptions",
    "icloud": "subscriptions",
    "youtube": "subscriptions",
    "hbo": "subscriptions",
    "paramount+": "subscriptions",
    "paramount": "subscriptions",
    "peacock": "subscriptions",
    "prime video": "subscriptions",
    "audible": "subscriptions",
    "adobe": "subscriptions",
    "microsoft": "subscriptions",
    "dropbox": "subscriptions",
    "crave": "subscriptions",
    # ── Travel ───────────────────────────────────────────────────────
    "airbnb": "travel",
    "marriott": "travel",
    "hilton": "travel",
    "delta": "travel",
    "air canada": "travel",
    "westjet": "travel",
    "united": "travel",
    "expedia": "travel",
    "booking": "travel",
}

# Keyword-based smart guesser — catches unrecognized stores
_KEYWORD_CATEGORIES: list[tuple[str, str]] = [
    # Grocery signals
    ("grocer", "groceries"),   ("supermarket", "groceries"),
    ("market", "groceries"),   ("foods", "groceries"),
    ("fresh", "groceries"),    ("farm", "groceries"),
    ("produce", "groceries"),  ("organic", "groceries"),
    # Restaurant / cafe signals
    ("cafe", "restaurants"),   ("coffee", "restaurants"),
    ("brew", "restaurants"),   ("bistro", "restaurants"),
    ("grill", "restaurants"),  ("kitchen", "restaurants"),
    ("restaurant", "restaurants"), ("pizza", "restaurants"),
    ("sushi", "restaurants"),  ("bbq", "restaurants"),
    # Pharmacy / health signals
    ("drug", "healthcare"),    ("pharmacy", "healthcare"),
    ("health", "healthcare"),  ("clinic", "healthcare"),
    ("dental", "healthcare"),  ("medical", "healthcare"),
    # Retail / shopping signals
    ("mart", "shopping"),      ("store", "shopping"),
    ("shop", "shopping"),      ("boutique", "shopping"),
    ("outlet", "shopping"),
    # Hardware / home signals
    ("hardware", "home & hardware"), ("supply", "home & hardware"),
    ("lumber", "home & hardware"),
    # Transport / fuel signals
    ("gas", "transport"),      ("fuel", "transport"),
    ("petro", "transport"),    ("parking", "transport"),
    ("transit", "transport"),
    # Utility signals
    ("hydro", "utilities"),    ("electric", "utilities"),
    ("internet", "utilities"),
    # Entertainment signals
    ("cinema", "entertainment"), ("theatre", "entertainment"),
    ("theater", "entertainment"), ("arcade", "entertainment"),
]


def _normalize_merchant(name: str) -> str:
    """Resolve a nickname/alias to its canonical merchant name, title-casing unknowns."""
    key = name.strip().lower()
    if key in _MERCHANT_ALIASES:
        return _MERCHANT_ALIASES[key]
    return name.strip().title()


def _guess_category(merchant: str) -> str:
    """
    Three-tier category resolution:
    1. Exact / substring match in the merchant table (highest precision).
    2. Keyword scan for smart guessing (e.g. 'Sunrise Market' → groceries).
    3. Fallback to 'Uncategorized'.
    """
    m = merchant.lower()

    # Tier 1 — merchant table
    for key, cat in _MERCHANT_CATEGORIES.items():
        if key in m:
            return cat

    # Tier 2 — keyword hints
    for kw, cat in _KEYWORD_CATEGORIES:
        if kw in m:
            return cat

    return "Uncategorized"


def _find_pending_amount(history: list[dict]) -> float | None:
    """
    Scan recent history (last 6 messages) for an unanswered expense amount.

    Returns the float amount if the last assistant message was a clarification
    question ("what store was that?") and the preceding user message contained
    an amount.  Returns None otherwise.
    """
    if not history:
        return None
    recent = history[-6:]

    # Walk backwards to find the last assistant clarification question
    for i in range(len(recent) - 1, -1, -1):
        msg = recent[i]
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "").lower()
        is_clarification = any(kw in content for kw in (
            "what store", "where was that", "which merchant",
            "what was that for", "where did", "store or service",
        ))
        if not is_clarification:
            break  # Last assistant message is not a clarification — nothing pending

        # Find the user message immediately before this assistant message
        for j in range(i - 1, -1, -1):
            if recent[j].get("role") != "user":
                continue
            user_content = recent[j]["content"]
            dollar_amounts = re.findall(r'\$\s*(\d+(?:\.\d{1,2})?)', user_content)
            word_amounts = re.findall(
                r'\b(\d+(?:\.\d{1,2})?)\s*(?:dollars?|bucks?)\b',
                user_content, re.IGNORECASE,
            )
            bare = [a for a in re.findall(r'\b(\d+(?:\.\d{1,2})?)\b', user_content)
                    if float(a) >= 1]
            amounts = dollar_amounts or word_amounts or bare
            if amounts:
                return float(amounts[0])
        break  # Only look at the last assistant message

    return None


def _regex_extract(message: str, history: list[dict] | None = None) -> dict[str, Any]:
    """
    Smart regex-based expense extractor — active when the LLM is unavailable.

    Handles all common natural-language patterns:
      • "$45 at Walmart"          keyword-preceded merchant
      • "Netflix $15.99"          merchant-first, then amount
      • "paid 20 for Spotify"     word amount + keyword
      • "spent 70 on groceries"   vague (no named merchant)
      • "Starbucks 5.50"          bare name + bare number
      • "Aritzia" (after AI asked for the store) — multi-turn context link

    Returns the same dict shape as extract_expenses so the rest of the
    pipeline is completely unaffected.
    """
    from datetime import date as _date
    today = _date.today().isoformat()

    # ── Step 1: Extract all monetary amounts ────────────────────────────
    # Priority order: $X.XX  →  X dollars/bucks  →  bare number ≥ 1
    dollar_amounts = re.findall(r'\$\s*(\d+(?:\.\d{1,2})?)', message)
    word_amounts   = re.findall(r'\b(\d+(?:\.\d{1,2})?)\s*(?:dollars?|bucks?)\b',
                                message, re.IGNORECASE)
    bare_amounts   = re.findall(r'\b(\d+(?:\.\d{1,2})?)\b', message)
    bare_amounts   = [a for a in bare_amounts if float(a) >= 1]

    all_amounts = dollar_amounts or word_amounts or bare_amounts

    if not all_amounts:
        # ── Multi-turn context: no amounts in this message ───────────────────
        # Check if this message looks like a merchant-only reply to a prior
        # clarification question (e.g. the AI asked "What store was that?" and
        # the user replied "Aritzia").
        msg_stripped = message.strip()
        is_merchant_like = (
            2 <= len(msg_stripped) <= 50
            and not re.search(r'\d', msg_stripped)  # no digits
        )
        if is_merchant_like and history:
            pending_amount = _find_pending_amount(history)
            if pending_amount is not None:
                merchant = _normalize_merchant(msg_stripped)
                category = _guess_category(merchant)
                cat_note = "" if category == "Uncategorized" else f" under {category.title()}"
                logged = f"${pending_amount:.2f} at {merchant}"
                return {
                    "expenses": [{
                        "merchant": merchant,
                        "amount": pending_amount,
                        "currency": "CAD",
                        "category": category,
                        "note": "",
                        "expense_date": today,
                    }],
                    "assistant_message": (
                        f"Got it! I\u2019ve logged {logged}{cat_note}. "
                        "Is there anything else you\u2019d like to log?"
                    ),
                    "needs_clarification": False,
                    "follow_up_question": None,
                }

        return {
            "expenses": [],
            "assistant_message": (
                "I didn\u2019t catch a clear expense in that message. "
                "Try something like \u201cI spent $30 at Starbucks.\u201d "
                "Is there anything else I can help with?"
            ),
            "needs_clarification": False,
            "follow_up_question": None,
        }

    # ── Step 2: Extract merchant names ──────────────────────────────────
    # Strategy A: keyword-preceded — "at / on / for / from / in <Merchant>"
    kw_merchants = re.findall(
        r'(?:at|on|for|from|in)\s+([A-Za-z][A-Za-z0-9\s&\'\-]{1,28}?)'
        r'(?=\s*[\.\,\!\?]|\s+(?:and|for|\$|\d)|$)',
        message, re.IGNORECASE,
    )

    _STOP_WORDS = {
        "at", "on", "for", "from", "in", "to", "the", "a", "an", "my",
        "and", "or", "but", "with", "by", "of", "dollars", "bucks",
        "spent", "paid", "bought", "got", "just", "was", "is", "about",
    }

    # Strategy B: word(s) immediately before a dollar sign
    #   e.g. "Netflix $15" or "netflix $15"
    cap_before_dollar = re.findall(
        r'([A-Za-z][a-zA-Z0-9&\'\-]{1,20}(?:\s+[A-Za-z][a-zA-Z0-9&\'\-]{1,20})?)'
        r'\s+\$\d',
        message,
    )
    cap_before_dollar = [m for m in cap_before_dollar if m.strip().lower() not in _STOP_WORDS]

    # Strategy C: word(s) right after the amount
    #   e.g. "$15 Netflix" or "15 zara"
    cap_after_amount = re.findall(
        r'\$?\d+(?:\.\d{1,2})?\s+([A-Za-z][a-zA-Z0-9&\'\-]{2,20})',
        message,
    )
    cap_after_amount = [m for m in cap_after_amount if m.strip().lower() not in _STOP_WORDS]

    # Merge in priority order, deduplicate
    seen: set[str] = set()
    merged_merchants: list[str] = []
    for m in kw_merchants + cap_before_dollar + cap_after_amount:
        clean = m.strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            merged_merchants.append(clean)

    # ── Step 3: Pair amounts with merchants ─────────────────────────────
    expenses = []
    for i, raw in enumerate(all_amounts):
        raw_merchant = merged_merchants[i].strip() if i < len(merged_merchants) else "Pending"
        merchant = _normalize_merchant(raw_merchant)   # resolve aliases first
        category = _guess_category(merchant)
        expenses.append({
            "merchant": merchant,
            "amount": float(raw),
            "currency": "USD",
            "category": category,
            "note": "",
            "expense_date": today,
        })

    # ── Step 4: Build conversational reply ──────────────────────────────
    needs_clarification = any(e["merchant"] == "Pending" for e in expenses)

    if len(expenses) == 1:
        e = expenses[0]
        cat_note = "" if e["category"] == "Uncategorized" else f" under {e['category'].title()}"
        logged = f"${e['amount']:.2f} at {e['merchant']}{cat_note}"
    else:
        logged = ", ".join(
            f"${e['amount']:.2f} at {e['merchant']}" for e in expenses
        )

    if needs_clarification:
        follow_up = "What store or service was that for?"
        reply = (
            f"I\u2019ve noted the expense! {follow_up}"
        )
    else:
        follow_up = None
        reply = (
            f"Got it! I\u2019ve updated the app with your expense \u2014 {logged}. "
            "Is there anything else you\u2019d like to log?"
        )

    return {
        "expenses": expenses,
        "assistant_message": reply,
        "needs_clarification": needs_clarification,
        "follow_up_question": follow_up,
    }


class LLMClient:
    """
    Thin wrapper around an LLM API (e.g. OpenAI) used exclusively for semantic
    understanding and structured extraction, not hand-written parsing rules.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model

    async def extract_expenses(
        self, message: str, history: List[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """
        Ask the LLM to read the user's message (with optional prior conversation
        history for multi-turn context) and return structured expenses plus a
        warm conversational reply.

        Returns a dict with keys:
          expenses          – list of expense dicts
          reply             – AI-generated natural language confirmation
          needs_clarification – True when more info is needed (e.g. no merchant)
          follow_up_question  – the question to ask the user if clarification needed
        """
        from datetime import date as _date
        today = _date.today().isoformat()

        default = {
            "expenses": [],
            "assistant_message": "I'm having trouble reaching my AI brain right now. Please try again in a moment.",
            "needs_clarification": False,
            "follow_up_question": None,
        }

        if not self.api_key:
            return _regex_extract(message, history)


        system_prompt = (
            f"You are a helpful Wealth Auditor AI with deep knowledge of the Canadian "
            f"retail market. Today's date is {today}.\n\n"

            "EXPENSE DETECTION — be generous:\n"
            "- merchant + amount = always an expense, even without 'spent' or 'paid'.\n"
            "- 'just paid $15.99 for Netflix', 'Netflix $15.99', '$45 at Walmart', "
            "'grabbed coffee for $5' → all are expenses.\n"
            "- Multiple expenses in one message are fine.\n"
            "- Be robust to casual phrasing, nicknames, slang, and typos.\n"
            "- Infer the date as today unless the user says otherwise.\n"
            "- Assume CAD unless the user specifies otherwise.\n\n"

            "CANADIAN RETAIL INTELLIGENCE — always resolve nicknames to the correct "
            "canonical store name and assign the right category:\n"
            "  Groceries: No Frills, Food Basics, Loblaws, Sobeys, Metro, "
            "Real Canadian Superstore, Farm Boy, Zehrs, FreshCo, Bulk Barn\n"
            "  Coffee/Dining: Tim Hortons (Timmy's / Timmies), Second Cup, "
            "Swiss Chalet, Harvey's, A&W Canada, Osmow's, Mary Brown's, "
            "St-Hubert, Boston Pizza, The Keg, Pita Pit, Skip The Dishes\n"
            "  Apparel: Aritzia, Lululemon, Roots, Zara, H&M, Uniqlo, Nike, Adidas, "
            "Gap, Old Navy, Winners/Marshalls, Simons, Reitmans, Sport Chek\n"
            "  Retail/Shopping: Hudson's Bay (The Bay), Amazon, Best Buy, Target\n"
            "  Home & Hardware: Canadian Tire, RONA, Home Hardware\n"
            "  Daily Essentials: Shoppers Drug Mart, Rexall, Dollarama, Giant Tiger\n"
            "  Telecom/Utilities: Rogers, Bell, Telus, Fido, Koodo, Freedom Mobile\n"
            "  Transport/Fuel: Petro-Canada, Esso, Canadian Tire Gas Bar, Ultramar\n"
            "  Entertainment: Cineplex, Scene\n\n"

            "SMART GUESSING — if the store is unrecognized:\n"
            "- Name contains 'Market', 'Foods', 'Fresh', 'Farm', 'Grocer', 'Produce' "
            "→ category = groceries\n"
            "- Name contains 'Mart', 'Store', 'Shop', 'Boutique' → shopping\n"
            "- Name contains 'Cafe', 'Coffee', 'Brew', 'Bistro', 'Grill', 'Kitchen' "
            "→ restaurants\n"
            "- Name contains 'Drug', 'Pharmacy', 'Health', 'Clinic' → healthcare\n"
            "- Name contains 'Hardware', 'Supply', 'Lumber' → home & hardware\n"
            "- Name contains 'Gas', 'Fuel', 'Petro' → transport\n"
            "- Otherwise → Uncategorized\n\n"

            "WHEN INFO IS MISSING:\n"
            "- Amount present but NO merchant → log with merchant='Pending', "
            "needs_clarification=true, ask 'I've noted the $X — what store was that at?'\n"
            "- If the current message is ONLY a merchant name (no amount) and the "
            "conversation history shows you previously asked for the store name after "
            "logging an amount, link them: use the pending amount + the new merchant.\n"
            "- If conversation history already answers the missing field, resolve it "
            "and set needs_clarification=false.\n"
            "- NEVER return an empty response or error — always guide the user.\n\n"

            "CATEGORIES (use exactly one of these):\n"
            "groceries, restaurants, subscriptions, entertainment, travel, healthcare,\n"
            "shopping, apparel, home & hardware, utilities, transport, education, Uncategorized\n\n"

            "REPLY GUIDELINES:\n"
            "- Always write a warm, specific 1-3 sentence assistant_message.\n"
            "- Confirm exactly what was logged: use the canonical merchant name and amount.\n"
            "- End EVERY reply with a short friendly follow-up like "
            "'Is there anything else you'd like to log?'\n"
            "- If category is 'Uncategorized', note it briefly.\n\n"

            "CRITICAL: Your entire response MUST be valid JSON. "
            "Never return plain text or prose outside the JSON object.\n\n"

            "OUTPUT — pure JSON only:\n"
            "{\n"
            '  "expenses": [\n'
            '    {"merchant": "Tim Hortons", "amount": 5.00, "currency": "CAD",\n'
            '     "category": "restaurants", "note": "morning coffee",\n'
            '     "expense_date": "YYYY-MM-DD"}\n'
            "  ],\n"
            '  "assistant_message": "Got it! $5.00 at Tim Hortons logged under Restaurants. Anything else?",\n'
            '  "needs_clarification": false,\n'
            '  "follow_up_question": null\n'
            "}"
        )

        # Build the messages array: system + prior history + current user message
        messages: List[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for h in (history or []):
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
        except HTTPStatusError as exc:
            logger.warning(
                "LLM HTTP error while extracting expenses: %s (status=%s)",
                exc,
                exc.response.status_code if exc.response else None,
            )
            return _regex_extract(message, history)
        except RequestError as exc:
            logger.warning("LLM network error while extracting expenses: %s", exc)
            return _regex_extract(message, history)

        parsed = _extract_json(content)
        expenses = parsed.get("expenses") or []
        if not isinstance(expenses, list):
            expenses = []
        # Accept both 'assistant_message' (new) and 'reply' (legacy fallback)
        msg = (
            parsed.get("assistant_message")
            or parsed.get("reply")
            or ""
        )
        return {
            "expenses": expenses,
            "assistant_message": str(msg),
            "needs_clarification": bool(parsed.get("needs_clarification", False)),
            "follow_up_question": parsed.get("follow_up_question") or None,
        }


    async def search_expenses(self, query: str) -> dict[str, Any]:
        """
        Translate a natural-language spending question into structured DB
        filters.  Falls back to _local_search when the LLM is unavailable.
        """
        from datetime import date as _date
        today = _date.today().isoformat()

        if not self.api_key:
            return _local_search(query)

        system_prompt = (
            f"You are an expense search assistant. Today is {today}.\n"
            "Given a natural language question about spending, produce a JSON "
            "filter object to query an expense database.\n\n"
            "Columns: merchant (text), amount (float), category (text), "
            "expense_date (date YYYY-MM-DD), note (text).\n\n"
            "Valid categories: groceries, restaurants, subscriptions, "
            "entertainment, travel, healthcare, shopping, home & hardware, "
            "utilities, transport, education, apparel, Uncategorized.\n\n"
            "SEMANTIC UNDERSTANDING:\n"
            "- 'unhealthy spending' → fast food chains (McDonald's, Burger King, "
            "Wendy's, Taco Bell, KFC, etc.) and liquor stores (LCBO, Beer Store)\n"
            "- 'Canadian stores' → Canadian retailers (Tim Hortons, Loblaws, "
            "Canadian Tire, Shoppers Drug Mart, etc.)\n"
            "- 'coffee' → Starbucks, Tim Hortons, Second Cup, Dunkin\n"
            "- 'eating out' / 'dining' → category 'restaurants'\n"
            "- 'clothes' / 'fashion' → category 'apparel'\n"
            "- 'streaming' → Netflix, Spotify, Disney+, etc.\n"
            "- 'gas' / 'fuel' → Petro-Canada, Esso, Shell, etc.\n\n"
            "Return ONLY valid JSON with these keys:\n"
            "{\n"
            '  "merchants": ["name1", "name2"],\n'
            '  "categories": ["cat1"],\n'
            '  "date_from": "YYYY-MM-DD" or null,\n'
            '  "date_to": "YYYY-MM-DD" or null,\n'
            '  "amount_min": number or null,\n'
            '  "amount_max": number or null,\n'
            '  "summary_text": "Short natural-language description"\n'
            "}"
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
        except (HTTPStatusError, RequestError) as exc:
            logger.warning("LLM search error: %s — falling back to local search", exc)
            return _local_search(query)

        try:
            parsed = json.loads(content)
            return {
                "merchants": parsed.get("merchants") or [],
                "categories": parsed.get("categories") or [],
                "date_from": parsed.get("date_from"),
                "date_to": parsed.get("date_to"),
                "amount_min": parsed.get("amount_min"),
                "amount_max": parsed.get("amount_max"),
                "summary_text": parsed.get("summary_text", ""),
            }
        except Exception:
            return _local_search(query)

    async def audit_expense(self, expense: dict, spending_summary: str) -> dict:
        """
        Ask the LLM to act as a financial auditor for a single expense.
        Returns financial_impact_score (0-100), strategic_insight, and ai_reasoning_path.
        Safe default returned on missing API key or any error.
        """
        default = {"financial_impact_score": 0, "strategic_insight": "", "ai_reasoning_path": ""}

        if not self.api_key:
            return default

        system_prompt = (
            "You are a financial auditor AI. You will be given a single expense and a "
            "compact JSON summary of the user's recent spending history.\n\n"
            "Your task:\n"
            "1. financial_impact_score: integer 0-100 (higher = more financial concern or risk)\n"
            "2. strategic_insight: 1-2 actionable sentences about this expense\n"
            "3. ai_reasoning_path: brief chain-of-thought explaining how you arrived at the score\n\n"
            "Output strictly valid JSON with exactly these three keys and nothing else:\n"
            "{\"financial_impact_score\": <int>, \"strategic_insight\": \"<str>\", \"ai_reasoning_path\": \"<str>\"}"
        )

        user_content = (
            f"Expense: {json.dumps(expense)}\n\n"
            f"Spending context: {spending_summary}"
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
        except HTTPStatusError as exc:
            logger.warning(
                "LLM HTTP error while auditing expense: %s (status=%s)",
                exc,
                exc.response.status_code if exc.response else None,
            )
            return default
        except RequestError as exc:
            logger.warning("LLM network error while auditing expense: %s", exc)
            return default

        try:
            parsed = json.loads(content)
            return {
                "financial_impact_score": int(parsed.get("financial_impact_score") or 0),
                "strategic_insight": str(parsed.get("strategic_insight") or ""),
                "ai_reasoning_path": str(parsed.get("ai_reasoning_path") or ""),
            }
        except Exception:
            return default

    async def get_savings_advice(self, message: str, analytics: dict) -> str:
        """
        Generate personalised savings advice backed by real DB analytics.
        Falls back to _local_savings_advice when no API key or on any error.
        """
        if not self.api_key:
            return _local_savings_advice(analytics)

        system_prompt = (
            "You are a sharp, data-driven personal financial advisor embedded in a spending tracker app. "
            "The user has asked a question about their finances and you have access to their REAL spending data.\n\n"
            "Rules:\n"
            "- Reference specific categories, exact dollar amounts, and merchant names from the data.\n"
            "- Identify the top 2-3 concrete savings opportunities with specific numbers.\n"
            "- Call out categories significantly above their 3-month average and explain what's driving the spike.\n"
            "- If subscriptions exist, mention the total and name any that seem redundant.\n"
            "- Be direct and specific — avoid generic advice like 'make a budget' or 'track your spending'.\n"
            "- Write in second person ('You're spending...'), warm and conversational tone.\n"
            "- Use 3-5 short paragraphs. Each paragraph = one insight or recommendation.\n"
            "- End with a short invite to dig deeper ('Want me to break down any of these further?').\n"
            "- Do NOT use markdown headers, bullet symbols, or asterisks — plain text with line breaks only.\n"
            "- Do NOT repeat the raw JSON back — synthesise it into actionable insight."
        )

        user_content = (
            f"User's question: {message}\n\n"
            f"Their spending data:\n{json.dumps(analytics, indent=2)}"
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except (HTTPStatusError, RequestError) as exc:
            logger.warning("LLM savings advice error: %s — using local fallback", exc)
            return _local_savings_advice(analytics)
        except Exception as exc:
            logger.warning("Unexpected savings advice error: %s — using local fallback", exc)
            return _local_savings_advice(analytics)

    async def analyze_drift(self, drifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Send category drift data to the LLM for Wealthsimple-tone insights.
        Falls back to _local_drift_insights when no API key or on error.
        """
        if not self.api_key or not drifts:
            return _local_drift_insights(drifts)

        user_content = json.dumps(drifts, indent=2)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": PROMPT_DRIFT_ANALYSIS},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
        except (HTTPStatusError, RequestError) as exc:
            logger.warning("LLM drift analysis error: %s — using local fallback", exc)
            return _local_drift_insights(drifts)

        try:
            parsed = json.loads(content)
            items = parsed if isinstance(parsed, list) else parsed.get("insights", parsed.get("data", []))
            if not isinstance(items, list):
                return _local_drift_insights(drifts)
            by_cat = {it["category"].lower(): it for it in items if isinstance(it, dict)}
            merged: list[dict[str, Any]] = []
            for d in drifts:
                llm_row = by_cat.get(d["category"].lower(), {})
                merged.append({
                    "category": d["category"],
                    "insight": str(llm_row.get("insight", "")),
                    "action": str(llm_row.get("action", "")),
                    "status": llm_row.get("status", "stable"),
                })
            return merged
        except Exception:
            return _local_drift_insights(drifts)


########################################################################
# Semantic concept map — maps natural-language concepts to DB filters
########################################################################
_SEARCH_CONCEPTS: dict[str, dict[str, list[str]]] = {
    "unhealthy": {
        "merchants": [
            "McDonald's", "Burger King", "Wendy's", "Taco Bell", "KFC",
            "Popeyes", "Pizza Hut", "Domino's", "Subway", "Chick-fil-A",
            "Harvey's", "A&W Canada", "Mary Brown's",
            "LCBO", "Beer Store", "SAQ", "Wine Rack",
        ],
    },
    "junk food": {
        "merchants": [
            "McDonald's", "Burger King", "Wendy's", "Taco Bell", "KFC",
            "Popeyes", "Pizza Hut", "Domino's", "Subway", "Chick-fil-A",
        ],
    },
    "fast food": {
        "merchants": [
            "McDonald's", "Burger King", "Wendy's", "Taco Bell", "KFC",
            "Popeyes", "Subway", "Chick-fil-A", "A&W Canada", "Harvey's",
            "Mary Brown's",
        ],
    },
    "liquor": {
        "merchants": ["LCBO", "Beer Store", "SAQ", "Wine Rack"],
    },
    "alcohol": {
        "merchants": ["LCBO", "Beer Store", "SAQ", "Wine Rack"],
    },
    "coffee": {
        "merchants": ["Starbucks", "Tim Hortons", "Second Cup", "Dunkin"],
    },
    "canadian": {
        "merchants": [
            "Tim Hortons", "Loblaws", "No Frills", "Sobeys", "Metro",
            "Food Basics", "Real Canadian Superstore", "Farm Boy",
            "Shoppers Drug Mart", "Canadian Tire", "Hudson's Bay",
            "Roots", "Aritzia", "Lululemon", "Winners/Marshalls",
            "Sport Chek", "Rexall", "Dollarama", "RONA", "Home Hardware",
            "Rogers", "Bell", "Telus", "Petro-Canada", "Esso",
            "Swiss Chalet", "Harvey's", "A&W Canada", "Osmow's",
            "Second Cup", "Boston Pizza", "The Keg", "Air Canada", "WestJet",
        ],
    },
    "dining": {"categories": ["restaurants"]},
    "eating out": {"categories": ["restaurants"]},
    "restaurant": {"categories": ["restaurants"]},
    "food": {"categories": ["groceries", "restaurants"]},
    "clothes": {"categories": ["apparel"]},
    "clothing": {"categories": ["apparel"]},
    "fashion": {"categories": ["apparel"]},
    "streaming": {
        "merchants": [
            "Netflix", "Spotify", "Hulu", "Disney+", "HBO",
            "Paramount+", "Peacock", "Prime Video", "Crave", "YouTube",
        ],
        "categories": ["subscriptions"],
    },
    "gas": {
        "merchants": [
            "Petro-Canada", "Esso", "Shell", "BP", "Exxon",
            "Chevron", "Sunoco", "Ultramar",
        ],
    },
    "fuel": {
        "merchants": [
            "Petro-Canada", "Esso", "Shell", "BP", "Exxon",
            "Chevron", "Sunoco", "Ultramar",
        ],
    },
    "pharmacy": {
        "merchants": ["Shoppers Drug Mart", "Rexall", "CVS", "Walgreens"],
        "categories": ["healthcare"],
    },
    "online shopping": {
        "merchants": ["Amazon", "Shein"],
        "categories": ["shopping"],
    },
}

_ALL_CATEGORIES = [
    "groceries", "restaurants", "subscriptions", "entertainment",
    "travel", "healthcare", "shopping", "home & hardware",
    "utilities", "transport", "education", "apparel",
]


def _local_search(query: str) -> dict[str, Any]:
    """
    Regex / concept-map search filter generator — active when the LLM
    is unavailable.  Maps natural-language queries to structured filters.
    """
    from datetime import date as _date, timedelta

    q = query.lower().strip()

    # Strip common question prefixes so "how much at Starbucks?" → "starbucks"
    for prefix in [
        "how much did i spend", "how much have i spent", "what did i spend",
        "show me my", "show me", "find my", "find all", "find", "search for",
        "search", "how much", "what are my", "where did i spend", "list",
    ]:
        if q.startswith(prefix):
            q = q[len(prefix):].strip()
            break
    q = q.rstrip("?!.,").strip()
    for prep in ["at", "on", "for", "in", "from"]:
        if q.startswith(prep + " "):
            q = q[len(prep):].strip()
            break

    merchants: list[str] = []
    categories: list[str] = []
    date_from: str | None = None
    date_to: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None

    # ── Concept map matching ──────────────────────────────────────────
    for concept, filters in _SEARCH_CONCEPTS.items():
        if concept in q:
            merchants.extend(filters.get("merchants", []))
            categories.extend(filters.get("categories", []))

    # ── Direct merchant / alias matching ──────────────────────────────
    for alias, canonical in _MERCHANT_ALIASES.items():
        if alias in q:
            merchants.append(canonical)
    for merchant_key in _MERCHANT_CATEGORIES:
        if merchant_key in q:
            merchants.append(merchant_key.title())

    # ── Category name matching ────────────────────────────────────────
    for cat in _ALL_CATEGORIES:
        if cat in q:
            categories.append(cat)

    # ── Date handling ─────────────────────────────────────────────────
    today = _date.today()
    if "today" in q:
        date_from = today.isoformat()
        date_to = today.isoformat()
    elif "yesterday" in q:
        d = today - timedelta(days=1)
        date_from = date_to = d.isoformat()
    elif "this week" in q:
        date_from = (today - timedelta(days=today.weekday())).isoformat()
        date_to = today.isoformat()
    elif "last week" in q:
        start = today - timedelta(days=today.weekday() + 7)
        date_from = start.isoformat()
        date_to = (start + timedelta(days=6)).isoformat()
    elif "this month" in q:
        date_from = today.replace(day=1).isoformat()
        date_to = today.isoformat()
    elif "last month" in q:
        first = today.replace(day=1)
        end = first - timedelta(days=1)
        date_from = end.replace(day=1).isoformat()
        date_to = end.isoformat()

    # ── Amount handling ───────────────────────────────────────────────
    amt_matches = re.findall(r'\$(\d+(?:\.\d{1,2})?)', q)
    if amt_matches:
        amounts = [float(a) for a in amt_matches]
        if len(amounts) == 1:
            if any(w in q for w in ("over", "above", "more than")):
                amount_min = amounts[0]
            elif any(w in q for w in ("under", "below", "less than")):
                amount_max = amounts[0]
        if len(amounts) >= 2:
            amount_min = min(amounts)
            amount_max = max(amounts)

    # ── Deduplicate ───────────────────────────────────────────────────
    merchants = list(dict.fromkeys(merchants))
    categories = list(dict.fromkeys(categories))

    # ── Build summary ─────────────────────────────────────────────────
    if merchants or categories:
        parts = []
        if merchants:
            shown = merchants[:5]
            tail = f" +{len(merchants) - 5} more" if len(merchants) > 5 else ""
            parts.append(", ".join(shown) + tail)
        if categories:
            parts.append(", ".join(c.title() for c in categories))
        summary_text = f"Searching {' · '.join(parts)}"
    else:
        merchants = [query.strip()]
        summary_text = f'Searching for "{query.strip()}"'

    return {
        "merchants": merchants,
        "categories": categories,
        "date_from": date_from,
        "date_to": date_to,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "summary_text": summary_text,
    }


########################################################################
# Financial Drift Engine — prompt & local fallback
########################################################################
PROMPT_DRIFT_ANALYSIS = (
    "You are a financial advisor with a Wealthsimple tone: witty, simple, "
    "professional, and supportive.\n\n"
    "You will be given spending drift data for one or more categories. "
    "Each entry contains:\n"
    "  - category: the spending category\n"
    "  - current_total: total spending this month so far\n"
    "  - median_total: median monthly spending over the previous 3 months\n"
    "  - drift_pct: percentage change (positive = spending more than usual)\n\n"
    "For EACH category:\n"
    "1. Calculate the percentage drift (current vs median).\n"
    "2. Write a 1-sentence supportive but direct insight "
    "(Wealthsimple tone: witty, simple, professional).\n"
    "3. If drift is >10% higher, suggest a specific 'Wealthsimple' action "
    "(e.g., setting a Recurring Deposit or moving excess to a TFSA).\n"
    "   If drift is <=10% or negative, set action to \"\".\n"
    "4. Status: \"warning\" if drift > 10%, \"improving\" if drift < -10%, "
    "\"stable\" otherwise.\n\n"
    "Return ONLY a JSON array (no extra text):\n"
    "[{\"category\": \"...\", \"insight\": \"...\", \"action\": \"...\", "
    "\"status\": \"warning\"|\"stable\"|\"improving\"}]"
)


def _local_drift_insights(drifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate Wealthsimple-tone drift insights without the LLM."""
    results: list[dict[str, Any]] = []
    for d in drifts:
        cat = d["category"]
        pct = d["drift_pct"]
        if pct > 50:
            results.append({
                "category": cat,
                "insight": (
                    f"Your {cat} spending jumped {pct:.0f}% this month "
                    f"\u2014 that\u2019s a big shift worth a closer look."
                ),
                "action": (
                    "Consider moving some of the excess into your TFSA "
                    "or setting up a Recurring Deposit."
                ),
                "status": "warning",
            })
        elif pct > 10:
            results.append({
                "category": cat,
                "insight": (
                    f"Your {cat} spending crept up {pct:.0f}% "
                    f"\u2014 not a crisis, but worth watching."
                ),
                "action": (
                    "Try setting a monthly budget for this category "
                    "to keep it in check."
                ),
                "status": "warning",
            })
        elif pct < -30:
            results.append({
                "category": cat,
                "insight": (
                    f"Your {cat} spending dropped {abs(pct):.0f}% "
                    f"\u2014 impressive discipline this month."
                ),
                "action": "",
                "status": "improving",
            })
        elif pct < -10:
            results.append({
                "category": cat,
                "insight": (
                    f"You\u2019ve trimmed {abs(pct):.0f}% off your "
                    f"{cat} spending \u2014 keep it up."
                ),
                "action": "",
                "status": "improving",
            })
        else:
            results.append({
                "category": cat,
                "insight": (
                    f"Your {cat} spending is tracking close to your "
                    f"usual pattern \u2014 right on track."
                ),
                "action": "",
                "status": "stable",
            })
    return results


########################################################################
# Local savings-advice fallback (no API key)
########################################################################

def _local_savings_advice(analytics: dict) -> str:
    """Rule-based savings advice built from DB analytics when no LLM is available."""
    period = analytics.get("period", "this month")
    month_total = analytics.get("month_total", 0.0)
    breakdown = analytics.get("category_breakdown", [])
    warnings = analytics.get("drift_warnings", [])
    subs = analytics.get("subscriptions", [])
    subs_total = analytics.get("subscriptions_total", 0.0)
    top_merchants = analytics.get("top_merchants", [])

    lines = [f"Here's where your money is going in {period} (${month_total:,.2f} total):\n"]

    # Drift warnings — highest-value savings opportunities
    if warnings:
        lines.append("Categories running above your 3-month average:")
        for w in warnings[:4]:
            cat = w["category"].title()
            pct = w["drift_pct"]
            this = w["this_month"]
            avg = w["3mo_median"]
            arrow = "↑" if pct > 0 else "↓"
            lines.append(
                f"  {arrow} {cat}: ${this:,.2f} this month vs your usual ${avg:,.2f} "
                f"({'+' if pct > 0 else ''}{pct:.0f}%)"
            )
        lines.append("")

    # Subscriptions
    if subs_total > 0:
        sub_names = ", ".join(s["merchant"] for s in subs)
        lines.append(
            f"Subscriptions: ${subs_total:,.2f}/month — {sub_names}. "
            "Check if you're actively using all of them."
        )
        lines.append("")

    # Biggest spending category
    if breakdown:
        top = breakdown[0]
        lines.append(
            f"Your biggest category is {top['category'].title()} "
            f"at ${top['this_month']:,.2f}. "
            "Even a 10% reduction here would add up over the year."
        )
        lines.append("")

    # Top merchant
    if top_merchants:
        m = top_merchants[0]
        lines.append(
            f"Top merchant: {m['merchant']} — ${m['total']:,.2f} across "
            f"{m['visits']} visit{'s' if m['visits'] != 1 else ''} this month."
        )
        lines.append("")

    lines.append("Click any drift card in the Intelligence Hub to deep-dive into a category. Anything specific you'd like to focus on?")
    return "\n".join(lines)


llm_client = LLMClient()


