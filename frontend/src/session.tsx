import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export interface CustomerSession {
  token: string;
  username: string;
  displayName: string;
}

interface SessionValue {
  customer: CustomerSession | null;
  /** user_id sent to the agent: the account username, or a per-browser guest id. */
  userId: string;
  signIn: (s: CustomerSession) => void;
  signOut: () => void;
  chatRequest: { text: string; nonce: number } | null;
  askAgent: (text: string) => void;
  chatOpen: boolean;
  setChatOpen: (open: boolean) => void;
  threadRequest: { threadId: string; nonce: number } | null;
  openThread: (threadId: string) => void;
}

const CUSTOMER_KEY = "cp_customer";
const GUEST_KEY = "cp_guest_id";

function randomId(prefix: string) {
  const part = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
  return `${prefix}-${part}`;
}

export function newThreadId() {
  return randomId("thread");
}

function loadCustomer(): CustomerSession | null {
  try {
    const raw = localStorage.getItem(CUSTOMER_KEY);
    return raw ? (JSON.parse(raw) as CustomerSession) : null;
  } catch {
    return null;
  }
}

function guestId() {
  let id = localStorage.getItem(GUEST_KEY);
  if (!id) {
    id = randomId("guest");
    localStorage.setItem(GUEST_KEY, id);
  }
  return id;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [customer, setCustomer] = useState<CustomerSession | null>(loadCustomer);
  const [chatRequest, setChatRequest] = useState<{ text: string; nonce: number } | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [threadRequest, setThreadRequest] = useState<{ threadId: string; nonce: number } | null>(null);

  const signIn = useCallback((s: CustomerSession) => {
    localStorage.setItem(CUSTOMER_KEY, JSON.stringify(s));
    setCustomer(s);
  }, []);
  const signOut = useCallback(() => {
    localStorage.removeItem(CUSTOMER_KEY);
    setCustomer(null);
  }, []);
  const askAgent = useCallback((text: string) => {
    setChatOpen(true);
    setChatRequest({ text, nonce: Date.now() });
  }, []);

  const openThread = useCallback((threadId: string) => {
    setChatOpen(true);
    setThreadRequest({ threadId, nonce: Date.now() });
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      customer,
      userId: customer ? customer.username : guestId(),
      signIn,
      signOut,
      chatRequest,
      askAgent,
      chatOpen,
      setChatOpen,
      threadRequest,
      openThread,
    }),
    [customer, signIn, signOut, chatRequest, askAgent, chatOpen, threadRequest, openThread],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
