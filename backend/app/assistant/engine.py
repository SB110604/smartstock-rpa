"""Chat assistant engine (spec 7.8). With an LLM: tool calling over the fixed tools. Without one (or on any LLM
error): a keyword + RapidFuzz intent matcher that calls the same tools. Answers are stored in chat_messages."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import llm
from app.assistant import tools
from app.core.logging import log_ctx
from app.models.ai import ChatMessage
from app.models.core import User
from app.services.pdfbase import inr

logger = logging.getLogger("app.assistant")
MAX_TOOL_ROUNDS = 4

SYSTEM = (
    "You are SmartStock's assistant for an Indian supermarket. Answer briefly using ONLY the tools; never invent numbers. "
    "Currency is INR (₹); dates DD-MM-YYYY. If a tool returns an error, explain it plainly. "
    "Purchase requests you draft are DRAFTs that need normal approval — say so. Reply in the user's language."
)


@dataclass
class Answer:
    reply: str
    mode: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------------ intent matcher

QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|kgs|g|pcs|pieces|packs?|units?|l|ltr|litres?|liters?|dozen|bottles?|boxes?)?\b")
STOP = {"how", "much", "many", "is", "are", "left", "the", "of", "for", "in", "stock", "do", "we", "have", "what", "whats", "show",
        "me", "please", "create", "make", "raise", "draft", "a", "an", "purchase", "request", "pr", "order", "best", "supplier",
        "which", "who", "cheapest", "forecast", "demand", "kitna", "kitni", "bacha", "hai", "kiti", "ahe", "shillak", "baki",
        "with", "to", "from", "our", "any", "there", "get", "give", "tell", "about", "current", "level", "levels",
        "kg", "kgs", "pcs", "pieces", "pack", "packs", "unit", "units", "l", "ltr", "litre", "litres", "dozen", "bottles"}


def _product_phrase(text: str) -> str:
    words = re.findall(r"[a-zA-Zऀ-ॿ0-9]+", text.lower())
    return " ".join(w for w in words if w not in STOP and not w.isdigit()).strip()


def _days(text: str, default: int) -> int:
    t = text.lower()
    m = re.search(r"(\d+)\s*(day|din|divas)", t)
    if m:
        return int(m.group(1))
    if "today" in t or "aaj" in t:
        return 1
    if "tomorrow" in t:
        return 2
    if "month" in t:
        return 30
    if "week" in t or "hafte" in t:
        return 7
    return default


def match_intent(text: str) -> tuple[str, dict[str, Any]] | None:
    t = text.lower().strip()
    if re.search(r"\b(create|draft|raise|make|place)\b.*\b(purchase|request|pr|order)\b", t) or re.search(r"^order \d", t):
        m = QTY_RE.search(t)
        return "draft_purchase_request", {"qty": float(m.group(1)) if m else None, "product": _product_phrase(QTY_RE.sub(" ", t))}
    if re.search(r"expir|expire|एक्सपायर|समाप्त", t):
        return "expiring_items", {"days": _days(t, 7)}
    if re.search(r"pending|approval|approve|waiting for", t):
        return "pending_approvals", {}
    if re.search(r"supplier|vendor|cheapest|who sells|kaun", t):
        return "best_supplier", {"product": _product_phrase(t)}
    if re.search(r"low stock|running low|out of stock|reorder|below", t):
        return "low_stock", {}
    if re.search(r"forecast|demand|predict|next week|next month", t):
        return "demand_forecast", {"product": _product_phrase(t)}
    if re.search(r"\b(sales|revenue|sold|turnover)\b", t):
        return "sales_summary", {"days": _days(t, 7)}
    if re.search(r"purchase orders?|open po|deliver|in transit|\bpos?\b", t):
        return "open_orders", {}
    if re.search(r"how much|how many|left|in stock|stock of|kitna|kitni|kiti|shillak|available", t):
        return "stock_level", {"product": _product_phrase(t)}
    phrase = _product_phrase(t)
    return ("stock_level", {"product": phrase, "guess": True}) if phrase else None


def _fmt_qty(v: float) -> str:
    return f"{v:g}"


def render(name: str, r: dict[str, Any]) -> str:
    """Plain-language answer for a tool result (used by the fallback, and as tool output for the LLM)."""
    if name == "stock_level":
        lines = []
        for i in r["items"]:
            state = {"out": "out of stock", "low": "low — at/below reorder point", "ok": "OK"}[i["status"]]
            lines.append(f"• {i['product']}: {_fmt_qty(i['on_hand'])} {i['unit']} on hand, {_fmt_qty(i['on_order'])} on order ({state}).")
        return "\n".join(lines)
    if name == "expiring_items":
        if not r["items"]:
            return f"Nothing expires in the next {r['days']} days."
        head = f"{len(r['items'])} batch(es) expire within {r['days']} days:"
        return head + "\n" + "\n".join(
            f"• {i['product']} ({i['batch_no']}): {_fmt_qty(i['qty'])} {i['unit']}, "
            + ("expired" if (i["days_left"] or 0) <= 0 else f"{i['days_left']} day(s) left") + f", {inr(i['value'])}"
            for i in r["items"][:10])
    if name == "pending_approvals":
        if not r["total_pending"]:
            return "There are no purchase requests waiting for approval."
        head = f"{r['total_pending']} request(s) pending, {r['waiting_for_you']} waiting for you:"
        return head + "\n" + "\n".join(f"• #{i['id']} {i['product']} — {_fmt_qty(i['qty'])} {i['unit']} from {i['supplier'] or '—'}, "
                                       f"{inr(i['est_total'])} ({i['level']} approval)" for i in r["items"])
    if name == "best_supplier":
        b = r["best"]
        alts = ", ".join(f"{a['name']} ({a['score']:.0f})" for a in r["alternatives"]) or "none"
        return (f"Best supplier for {r['product']}: {b['name']} — score {b['score']:.0f}/100, {inr(b['unit_price'])} per unit, "
                f"about {b['lead_days']:g} days lead time (price {b['breakdown']['price']:.0f}, on-time {b['breakdown']['on_time']:.0f}, "
                f"quality {b['breakdown']['quality']:.0f}). Alternatives: {alts}.")
    if name == "low_stock":
        if not r["count"]:
            return "No products are below their reorder point."
        return f"{r['count']} product(s) need attention:\n" + "\n".join(
            f"• {i['product']}: {_fmt_qty(i['on_hand'])} on hand, {_fmt_qty(i['on_order'])} on order"
            + (f", ROP {i['reorder_point']:.0f}" if i["reorder_point"] is not None else "") + f" ({i['status']})" for i in r["items"])
    if name == "open_orders":
        if not r["count"]:
            return "There are no open purchase orders."
        return f"{r['count']} open purchase order(s):\n" + "\n".join(
            f"• {i['po_no']} — {i['supplier']}, {i['status'].replace('_', ' ').lower()}, expected {i['expected'] or '—'}"
            + (" (late)" if i["late"] else "") for i in r["items"])
    if name == "sales_summary":
        top = ", ".join(f"{t['product']} ({inr(t['revenue'])})" for t in r["top_products"]) or "—"
        return f"Last {r['days']} days: {inr(r['revenue'])} from {r['bills']} bills. Top sellers: {top}."
    if name == "demand_forecast":
        return (f"{r['product']}: about {r['next_7_days']:g} {r['unit']} expected in the next 7 days and {r['next_30_days']:g} "
                f"in the next 30 days" + (f" (reorder point {r['reorder_point']:.0f})." if r["reorder_point"] else "."))
    if name == "draft_purchase_request":
        extra = f" Note: request #{r['existing_open_request']} is already open for this product." if r["existing_open_request"] else ""
        return (f"Draft purchase request #{r['id']} created: {_fmt_qty(r['qty'])} {r['unit']} {r['product']} from "
                f"{r['supplier'] or 'the cheapest supplier'} (~{inr(r['est_total'])}). It is a DRAFT — submit it on the "
                f"Purchase requests page for normal approval.{extra}")
    return json.dumps(r, default=str)


HELP = ("I can answer questions like: “How much rice is left?”, “Which items expire this week?”, “Show pending approvals”, "
        "“Best supplier for sugar?”, “What is the forecast for milk?”, “Sales this week”, or “Create a purchase request for 50 kg sugar”.")


def rules_answer(db: Session, user: User, text: str) -> Answer:
    intent = match_intent(text)
    if not intent:
        return Answer(HELP, "rules")
    name, args = intent
    if name == "draft_purchase_request" and not args.get("qty"):
        return Answer("How much should I order? For example: “Create a purchase request for 50 kg sugar”.", "rules")
    if name in ("stock_level", "best_supplier", "demand_forecast", "draft_purchase_request") and not args.get("product"):
        return Answer("Which product do you mean? " + HELP, "rules")
    guess = bool(args.pop("guess", False))
    try:
        result = tools.call(db, user, name, args)
        return Answer(render(name, result), "rules", [{"name": name, "args": args, "result": result}])
    except tools.ToolError as exc:
        if guess:  # no keyword matched and no product either: the user is not asking about stock
            return Answer(HELP, "rules")
        return Answer(str(exc), "rules", [{"name": name, "args": args, "error": str(exc)}])


# ------------------------------------------------------------------ LLM loop

def llm_answer(db: Session, user: User, provider: llm.Provider, history: list[dict[str, Any]], text: str) -> Answer:
    specs = tools.allowed_tools(user)
    messages = [*history, {"role": "user", "content": text}]
    calls: list[dict[str, Any]] = []
    for _ in range(MAX_TOOL_ROUNDS):
        reply = provider.chat(SYSTEM + f" The user is a {user.role}.", messages, [s.tool for s in specs])
        if not reply.tool_calls:
            return Answer(reply.text or "…", provider.name, calls)
        results = []
        for c in reply.tool_calls:
            try:
                out = tools.call(db, user, c.name, c.arguments)
                calls.append({"name": c.name, "args": c.arguments, "result": out})
                results.append((c, render(c.name, out)))
            except tools.ToolError as exc:
                calls.append({"name": c.name, "args": c.arguments, "error": str(exc)})
                results.append((c, f"ERROR: {exc}"))
        messages += provider.tool_result_messages(reply, results)
    return Answer("I could not finish that request — please rephrase it.", provider.name, calls)


def answer(db: Session, user: User, text: str) -> Answer:
    text = (text or "").strip()[:1000]
    history_rows = list(db.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id)
                                   .order_by(ChatMessage.id.desc()).limit(8)))[::-1]
    db.add(ChatMessage(user_id=user.id, role="user", content=text))
    provider = llm.get_provider()
    result: Answer | None = None
    if provider is not None:
        try:
            result = llm_answer(db, user, provider, [{"role": m.role, "content": m.content} for m in history_rows], text)
        except (llm.LLMError, KeyError, ValueError, TypeError) as exc:
            logger.warning("assistant LLM failed, using rules", extra=log_ctx(error=str(exc)))
    if result is None:
        result = rules_answer(db, user, text)
    db.add(ChatMessage(user_id=user.id, role="assistant", content=result.reply,
                       tool_calls_json=json.loads(json.dumps(result.tool_calls, default=str)) or None))
    db.commit()
    return result


def history(db: Session, user: User, limit: int = 50) -> list[ChatMessage]:
    return list(db.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id).order_by(ChatMessage.id.desc())
                           .limit(limit)))[::-1]


def clear(db: Session, user: User) -> None:
    db.execute(delete(ChatMessage).where(ChatMessage.user_id == user.id))
    db.commit()
