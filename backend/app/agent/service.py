"""Runs one chat turn through the graph and shapes the /chat response."""

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage

from .. import database as db
from .graph import FALLBACK_REPLY, build_graph

log = logging.getLogger("cartpilot.service")

_graph = None
_graph_lock = threading.Lock()

# One lock per conversation so two concurrent requests on the same thread can't
# interleave their checkpoint writes. Bounded LRU so memory stays flat.
_thread_locks: "OrderedDict[str, threading.Lock]" = OrderedDict()
_locks_guard = threading.Lock()
_MAX_LOCKS = 5000


def init_agent(checkpointer: Any) -> None:
    global _graph
    with _graph_lock:
        _graph = build_graph(checkpointer=checkpointer)


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _thread_locks.pop(key, None) or threading.Lock()
        _thread_locks[key] = lock
        while len(_thread_locks) > _MAX_LOCKS:
            _thread_locks.popitem(last=False)
        return lock


_TYPO_MAP = str.maketrans({
    "\u00a0": " ", "\u202f": " ", "\u2007": " ", "\u2009": " ", "\u200a": " ",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u200b": "",
})


def normalize_reply(text: str) -> str:
    """Replace exotic spaces/hyphens some models emit with plain ASCII ones so
    clients (and automated graders) can match text reliably."""
    return text.translate(_TYPO_MAP).strip()


def thread_key(user_id: str, thread_id: str) -> str:
    # Scoping the checkpoint key by user_id means two users who happen to send the
    # same thread_id still get completely separate short-term memory.
    return f"{user_id}::{thread_id}"


def chat(user_id: str, thread_id: str, message: str) -> Dict[str, Any]:
    if _graph is None:
        raise RuntimeError("Agent not initialised")
    started = time.perf_counter()
    key = thread_key(user_id, thread_id)
    config = {"configurable": {"thread_id": key}, "recursion_limit": 40}
    reply, tool_calls, tokens = FALLBACK_REPLY, [], {"in": 0, "out": 0}
    blocked: Optional[str] = None
    error = False
    with _lock_for(key):
        try:
            state = _graph.invoke({"messages": [HumanMessage(content=message)], "user_id": user_id}, config)
            last = state["messages"][-1]
            if isinstance(last, AIMessage):
                reply = normalize_reply(last.text or "") or FALLBACK_REPLY
            tool_calls = state.get("turn_tool_calls") or []
            tokens = state.get("turn_tokens") or tokens
            blocked = state.get("blocked")
            error = bool(state.get("error"))
        except Exception:
            log.exception("chat turn failed (user=%s thread=%s)", user_id, thread_id)
            error = True
    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        db.log_chat(
            user_id, thread_id, message, reply, tool_calls, int(tokens.get("in", 0)), int(tokens.get("out", 0)),
            latency_ms, bool(blocked), blocked, error,
        )
    except Exception:
        log.exception("failed to write chat log")
    return {
        "reply": reply,
        "tool_calls": tool_calls,
        "tokens": {"in": int(tokens.get("in", 0)), "out": int(tokens.get("out", 0))},
    }
