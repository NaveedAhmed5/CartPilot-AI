import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, type ToolCall } from "../api";
import { newThreadId, useSession } from "../session";
import { Markdown } from "./Markdown";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  tools?: ToolCall[];
  failed?: boolean;
}

const TOOL_LABELS: Record<string, string> = {
  search_products: "Searched the catalogue",
  get_product_details: "Checked product details",
  get_store_policy: "Looked up store policy",
  place_order: "Prepared your order",
  cancel_order: "Prepared a cancellation",
  forget_my_data: "Prepared data deletion",
  confirm_pending_action: "Confirmed your request",
  get_my_orders: "Checked your orders",
  save_user_preference: "Saved your preferences",
};

const SUGGESTIONS = [
  "Show me hoodies under Rs 7,000",
  "My size is M and I live in Lahore",
  "What's your return policy?",
  "Where is my order?",
];

interface Conversation {
  owner: string;
  threadId: string;
  messages: ChatMessage[];
}

const threadKey = (userId: string) => `cp_thread_${userId}`;
const messagesKey = (userId: string, threadId: string) => `cp_msgs_${userId}_${threadId}`;

function loadThread(userId: string): string {
  return localStorage.getItem(threadKey(userId)) || newThreadId();
}

function loadMessages(userId: string, threadId: string): ChatMessage[] {
  try {
    return JSON.parse(localStorage.getItem(messagesKey(userId, threadId)) || "[]");
  } catch {
    return [];
  }
}

export function ChatPanel() {
  const { userId, customer, chatRequest, chatOpen, setChatOpen, threadRequest } = useSession();
  const [conv, setConv] = useState<Conversation>(() => {
    const t = loadThread(userId);
    return { owner: userId, threadId: t, messages: loadMessages(userId, t) };
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastChatNonce = useRef<number | null>(null);
  const lastThreadNonce = useRef<number | null>(null);
  const { messages } = conv;

  // Switch conversation when the signed-in identity changes. The owner travels with
  // the messages, so one person's chat is never saved under another's key.
  useEffect(() => {
    if (conv.owner !== userId) {
      const t = loadThread(userId);
      setConv({ owner: userId, threadId: t, messages: loadMessages(userId, t) });
    }
  }, [userId, conv.owner]);

  useEffect(() => {
    localStorage.setItem(threadKey(conv.owner), conv.threadId);
    localStorage.setItem(messagesKey(conv.owner, conv.threadId), JSON.stringify(conv.messages.slice(-60)));
  }, [conv]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    if (chatOpen) setTimeout(() => inputRef.current?.focus(), 50);
  }, [chatOpen]);

  useEffect(() => {
    if (!chatOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setChatOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chatOpen, setChatOpen]);

  const append = useCallback((owner: string, tid: string, msg: ChatMessage) => {
    setConv((c) => (c.owner === owner && c.threadId === tid ? { ...c, messages: [...c.messages, msg] } : c));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || conv.owner !== userId) return;
      const owner = conv.owner;
      const tid = conv.threadId;
      append(owner, tid, { role: "user", text: message });
      setInput("");
      setBusy(true);
      try {
        const res = await api.chat(owner, tid, message);
        append(owner, tid, { role: "assistant", text: res.reply, tools: res.tool_calls });
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "Something went wrong.";
        append(owner, tid, {
          role: "assistant",
          text: `${msg} Your message wasn't answered; send it again to retry.`,
          failed: true,
        });
      } finally {
        setBusy(false);
      }
    },
    [conv.owner, conv.threadId, userId, append],
  );

  useEffect(() => {
    if (chatRequest && chatRequest.nonce !== lastChatNonce.current && conv.owner === userId) {
      lastChatNonce.current = chatRequest.nonce;
      void send(chatRequest.text);
    }
  }, [chatRequest, send, conv.owner, userId]);

  useEffect(() => {
    if (!threadRequest || threadRequest.nonce === lastThreadNonce.current || !customer) return;
    lastThreadNonce.current = threadRequest.nonce;
    const id = threadRequest.threadId;
    const owner = customer.username;
    api
      .myThread(customer.token, id)
      .then((rows) => {
        setConv({
          owner,
          threadId: id,
          messages: rows.flatMap((r) => [
            { role: "user" as const, text: r.message },
            { role: "assistant" as const, text: r.reply, tools: r.tool_calls },
          ]),
        });
      })
      .catch(() => undefined);
  }, [threadRequest, customer]);

  const newChat = () => {
    setConv({ owner: userId, threadId: newThreadId(), messages: [] });
    inputRef.current?.focus();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!busy) void send(input);
  };

  return (
    <>
      {!chatOpen && (
        <button className="chat-launcher" onClick={() => setChatOpen(true)} aria-label="Open chat with CartPilot">
          <span className="chat-launcher-dot" aria-hidden="true" />
          Chat with CartPilot
        </button>
      )}
      <aside className={`chat-panel ${chatOpen ? "open" : ""}`} aria-label="CartPilot chat" aria-hidden={!chatOpen}>
        <header className="chat-head">
          <div>
            <p className="chat-title">CartPilot</p>
            <p className="chat-sub">
              {customer ? `Signed in as ${customer.displayName || customer.username}` : "Shopping as a guest"}
            </p>
          </div>
          <div className="chat-head-actions">
            <button className="btn-ghost small" onClick={newChat} disabled={busy}>
              New chat
            </button>
            <button className="icon-btn" onClick={() => setChatOpen(false)} aria-label="Close chat">
              ✕
            </button>
          </div>
        </header>

        <div className="chat-log" ref={listRef} aria-live="polite">
          {messages.length === 0 && (
            <div className="chat-empty">
              <p>
                Ask about products, sizes or delivery, or place an order. I remember your size and city between
                chats{customer ? "" : " in this browser"}.
              </p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => void send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role} ${m.failed ? "failed" : ""}`}>
              {m.role === "assistant" ? <Markdown text={m.text} /> : <p>{m.text}</p>}
              {m.tools && m.tools.length > 0 && (
                <ul className="tool-trail" aria-label="What CartPilot did">
                  {m.tools.map((t, j) => (
                    <li key={j} className={t.ok === false ? "bad" : ""}>
                      {TOOL_LABELS[t.name] || t.name}
                      {t.ok === false ? " (didn't go through)" : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {busy && (
            <div className="bubble assistant typing" aria-label="CartPilot is replying">
              <span />
              <span />
              <span />
            </div>
          )}
        </div>

        <form className="chat-input" onSubmit={onSubmit}>
          <textarea
            ref={inputRef}
            value={input}
            rows={1}
            maxLength={2000}
            placeholder="Ask CartPilot…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) onSubmit(e);
            }}
            aria-label="Message"
          />
          <button className="btn-primary" type="submit" disabled={busy || !input.trim()}>
            Send
          </button>
        </form>
      </aside>
    </>
  );
}
