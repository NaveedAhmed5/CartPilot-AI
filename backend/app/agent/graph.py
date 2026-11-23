"""The CartPilot LangGraph agent.

    START -> safety_guard --(blocked)--> END
                  |
                  v
            memory_loader -> sales_agent <-> tools
                                  |
                                  v
                                 END

- safety_guard  : deterministic screen for injection, other-user data, off-topic (no LLM call).
- memory_loader : loads and updates long-term memory (Postgres, per user_id).
- sales_agent   : Claude Haiku 5.5 with tools, short-term memory = the thread's messages.
- tools         : executes tool calls scoped to the user, enforces risky-action confirmation.

Short-term memory is the LangGraph Postgres checkpointer keyed by "<user_id>::<thread_id>".
"""

import logging
import threading
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .. import database as db
from .. import llm
from ..config import settings
from .memory import extract_facts
from .prompts import STATIC_PROMPT, session_block
from .safety import screen
from .tools import CLEAR, ToolContext, compact_args, langchain_tools, run_tool

log = logging.getLogger("cartpilot.agent")

FALLBACK_REPLY = (
    "Sorry, I'm having trouble completing that right now. Could you try again in a moment or rephrase?"
)
TIME_LIMIT_REPLY = (
    "Sorry, that's taking longer than expected on my side. Could you send your request again, "
    "or ask about one thing at a time?"
)
STEP_LIMIT_REPLY = (
    "Sorry, that took more steps than expected. Could you tell me a bit more specifically what you need?"
)


class AgentState(TypedDict, total=False):
    messages: Annotated[List[AnyMessage], add_messages]
    user_id: str
    turn: int
    pending_action: Optional[Dict[str, Any]]
    profile: Optional[Dict[str, Any]]
    blocked: Optional[str]
    error: bool
    steps: int
    turn_tool_calls: List[Dict[str, Any]]
    turn_tokens: Dict[str, int]
    turn_started: float


