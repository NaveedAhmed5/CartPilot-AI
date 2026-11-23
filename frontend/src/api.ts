export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export interface Product {
  id: number;
  name: string;
  description: string;
  price: number;
  category: string;
  sizes: string[];
  stock: number;
  is_active?: boolean;
}

export interface OrderItem {
  product_id: number;
  name: string;
  size: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface Order {
  id: number;
  user_id: string;
  items: OrderItem[];
  subtotal: number | null;
  shipping_fee: number | null;
  discount: number | null;
  discount_code: string | null;
  total_price: number;
  status: string;
  customer_name: string | null;
  phone: string | null;
  shipping_address: string | null;
  city: string | null;
  created_at: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  ok?: boolean;
  output?: string;
}

export interface ChatReply {
  reply: string;
  tool_calls: ToolCall[];
  tokens: { in: number; out: number };
}

export interface Memory {
  name?: string | null;
  preferred_size?: string | null;
  city?: string | null;
  budget?: string | null;
  style_notes?: string | null;
  updated_at?: string;
}

export interface ThreadSummary {
  thread_id: string;
  started_at: string;
  last_at: string;
  turns: number;
  first_message: string;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers: { ...headers, ...(init.headers || {}) } });
  } catch {
    throw new ApiError(0, "Can't reach the CartPilot server. Check your connection and try again.");
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const detail =
      (data && typeof data === "object" && "detail" in data && typeof data.detail === "string" && data.detail) ||
      (data && typeof data === "object" && "error" in data && String(data.error)) ||
      `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const api = {
  chat: (user_id: string, thread_id: string, message: string) =>
    request<ChatReply>("/chat", { method: "POST", body: JSON.stringify({ user_id, thread_id, message }) }),
  products: () => request<Product[]>("/api/products"),
  register: (username: string, password: string, display_name: string) =>
    request<{ token: string; user: { username: string; display_name: string } }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username, password, display_name: display_name || undefined }),
    }),
  login: (username: string, password: string) =>
    request<{ token: string; user: { username: string; display_name: string } }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  me: (token: string) =>
    request<{ username: string; display_name: string; memory: Memory | null }>("/api/me", {}, token),
  myOrders: (token: string) => request<Order[]>("/api/me/orders", {}, token),
  forgetMe: (token: string) => request<{ deleted: boolean }>("/api/me/memory", { method: "DELETE" }, token),
  myThreads: (token: string) => request<ThreadSummary[]>("/api/me/threads", {}, token),
  myThread: (token: string, threadId: string) =>
    request<{ message: string; reply: string; tool_calls: ToolCall[]; created_at: string }[]>(
      `/api/me/threads/${encodeURIComponent(threadId)}`,
      {},
      token,
    ),

  adminLogin: (password: string) =>
    request<{ token: string }>("/api/admin/login", { method: "POST", body: JSON.stringify({ password }) }),
  adminStats: (t: string) => request<AdminStats>("/api/admin/stats", {}, t),
  adminOrders: (t: string, status?: string) =>
    request<Order[]>(`/api/admin/orders${status ? `?status=${encodeURIComponent(status)}` : ""}`, {}, t),
  adminSetOrderStatus: (t: string, id: number, status: string) =>
    request<Order>(`/api/admin/orders/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }, t),
  adminProducts: (t: string) => request<Product[]>("/api/admin/products", {}, t),
  adminCreateProduct: (t: string, p: Omit<Product, "id">) =>
    request<Product>("/api/admin/products", { method: "POST", body: JSON.stringify(p) }, t),
  adminUpdateProduct: (t: string, id: number, p: Partial<Product>) =>
    request<Product>(`/api/admin/products/${id}`, { method: "PUT", body: JSON.stringify(p) }, t),
  adminArchiveProduct: (t: string, id: number) =>
    request<{ archived: boolean }>(`/api/admin/products/${id}`, { method: "DELETE" }, t),
  adminConversations: (t: string, opts: { user_id?: string; blocked_only?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (opts.user_id) q.set("user_id", opts.user_id);
    if (opts.blocked_only) q.set("blocked_only", "true");
    q.set("limit", "150");
    return request<ConversationLog[]>(`/api/admin/conversations?${q}`, {}, t);
  },
  adminCustomers: (t: string) => request<Customer[]>("/api/admin/customers", {}, t),
};

export interface AdminStats {
  orders: { orders: number; pending_orders: number; cancelled_orders: number; revenue: number; avg_order_value: number };
  chats: {
    messages: number;
    chat_users: number;
    conversations: number;
    tokens_in: number;
    tokens_out: number;
    avg_latency_ms: number;
    blocked: number;
    errors: number;
    est_cost_usd: number;
  };
  top_products: { name: string; units: number; revenue: number }[];
  daily: { day: string; orders: number; revenue: number }[];
  tool_usage: { tool: string; calls: number }[];
  low_stock: { id: number; name: string; stock: number }[];
  accounts: number;
  llm_provider: string;
  model: string;
}

export interface ConversationLog {
  id: number;
  user_id: string;
  thread_id: string;
  message: string;
  reply: string;
  tool_calls: ToolCall[];
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  blocked: boolean;
  block_reason: string | null;
  error: boolean;
  created_at: string;
}

export interface Customer {
  user_id: string;
  display_name: string | null;
  has_account: boolean;
  name: string | null;
  preferred_size: string | null;
  city: string | null;
  budget: string | null;
  style_notes: string | null;
  orders: number;
  spent: number;
  threads: number;
  last_seen: string | null;
}

export const pkr = (n: number | null | undefined) =>
  `Rs ${Math.round(Number(n || 0)).toLocaleString("en-PK")}`;

export const shortDate = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

export const shortDateTime = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};
