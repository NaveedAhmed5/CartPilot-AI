import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  ApiError,
  pkr,
  shortDate,
  shortDateTime,
  type AdminStats,
  type ConversationLog,
  type Customer,
  type Order,
  type Product,
} from "../api";
import { Markdown } from "../components/Markdown";

const TOKEN_KEY = "cp_admin_token";
const STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"];
type Tab = "overview" | "orders" | "products" | "conversations" | "customers";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "orders", label: "Orders" },
  { id: "products", label: "Products" },
  { id: "conversations", label: "Conversations" },
  { id: "customers", label: "Customers" },
];

export function Admin() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY));
  const [tab, setTab] = useState<Tab>("overview");

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }, []);

  if (!token) {
    return (
      <AdminLogin
        onLogin={(t) => {
          sessionStorage.setItem(TOKEN_KEY, t);
          setToken(t);
        }}
      />
    );
  }

  return (
    <div className="admin">
      <aside className="admin-side">
        <p className="wordmark small">CartPilot</p>
        <p className="admin-side-label">Store admin</p>
        <nav aria-label="Admin sections">
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "active" : ""} aria-current={tab === t.id} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="admin-side-foot">
          <a href="/">View store</a>
          <button className="btn-ghost small on-dark" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="admin-main">
        {tab === "overview" && <Overview token={token} onAuthError={logout} />}
        {tab === "orders" && <Orders token={token} onAuthError={logout} />}
        {tab === "products" && <Products token={token} onAuthError={logout} />}
        {tab === "conversations" && <Conversations token={token} onAuthError={logout} />}
        {tab === "customers" && <Customers token={token} onAuthError={logout} />}
      </main>
    </div>
  );
}

interface SectionProps {
  token: string;
  onAuthError: () => void;
}

/** Load data for an admin section, handling expired sessions and errors. */
function useAdminData<T>(fetcher: () => Promise<T>, onAuthError: () => void, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    setError("");
    fetcher()
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) onAuthError();
        else setError(e instanceof ApiError ? e.message : "Couldn't load data.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, setData, error, reload };
}

function SectionHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="section-head">
      <h1>{title}</h1>
      <div className="section-tools">{children}</div>
    </div>
  );
}

function AdminLogin({ onLogin }: { onLogin: (token: string) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin((await api.adminLogin(password)).token);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign in.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="admin-login">
      <form onSubmit={submit} className="panel">
        <p className="wordmark">CartPilot</p>
        <h1>Store admin</h1>
        <label>
          Admin password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn-primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <a href="/" className="muted small-text">
          Back to the store
        </a>
      </form>
    </main>
  );
}

// ------------------------------------------------------------------- overview
function Bars({ rows, value, label, format }: {
  rows: Record<string, any>[];
  value: string;
  label: string;
  format: (n: number) => string;
}) {
  const max = Math.max(1, ...rows.map((r) => Number(r[value]) || 0));
  return (
    <ul className="bars">
      {rows.map((r, i) => (
        <li key={i}>
          <span className="bar-label">{r[label]}</span>
          <span className="bar-track" aria-hidden="true">
            <span className="bar-fill" style={{ width: `${(Number(r[value]) / max) * 100}%` }} />
          </span>
          <span className="bar-value">{format(Number(r[value]))}</span>
        </li>
      ))}
    </ul>
  );
}