# ------------------------------------------------------------------------- helpers
def last_human_text(messages: List[AnyMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m.text if isinstance(m.content, list) else str(m.content)
    return ""


def prepare_history(messages: List[AnyMessage], window: int) -> List[AnyMessage]:
    """Return a valid, bounded slice of the conversation for the model.

    Drops tool calls that never got results (e.g. after a crash) and orphan tool
    results, then keeps the last `window` messages starting at a human message.
    """
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    kept: List[AnyMessage] = []
    valid_call_ids: set = set()
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            ids = {tc["id"] for tc in m.tool_calls}
            if not ids <= answered:
                continue
            valid_call_ids |= ids
        if isinstance(m, ToolMessage) and m.tool_call_id not in valid_call_ids:
            continue
        kept.append(m)
    tail = kept[-window:] if window > 0 else kept
    for i, m in enumerate(tail):
        if isinstance(m, HumanMessage):
            return tail[i:]
    # Window contained no human message (very long tool loop): fall back to the last human onward.
    for i in range(len(kept) - 1, -1, -1):
        if isinstance(kept[i], HumanMessage):
            return kept[i:]
    return tail


def system_message(state: AgentState) -> SystemMessage:
    dynamic = session_block(state.get("profile"), state.get("pending_action"), state.get("turn", 0))
    if llm.supports_prompt_caching():
        return SystemMessage(content=[
            {"type": "text", "text": STATIC_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic},
        ])
    return SystemMessage(content=STATIC_PROMPT + "\n\n" + dynamic)


_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = llm.get_chat_model(langchain_tools())
    return _model


def reset_model() -> None:
    global _model
    _model = None


# --------------------------------------------------------------------------- nodes
def safety_guard(state: AgentState) -> Dict[str, Any]:
    turn = int(state.get("turn") or 0) + 1
    update: Dict[str, Any] = {
        "turn": turn, "steps": 0, "turn_tool_calls": [], "turn_tokens": {"in": 0, "out": 0},
        "blocked": None, "error": False, "turn_started": time.time(),
    }
    verdict = screen(last_human_text(state.get("messages", [])))
    if not verdict.allowed:
        update["blocked"] = verdict.reason
        update["messages"] = [AIMessage(content=verdict.reply)]
    return update


def memory_loader(state: AgentState) -> Dict[str, Any]:
    user_id = state["user_id"]
    facts = extract_facts(last_human_text(state.get("messages", [])))
    try:
        profile = db.upsert_user_memory(user_id, **facts) if facts else db.get_user_memory(user_id)
    except Exception:
        log.exception("memory_loader failed for user %s", user_id)
        profile = None
    return {"profile": profile}


def sales_agent(state: AgentState) -> Dict[str, Any]:
    steps = int(state.get("steps") or 0)
    if steps >= settings.max_agent_steps:
        return {"messages": [AIMessage(content=STEP_LIMIT_REPLY)]}
    started = float(state.get("turn_started") or time.time())
    if steps > 0 and time.time() - started > settings.turn_budget_s:
        log.warning("turn budget exceeded after %d steps", steps)
        return {"messages": [AIMessage(content=TIME_LIMIT_REPLY)]}
    history = prepare_history(state.get("messages", []), settings.history_window)
    tokens = dict(state.get("turn_tokens") or {"in": 0, "out": 0})
    try:
        ai = get_model().invoke([system_message(state)] + history)
    except Exception as e:
        log.exception("LLM call failed: %s", e)
        return {"messages": [AIMessage(content=FALLBACK_REPLY)], "error": True, "steps": steps + 1}
    usage = getattr(ai, "usage_metadata", None) or {}
    tokens["in"] = tokens.get("in", 0) + int(usage.get("input_tokens", 0) or 0)
    tokens["out"] = tokens.get("out", 0) + int(usage.get("output_tokens", 0) or 0)
    return {"messages": [ai], "steps": steps + 1, "turn_tokens": tokens}


def tools_node(state: AgentState) -> Dict[str, Any]:
    ai = state["messages"][-1]
    ctx = ToolContext(
        user_id=state["user_id"],
        turn=int(state.get("turn") or 0),
        user_message=last_human_text(state["messages"]),
        pending_action=state.get("pending_action"),
    )
    calls = list(state.get("turn_tool_calls") or [])
    results: List[ToolMessage] = []
    pending_changed = False
    for tc in getattr(ai, "tool_calls", []) or []:
        outcome = run_tool(tc["name"], tc.get("args") or {}, ctx)
        if outcome.pending_action is CLEAR:
            ctx.pending_action, pending_changed = None, True
        elif outcome.pending_action is not None:
            ctx.pending_action, pending_changed = outcome.pending_action, True
        results.append(ToolMessage(
            content=outcome.content, tool_call_id=tc["id"], name=tc["name"],
            status="error" if outcome.is_error else "success",
        ))
        calls.append({
            "name": tc["name"], "args": compact_args(tc.get("args")),
            "ok": not outcome.is_error, "output": outcome.content[:400],
        })
    update: Dict[str, Any] = {"messages": results, "turn_tool_calls": calls}
    if pending_changed:
        update["pending_action"] = ctx.pending_action
    return update


def route_after_guard(state: AgentState) -> str:
    return END if state.get("blocked") else "memory_loader"


def route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls and not state.get("error"):
        return "tools"
    return END


def build_graph(checkpointer: Any = None):
    g = StateGraph(AgentState)
    g.add_node("safety_guard", safety_guard)
    g.add_node("memory_loader", memory_loader)
    g.add_node("sales_agent", sales_agent)
    g.add_node("tools", tools_node)
    g.add_edge(START, "safety_guard")
    g.add_conditional_edges("safety_guard", route_after_guard, {"memory_loader": "memory_loader", END: END})
    g.add_edge("memory_loader", "sales_agent")
    g.add_conditional_edges("sales_agent", route_after_agent, {"tools": "tools", END: END})
    g.add_edge("tools", "sales_agent")
    return g.compile(checkpointer=checkpointer)


# For `langgraph dev` / LangGraph Studio (the platform supplies its own checkpointer).
graph = build_graph()
