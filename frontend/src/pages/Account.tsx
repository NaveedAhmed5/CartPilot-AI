import { useCallback, useEffect, useState } from "react";
import { api, ApiError, pkr, shortDate, shortDateTime, type Memory, type Order, type ThreadSummary } from "../api";
import { AuthDialog } from "../components/AuthDialog";
import { useSession } from "../session";

const MEMORY_LABELS: [keyof Memory, string][] = [
  ["name", "Name"],
  ["preferred_size", "Usual size"],
  ["city", "City"],
  ["budget", "Budget"],
  ["style_notes", "Style notes"],
];

export function Account() {
  const { customer, signOut, openThread, askAgent } = useSession();
  const [authOpen, setAuthOpen] = useState(false);
  const [memory, setMemory] = useState<Memory | null>(null);
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [error, setError] = useState("");
  const [confirmForget, setConfirmForget] = useState(false);

  const load = useCallback(async () => {
    if (!customer) return;
    setError("");
    try {
      const [me, o, t] = await Promise.all([
        api.me(customer.token),
        api.myOrders(customer.token),
        api.myThreads(customer.token),
      ]);
      setMemory(me.memory);
      setOrders(o);
      setThreads(t);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) signOut();
      setError(e instanceof ApiError ? e.message : "Couldn't load your account.");
    }
  }, [customer, signOut]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!customer) {
    return (
      <main id="content" className="wrap page">
        <h1 className="page-title">My account</h1>
        <div className="notice">
          <p>Sign in to see your orders, the preferences CartPilot remembers and your past chats.</p>
          <button className="btn-primary" onClick={() => setAuthOpen(true)}>
            Sign in
          </button>
        </div>
        <AuthDialog open={authOpen} onClose={() => setAuthOpen(false)} />
      </main>
    );
  }

  const forget = async () => {
    await api.forgetMe(customer.token);
    setConfirmForget(false);
    setMemory(null);
  };

  const filled = MEMORY_LABELS.filter(([k]) => memory && memory[k]);

  return (
    <main id="content" className="wrap page">
      <h1 className="page-title">My account</h1>
      {error && <p className="form-error">{error}</p>}

      <div className="account-grid">
        <section className="panel">
          <h2>What CartPilot remembers</h2>
          <p className="muted small-text">
            Saved from your chats and used in every new conversation. Only you can see this.
          </p>
          {filled.length === 0 ? (
            <p className="muted">
              Nothing saved yet. Tell CartPilot something like “my size is M and I live in Lahore”.
            </p>
          ) : (
            <dl className="memory-list">
              {filled.map(([k, label]) => (
                <div key={k}>
                  <dt>{label}</dt>
                  <dd>{String(memory![k])}</dd>
                </div>
              ))}
            </dl>
          )}
          {filled.length > 0 &&
            (confirmForget ? (
              <div className="confirm-row">
                <p>Delete your saved preferences? Your orders stay.</p>
                <button className="btn-danger small" onClick={forget}>
                  Delete preferences
                </button>
                <button className="btn-ghost small" onClick={() => setConfirmForget(false)}>
                  Keep them
                </button>
              </div>
            ) : (
              <button className="btn-ghost small" onClick={() => setConfirmForget(true)}>
                Delete saved preferences
              </button>
            ))}
        </section>

        <section className="panel">
          <h2>Past conversations</h2>
          {!threads ? (
            <p className="muted">Loading…</p>
          ) : threads.length === 0 ? (
            <p className="muted">No chats yet.</p>
          ) : (
            <ul className="thread-list">
              {threads.map((t) => (
                <li key={t.thread_id}>
                  <button onClick={() => openThread(t.thread_id)}>
                    <span className="thread-first">{t.first_message}</span>
                    <span className="muted small-text">
                      {t.turns} {t.turns === 1 ? "message" : "messages"}, last on {shortDateTime(t.last_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="panel">
        <h2>Your orders</h2>
        {!orders ? (
          <p className="muted">Loading…</p>
        ) : orders.length === 0 ? (
          <div className="empty-row">
            <p className="muted">You haven't ordered yet.</p>
            <button className="btn-outline small" onClick={() => askAgent("Help me pick something to order")}>
              Shop with CartPilot
            </button>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Placed</th>
                  <th>Items</th>
                  <th>Deliver to</th>
                  <th className="num">Total</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td>#{o.id}</td>
                    <td>{shortDate(o.created_at)}</td>
                    <td>
                      {(o.items || []).map((i, j) => (
                        <div key={j}>
                          {i.name} ({i.size}) × {i.quantity}
                        </div>
                      ))}
                    </td>
                    <td>{o.city}</td>
                    <td className="num">{pkr(o.total_price)}</td>
                    <td>
                      <span className={`status ${o.status}`}>{o.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