function Overview({ token, onAuthError }: SectionProps) {
  const { data: s, error, reload } = useAdminData<AdminStats>(() => api.adminStats(token), onAuthError, [token]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!s) return <p className="muted">Loading…</p>;
  const c = s.chats;
  const kpis: [string, string, string][] = [
    ["Revenue", pkr(s.orders.revenue), `${s.orders.orders} orders, excluding cancelled`],
    ["Waiting to ship", String(s.orders.pending_orders), "orders in pending status"],
    ["Average order", pkr(s.orders.avg_order_value), `${s.orders.cancelled_orders} cancelled so far`],
    ["Conversations", String(c.conversations), `${c.messages} messages from ${c.chat_users} shoppers`],
    ["Agent cost", `$${c.est_cost_usd.toFixed(4)}`, `${c.tokens_in.toLocaleString()} in / ${c.tokens_out.toLocaleString()} out tokens`],
    ["Reply time", `${(c.avg_latency_ms / 1000).toFixed(1)} s`, "average, excluding blocked messages"],
    ["Blocked by safety", String(c.blocked), "off-topic, injection or privacy attempts"],
    ["Agent errors", String(c.errors), "replies that fell back to an apology"],
  ];
  return (
    <>
      <SectionHead title="Overview">
        <span className="muted small-text">Model: {s.model}</span>
        <button className="btn-ghost small" onClick={reload}>
          Refresh
        </button>
      </SectionHead>
      <div className="kpis">
        {kpis.map(([label, value, hint]) => (
          <div key={label} className="kpi">
            <p className="kpi-label">{label}</p>
            <p className="kpi-value">{value}</p>
            <p className="kpi-hint">{hint}</p>
          </div>
        ))}
      </div>
      <div className="overview-grid">
        <section className="panel">
          <h2>Best sellers by revenue</h2>
          {s.top_products.length ? (
            <Bars rows={s.top_products} value="revenue" label="name" format={pkr} />
          ) : (
            <p className="muted">No sales yet.</p>
          )}
        </section>
        <section className="panel">
          <h2>Revenue, last 14 days</h2>
          {s.daily.length ? (
            <Bars rows={s.daily.map((d) => ({ ...d, day: shortDate(d.day) }))} value="revenue" label="day" format={pkr} />
          ) : (
            <p className="muted">No orders in the last 14 days.</p>
          )}
        </section>
        <section className="panel">
          <h2>Tools the agent used</h2>
          {s.tool_usage.length ? (
            <Bars rows={s.tool_usage} value="calls" label="tool" format={(n) => String(n)} />
          ) : (
            <p className="muted">No tool calls yet.</p>
          )}
        </section>
        <section className="panel">
          <h2>Running low</h2>
          {s.low_stock.length ? (
            <ul className="plain-list">
              {s.low_stock.map((p) => (
                <li key={p.id}>
                  <span>{p.name}</span>
                  <span className={`stock ${p.stock === 0 ? "out" : "low"}`}>{p.stock === 0 ? "Sold out" : `${p.stock} left`}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Every product has more than 10 in stock.</p>
          )}
        </section>
      </div>
    </>
  );
}

// --------------------------------------------------------------------- orders
function Orders({ token, onAuthError }: SectionProps) {
  const [status, setStatus] = useState("");
  const { data, setData, error, reload } = useAdminData<Order[]>(() => api.adminOrders(token, status), onAuthError, [token, status]);
  const [rowError, setRowError] = useState("");

  const change = async (o: Order, next: string) => {
    setRowError("");
    try {
      const updated = await api.adminSetOrderStatus(token, o.id, next);
      setData((rows) => (rows || []).map((r) => (r.id === o.id ? updated : r)));
    } catch (e) {
      setRowError(e instanceof ApiError ? `Order #${o.id}: ${e.message}` : "Couldn't update the order.");
    }
  };

  return (
    <>
      <SectionHead title="Orders">
        <label className="inline-label">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button className="btn-ghost small" onClick={reload}>
          Refresh
        </button>
      </SectionHead>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {rowError && <p className="form-error">{rowError}</p>}
      {!data ? (
        <p className="muted">Loading…</p>
      ) : data.length === 0 ? (
        <p className="muted">No orders{status ? ` with status ${status}` : ""}.</p>
      ) : (
        <div className="table-scroll panel flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Customer</th>
                <th>Items</th>
                <th>Deliver to</th>
                <th className="num">Total</th>
                <th>Placed</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.map((o) => (
                <tr key={o.id}>
                  <td>#{o.id}</td>
                  <td>
                    <div>{o.customer_name || "—"}</div>
                    <div className="muted small-text">
                      {o.user_id}
                      {o.phone ? `, ${o.phone}` : ""}
                    </div>
                  </td>
                  <td>
                    {(o.items || []).map((i, j) => (
                      <div key={j}>
                        {i.name} ({i.size}) × {i.quantity}
                      </div>
                    ))}
                    {o.discount_code && <div className="muted small-text">Code {o.discount_code}</div>}
                  </td>
                  <td>
                    <div>{o.city}</div>
                    <div className="muted small-text">{o.shipping_address}</div>
                  </td>
                  <td className="num">{pkr(o.total_price)}</td>
                  <td>{shortDate(o.created_at)}</td>
                  <td>
                    <select
                      className={`status-select ${o.status}`}
                      value={o.status}
                      disabled={o.status === "cancelled"}
                      onChange={(e) => void change(o, e.target.value)}
                      aria-label={`Status of order ${o.id}`}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------- products
const EMPTY_PRODUCT = { name: "", description: "", price: "", category: "Hoodies", sizes: "S, M, L, XL", stock: "10" };

function Products({ token, onAuthError }: SectionProps) {
  const { data, setData, error, reload } = useAdminData<Product[]>(() => api.adminProducts(token), onAuthError, [token]);
  const [form, setForm] = useState(EMPTY_PRODUCT);
  const [formError, setFormError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [rowError, setRowError] = useState("");

  const update = async (p: Product, patch: Partial<Product>) => {
    setRowError("");
    try {
      const updated = await api.adminUpdateProduct(token, p.id, patch);
      setData((rows) => (rows || []).map((r) => (r.id === p.id ? updated : r)));
    } catch (e) {
      setRowError(e instanceof ApiError ? `${p.name}: ${e.message}` : "Couldn't save the change.");
    }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setFormError("");
    const sizes = form.sizes.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const p = await api.adminCreateProduct(token, {
        name: form.name.trim(),
        description: form.description.trim(),
        price: Number(form.price),
        category: form.category,
        sizes,
        stock: Number(form.stock),
        is_active: true,
      });
      setData((rows) => [...(rows || []), p]);
      setForm(EMPTY_PRODUCT);
      setShowForm(false);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't add the product.");
    }
  };

  return (
    <>
      <SectionHead title="Products">
        <button className="btn-primary small" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Close form" : "Add product"}
        </button>
      </SectionHead>
      {showForm && (
        <form className="panel product-form" onSubmit={create}>
          <label>
            Name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required minLength={2} />
          </label>
          <label>
            Category
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {["Hoodies", "T-Shirts", "Bottoms", "Outerwear", "Footwear", "Accessories"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            Price (Rs)
            <input type="number" min={1} value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} required />
          </label>
          <label>
            Stock
            <input type="number" min={0} value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} required />
          </label>
          <label className="wide">
            Sizes, separated by commas
            <input value={form.sizes} onChange={(e) => setForm({ ...form, sizes: e.target.value })} required />
          </label>
          <label className="wide">
            Description
            <textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          {formError && <p className="form-error wide">{formError}</p>}
          <div className="wide">
            <button className="btn-primary">Add product</button>
          </div>
        </form>
      )}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {rowError && <p className="form-error">{rowError}</p>}
      {!data ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="table-scroll panel flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Category</th>
                <th>Sizes</th>
                <th className="num">Price (Rs)</th>
                <th className="num">Stock</th>
                <th>Listed</th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.id} className={p.is_active === false ? "dim" : ""}>
                  <td>
                    <div>{p.name}</div>
                    <div className="muted small-text">#{p.id}</div>
                  </td>
                  <td>{p.category}</td>
                  <td>{p.sizes.join(", ")}</td>
                  <td className="num">
                    <NumberCell value={p.price} min={1} onSave={(v) => update(p, { price: v })} label={`Price of ${p.name}`} />
                  </td>
                  <td className="num">
                    <NumberCell value={p.stock} min={0} onSave={(v) => update(p, { stock: v })} label={`Stock of ${p.name}`} />
                  </td>
                  <td>
                    <label className="toggle">
                      <input type="checkbox" checked={p.is_active !== false} onChange={(e) => update(p, { is_active: e.target.checked })} />
                      {p.is_active !== false ? "In store" : "Hidden"}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function NumberCell({ value, min, onSave, label }: { value: number; min: number; onSave: (v: number) => void; label: string }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n) && n >= min && n !== value) onSave(n);
    else setDraft(String(value));
  };
  return (
    <input
      className="cell-input"
      type="number"
      min={min}
      value={draft}
      aria-label={label}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

// -------------------------------------------------------------- conversations
function Conversations({ token, onAuthError }: SectionProps) {
  const [userFilter, setUserFilter] = useState("");
  const [applied, setApplied] = useState("");
  const [blockedOnly, setBlockedOnly] = useState(false);
  const { data, error, reload } = useAdminData<ConversationLog[]>(
    () => api.adminConversations(token, { user_id: applied || undefined, blocked_only: blockedOnly }),
    onAuthError,
    [token, applied, blockedOnly],
  );
  return (
    <>
      <SectionHead title="Conversations">
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(userFilter.trim());
          }}
        >
          <input placeholder="Filter by user id" value={userFilter} onChange={(e) => setUserFilter(e.target.value)} aria-label="Filter by user id" />
          <button className="btn-ghost small">Filter</button>
        </form>
        <label className="toggle">
          <input type="checkbox" checked={blockedOnly} onChange={(e) => setBlockedOnly(e.target.checked)} />
          Blocked only
        </label>
        <button className="btn-ghost small" onClick={reload}>
          Refresh
        </button>
      </SectionHead>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!data ? (
        <p className="muted">Loading…</p>
      ) : data.length === 0 ? (
        <p className="muted">No conversations match.</p>
      ) : (
        <ul className="convo-list">
          {data.map((c) => (
            <li key={c.id} className="panel">
              <div className="convo-meta">
                <span>
                  <strong>{c.user_id}</strong> <span className="muted">in {c.thread_id}</span>
                </span>
                <span className="muted small-text">
                  {shortDateTime(c.created_at)}, {(c.latency_ms / 1000).toFixed(1)} s, {c.tokens_in} in / {c.tokens_out} out tokens
                </span>
                {c.blocked && <span className="badge red">Blocked: {c.block_reason?.replace(/_/g, " ")}</span>}
                {c.error && <span className="badge amber">Agent error</span>}
              </div>
              <p className="convo-msg">
                <span className="who">Shopper</span>
                {c.message}
              </p>
              <div className="convo-reply">
                <span className="who">CartPilot</span>
                <div className="convo-md">
                  <Markdown text={c.reply} />
                </div>
              </div>
              {c.tool_calls.length > 0 && (
                <ul className="tool-chips">
                  {c.tool_calls.map((t, i) => (
                    <li key={i} className={t.ok === false ? "bad" : ""} title={JSON.stringify(t.args)}>
                      {t.name}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ------------------------------------------------------------------ customers
function Customers({ token, onAuthError }: SectionProps) {
  const { data, error, reload } = useAdminData<Customer[]>(() => api.adminCustomers(token), onAuthError, [token]);
  return (
    <>
      <SectionHead title="Customers">
        <span className="muted small-text">Long-term memory is stored per user id and never shared between customers.</span>
        <button className="btn-ghost small" onClick={reload}>
          Refresh
        </button>
      </SectionHead>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!data ? (
        <p className="muted">Loading…</p>
      ) : data.length === 0 ? (
        <p className="muted">No customers yet.</p>
      ) : (
        <div className="table-scroll panel flush">
          <table className="data-table">
            <thead>
              <tr>
                <th>User id</th>
                <th>Remembered</th>
                <th className="num">Orders</th>
                <th className="num">Spent</th>
                <th className="num">Chats</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {data.map((u) => (
                <tr key={u.user_id}>
                  <td>
                    <div>{u.user_id}</div>
                    <div className="muted small-text">{u.has_account ? u.display_name || "Account" : "API or guest"}</div>
                  </td>
                  <td>
                    {[u.name, u.preferred_size && `size ${u.preferred_size}`, u.city, u.budget].filter(Boolean).join(", ") || (
                      <span className="muted">Nothing yet</span>
                    )}
                    {u.style_notes && <div className="muted small-text">{u.style_notes}</div>}
                  </td>
                  <td className="num">{u.orders}</td>
                  <td className="num">{pkr(u.spent)}</td>
                  <td className="num">{u.threads}</td>
                  <td>{shortDateTime(u.last_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="notice error">
      <p>{message}</p>
      <button className="btn-ghost small" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
