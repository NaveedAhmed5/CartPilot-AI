import { useEffect, useMemo, useState } from "react";
import { api, ApiError, pkr, type Product } from "../api";
import { ProductArt } from "../components/ProductArt";
import { useSession } from "../session";

const CATEGORIES = ["All", "Hoodies", "T-Shirts", "Bottoms", "Outerwear", "Footwear", "Accessories"];

function stockNote(p: Product) {
  if (p.stock <= 0) return { text: "Sold out", tone: "out" };
  if (p.stock <= 10) return { text: `Only ${p.stock} left`, tone: "low" };
  return { text: "In stock", tone: "ok" };
}

export function Store() {
  const { askAgent } = useSession();
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState("");
  const [category, setCategory] = useState("All");
  const [query, setQuery] = useState("");

  const load = () => {
    setError("");
    api
      .products()
      .then(setProducts)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load products."));
  };
  useEffect(load, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (products || []).filter(
      (p) =>
        (category === "All" || p.category === category) &&
        (!q || `${p.name} ${p.description} ${p.category}`.toLowerCase().includes(q)),
    );
  }, [products, category, query]);

  return (
    <main id="content">
      <section className="hero">
        <div className="wrap hero-grid">
          <div className="painted-frame">
            <h1>Street fits from Karachi to Khunjerab</h1>
            <p className="hero-copy">
              Hoodies, cargos and truck-art jackets made for Pakistani streets. Tell CartPilot your size and city.
              It finds the fit, checks stock and places your order, paid cash on delivery.
            </p>
            <div className="hero-actions">
              <button className="btn-primary large" onClick={() => askAgent("Hi! What would you recommend for me?")}>
                Chat with CartPilot
              </button>
              <a className="btn-ghost large on-dark" href="#catalogue">
                Browse the catalogue
              </a>
            </div>
          </div>
          <figure className="hero-demo" aria-label="Example conversation with CartPilot">
            <p className="demo-line user">Need a warm hoodie under 7k, I wear L</p>
            <p className="demo-line bot">
              Two in stock in L: the <strong>Karachi Underground Oversized Hoodie</strong> at Rs 6,500 and the{" "}
              <strong>Multan Sunset Tie-Dye Hoodie</strong> at Rs 6,900. Want me to order one to Lahore?
            </p>
            <p className="demo-line user">The black one. Yes, same address</p>
            <p className="demo-line bot">
              Here's your summary: 1 × Oversized Hoodie (L), free delivery, total Rs 6,500. Reply yes to confirm.
            </p>
          </figure>
        </div>
      </section>

      <section className="promises wrap" aria-label="Store promises">
        <p>
          <strong>Cash on delivery</strong> everywhere in Pakistan
        </p>
        <p>
          <strong>Free shipping</strong> on orders over Rs 5,000
        </p>
        <p>
          <strong>7-day returns</strong> and free size exchanges
        </p>
        <p>
          <strong>WELCOME10</strong> takes 10% off your first order
        </p>
      </section>

      <section id="catalogue" className="wrap catalogue">
        <div className="catalogue-head">
          <h2>The catalogue</h2>
          <input
            type="search"
            className="search"
            placeholder="Search hoodies, cargos, caps…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search products"
          />
        </div>
        <div className="chips" role="group" aria-label="Filter by category">
          {CATEGORIES.map((c) => (
            <button key={c} className={`chip ${category === c ? "active" : ""}`} aria-pressed={category === c} onClick={() => setCategory(c)}>
              {c}
            </button>
          ))}
        </div>

        {error && (
          <div className="notice error">
            <p>{error}</p>
            <button className="btn-ghost small" onClick={load}>
              Try again
            </button>
          </div>
        )}
        {!products && !error && <p className="muted">Loading the catalogue…</p>}
        {products && visible.length === 0 && (
          <div className="notice">
            <p>Nothing matches that search. Try another category, or ask CartPilot to find something similar.</p>
          </div>
        )}

        <ul className="product-grid">
          {visible.map((p) => {
            const note = stockNote(p);
            return (
              <li key={p.id} className="product">
                <ProductArt product={p} className="product-art" />
                <div className="product-body">
                  <p className="product-cat">{p.category}</p>
                  <h3>{p.name}</h3>
                  <p className="product-desc">{p.description}</p>
                  <div className="product-meta">
                    <span className="price">{pkr(p.price)}</span>
                    <span className={`stock ${note.tone}`}>{note.text}</span>
                  </div>
                  <p className="sizes" aria-label="Sizes">
                    {p.sizes.map((s) => (
                      <span key={s}>{s}</span>
                    ))}
                  </p>
                  <button
                    className="btn-outline"
                    onClick={() =>
                      askAgent(
                        p.stock > 0
                          ? `I'm interested in the ${p.name}. Is it available in my size?`
                          : `The ${p.name} is sold out. Can you suggest something similar?`,
                      )
                    }
                  >
                    {p.stock > 0 ? "Ask CartPilot about this" : "Find something similar"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <footer className="site-footer">
        <div className="wrap footer-inner">
          <p className="wordmark small">CartPilot</p>
          <p className="muted">
            CartPilot Streetwear is a demo store for the Design to Production agentic AI hackathon. Products,
            prices and orders are fictional.
          </p>
        </div>
      </footer>
    </main>
  );
}
