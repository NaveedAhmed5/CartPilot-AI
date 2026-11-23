"""CartPilot Database Layer (Postgres via psycopg 3).

Originally: connection management, schema for products / orders / user_memories,
seed catalog and user-memory CRUD. Extended with: users (website accounts),
chat_logs (admin analytics), transactional order placement / cancellation, product
search and admin queries.

Every customer-facing query takes `user_id` and filters on it, so one user can never
read or modify another user's orders or memory.
"""

import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Generator, Iterable, List, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

SEED_VERSION = 2
SHIPPING_FEE = 250
FREE_SHIPPING_THRESHOLD = 5000
WELCOME_CODE = "WELCOME10"
WELCOME_DISCOUNT = 0.10
CANCELLABLE_STATUSES = ("pending", "confirmed")
ORDER_STATUSES = ("pending", "confirmed", "shipped", "delivered", "cancelled")

# Pakistani streetwear seed catalog (prices in PKR)
PAKISTANI_STREETWEAR_PRODUCTS: List[Dict[str, Any]] = [
    {
        "name": "Karachi Underground Oversized Hoodie",
        "description": "Heavyweight 400 GSM French terry fleece hoodie with Urdu calligraphy typography and cyberpunk truck-art accents. Colour: jet black.",
        "price": 6500.00,
        "category": "Hoodies",
        "sizes": ["S", "M", "L", "XL"],
        "stock": 45,
    },
    {
        "name": "Lahore Grunge Acid-Wash Boxy Tee",
        "description": "Vintage drop-shoulder distressed graphic tee crafted from 240 GSM single jersey cotton. Colour: acid-wash grey.",
        "price": 3200.00,
        "category": "T-Shirts",
        "sizes": ["M", "L", "XL"],
        "stock": 80,
    },
    {
        "name": "Rawalpindi Tactical Parachute Cargo Pants",
        "description": "Relaxed-fit utilitarian parachute cargo pants with deep tactical cargo pockets and adjustable ankle bungees. Colour: olive green.",
        "price": 5800.00,
        "category": "Bottoms",
        "sizes": ["S", "M", "L"],
        "stock": 35,
    },
    {
        "name": "Gulberg Ribbed Corduroy Trucker Jacket",
        "description": "Structured wide-wale corduroy outerwear jacket with quilted thermal lining and antique brass hardware. Colour: camel brown.",
        "price": 9500.00,
        "category": "Outerwear",
        "sizes": ["M", "L", "XL"],
        "stock": 25,
    },
    {
        "name": "Indus Heritage Embroidered Snapback Cap",
        "description": "Structured 6-panel streetwear cap featuring high-density embroidery of traditional Indus geometric motifs. Colour: navy.",
        "price": 2200.00,
        "category": "Accessories",
        "sizes": ["One Size"],
        "stock": 60,
    },
    {
        "name": "Clifton Sunset Graphic Tee",
        "description": "Lightweight 180 GSM combed-cotton tee with a retro sunset print inspired by Clifton Beach, Karachi. Breathable for summer. Colour: off-white.",
        "price": 2800.00,
        "category": "T-Shirts",
        "sizes": ["S", "M", "L", "XL"],
        "stock": 70,
    },
    {
        "name": "Truck Art Satin Bomber Jacket",
        "description": "Glossy satin bomber with hand-drawn Pakistani truck-art embroidery panels, ribbed cuffs and a padded lining. Colour: emerald green.",
        "price": 11500.00,
        "category": "Outerwear",
        "sizes": ["M", "L", "XL"],
        "stock": 18,
    },
    {
        "name": "Multan Sunset Tie-Dye Hoodie",
        "description": "Mid-weight 320 GSM cotton fleece hoodie with hand-dyed orange-to-purple tie-dye. Kangaroo pocket. Colour: sunset tie-dye.",
        "price": 6900.00,
        "category": "Hoodies",
        "sizes": ["S", "M", "L", "XL"],
        "stock": 40,
    },
    {
        "name": "Islamabad Essential Tee 3-Pack",
        "description": "Three minimal heavyweight 220 GSM cotton tees in black, white and heather grey. Everyday basics with a relaxed fit.",
        "price": 5400.00,
        "category": "T-Shirts",
        "sizes": ["S", "M", "L", "XL", "XXL"],
        "stock": 50,
    },
    {
        "name": "Hunza Puffer Vest",
        "description": "Water-resistant ripstop puffer vest with recycled insulation for northern winters. Colour: glacier white.",
        "price": 7800.00,
        "category": "Outerwear",
        "sizes": ["M", "L", "XL"],
        "stock": 22,
    },
    {
        "name": "Saddar Wide-Leg Denim",
        "description": "Rigid 13 oz wide-leg denim jeans with a raw hem and vintage indigo wash. Colour: indigo blue.",
        "price": 6200.00,
        "category": "Bottoms",
        "sizes": ["S", "M", "L", "XL"],
        "stock": 28,
    },
    {
        "name": "Peshawar Street Runner Sneakers",
        "description": "Chunky street sneakers with a suede-and-mesh upper, inspired by Peshawari chappal stitching. EU sizes 40-45. Colour: sand beige.",
        "price": 8900.00,
        "category": "Footwear",
        "sizes": ["40", "41", "42", "43", "44", "45"],
        "stock": 30,
    },
    {
        "name": "Kohistan Merino Wool Beanie",
        "description": "Soft ribbed merino wool beanie with a woven CartPilot label. Colour: charcoal.",
        "price": 1500.00,
        "category": "Accessories",
        "sizes": ["One Size"],
        "stock": 90,
    },
    {
        "name": "Anarkali Utility Crossbody Bag",
        "description": "Compact nylon crossbody bag with three zip pockets and an adjustable strap. Colour: black.",
        "price": 3900.00,
        "category": "Accessories",
        "sizes": ["One Size"],
        "stock": 35,
    },
    {
        "name": "Lyari Hoops Basketball Jersey",
        "description": "Breathable mesh basketball jersey celebrating Lyari street basketball. Colour: red and white. Currently sold out.",
        "price": 3600.00,
        "category": "T-Shirts",
        "sizes": ["S", "M", "L", "XL"],
        "stock": 0,
    },
]

# Pakistan Standard Time (UTC+5, no daylight saving) for every timestamp we return.
PKT = timezone(timedelta(hours=5), "PKT")

_pool = None
_pool_lock = threading.Lock()


# --------------------------------------------------------------------------- utils
def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(PKT)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: _plain(v) for k, v in dict(row).items()}


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(r) for r in rows]  # type: ignore[misc]


# ---------------------------------------------------------------------- connections
def _target_url(db_url: Optional[str] = None) -> str:
    target_url = db_url or os.getenv("DATABASE_URL") or settings.database_url
    if not target_url:
        raise ValueError("DATABASE_URL is not set in environment or .env file.")
    return target_url


# autocommit + no prepared statements: works with Neon / Supabase PgBouncer
# poolers (transaction mode) and is required by the LangGraph Postgres checkpointer.
CONNECTION_KWARGS: Dict[str, Any] = {
    "autocommit": True,
    "prepare_threshold": None,
    "row_factory": dict_row,
}


def get_connection(db_url: Optional[str] = None) -> psycopg.Connection:
    """Return a psycopg (v3) connection with dict_row row factory."""
    return psycopg.connect(_target_url(db_url), **CONNECTION_KWARGS)


def get_pool(db_url: Optional[str] = None):
    """Lazily initialize and return the global ConnectionPool."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool

                _pool = ConnectionPool(
                    _target_url(db_url),
                    min_size=1,
                    max_size=int(os.getenv("DB_POOL_MAX", "10")),
                    open=True,
                    kwargs=CONNECTION_KWARGS,
                    # Free hosted Postgres drops idle connections; validate before use.
                    check=ConnectionPool.check_connection,
                    max_idle=300,
                    timeout=20,
                )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_db_connection(db_url: Optional[str] = None) -> Generator[psycopg.Connection, None, None]:
    """Context manager for obtaining a pooled database connection."""
    with get_pool(db_url=db_url).connection() as conn:
        yield conn


# --------------------------------------------------------------------------- schema
def create_tables(conn: psycopg.Connection) -> None:
    """Create / migrate all application tables (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                price NUMERIC(10, 2) NOT NULL,
                category VARCHAR(100),
                sizes TEXT[] NOT NULL,
                stock INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                size VARCHAR(50),
                total_price NUMERIC(10, 2) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                shipping_address TEXT,
                city VARCHAR(100),
                items JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        for ddl in (
            "ADD COLUMN IF NOT EXISTS customer_name VARCHAR(255)",
            "ADD COLUMN IF NOT EXISTS phone VARCHAR(30)",
            "ADD COLUMN IF NOT EXISTS subtotal NUMERIC(10, 2)",
            "ADD COLUMN IF NOT EXISTS shipping_fee NUMERIC(10, 2) DEFAULT 0",
            "ADD COLUMN IF NOT EXISTS discount NUMERIC(10, 2) DEFAULT 0",
            "ADD COLUMN IF NOT EXISTS discount_code VARCHAR(50)",
            "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
        ):
            cur.execute(f"ALTER TABLE orders {ddl};")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memories (
                user_id VARCHAR(255) PRIMARY KEY,
                preferred_size VARCHAR(50),
                city VARCHAR(100),
                style_notes TEXT,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS name VARCHAR(100);")
        cur.execute("ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS budget VARCHAR(100);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(64) PRIMARY KEY,
                display_name VARCHAR(100),
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
                id BIGSERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                thread_id VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                reply TEXT NOT NULL,
                tool_calls JSONB NOT NULL DEFAULT '[]'::jsonb,
                tokens_in INTEGER NOT NULL DEFAULT 0,
                tokens_out INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                blocked BOOLEAN NOT NULL DEFAULT FALSE,
                block_reason VARCHAR(50),
                error BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_user_thread ON chat_logs (user_id, thread_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_logs_created ON chat_logs (created_at DESC);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _insert_product(cur: psycopg.Cursor, item: Dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO products (name, description, price, category, sizes, stock)
        VALUES (%s, %s, %s, %s, %s, %s);
        """,
        (item["name"], item["description"], item["price"], item["category"], item["sizes"], item["stock"]),
    )


def seed_products(conn: psycopg.Connection) -> None:
    """Seed the catalog. Runs once per SEED_VERSION so admin edits/deletions stick."""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM app_meta WHERE key = 'seed_version';")
        row = cur.fetchone()
        current = int(row["value"]) if row else 0
        if current >= SEED_VERSION:
            return
        cur.execute("SELECT name FROM products;")
        existing = {r["name"] for r in cur.fetchall()}
        added = 0
        for item in PAKISTANI_STREETWEAR_PRODUCTS:
            if item["name"] not in existing:
                _insert_product(cur, item)
                added += 1
        cur.execute(
            """
            INSERT INTO app_meta (key, value) VALUES ('seed_version', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
            """,
            (str(SEED_VERSION),),
        )
        conn.commit()
        print(f"Seeded {added} streetwear products (seed v{SEED_VERSION}).")


def init_db(db_url: Optional[str] = None) -> None:
    """Connect to DATABASE_URL, create tables, and seed initial products."""
    with get_connection(db_url=db_url) as conn:
        create_tables(conn)
        seed_products(conn)
    print("Database initialization complete.")


# ----------------------------------------------------------------- long-term memory
MEMORY_FIELDS = ("name", "preferred_size", "city", "budget", "style_notes")


def get_user_memory(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve memory and preferences for a user by user_id."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, name, preferred_size, city, budget, style_notes, updated_at
                FROM user_memories
                WHERE user_id = %s;
                """,
                (user_id,),
            )
            return _row(cur.fetchone())


def _merge_notes(old: Optional[str], new: Optional[str], limit: int = 600) -> Optional[str]:
    if not new:
        return old
    notes = [n.strip() for n in (old or "").split(";") if n.strip()]
    for n in new.split(";"):
        n = n.strip()
        if n and n.lower() not in {x.lower() for x in notes}:
            notes.append(n)
    merged = "; ".join(notes)
    while len(merged) > limit and len(notes) > 1:  # keep the most recent notes
        notes.pop(0)
        merged = "; ".join(notes)
    return merged[:limit]


def upsert_user_memory(
    user_id: str,
    preferred_size: Optional[str] = None,
    city: Optional[str] = None,
    style_notes: Optional[str] = None,
    name: Optional[str] = None,
    budget: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert memory preferences for a given user_id. None values keep the old value;
    style notes are appended (de-duplicated) instead of overwritten."""
    with get_db_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT style_notes FROM user_memories WHERE user_id = %s FOR UPDATE;", (user_id,))
                row = cur.fetchone()
                notes = _merge_notes(row["style_notes"] if row else None, style_notes)
                cur.execute(
                    """
                    INSERT INTO user_memories (user_id, preferred_size, city, style_notes, name, budget, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        preferred_size = COALESCE(EXCLUDED.preferred_size, user_memories.preferred_size),
                        city = COALESCE(EXCLUDED.city, user_memories.city),
                        style_notes = COALESCE(EXCLUDED.style_notes, user_memories.style_notes),
                        name = COALESCE(EXCLUDED.name, user_memories.name),
                        budget = COALESCE(EXCLUDED.budget, user_memories.budget),
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING user_id, name, preferred_size, city, budget, style_notes, updated_at;
                    """,
                    (user_id, preferred_size, city, notes, name, budget),
                )
                return _row(cur.fetchone()) or {}


def delete_user_memory(user_id: str) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_memories WHERE user_id = %s;", (user_id,))
            return cur.rowcount > 0


# ------------------------------------------------------------------------- products
_PRODUCT_COLS = "id, name, description, price, category, sizes, stock, is_active, created_at"


def get_products(include_inactive: bool = False) -> List[Dict[str, Any]]:
    """Retrieve all products from the catalog."""
    where = "" if include_inactive else "WHERE is_active"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_PRODUCT_COLS} FROM products {where} ORDER BY id ASC;")
            return _rows(cur.fetchall())


def get_product_by_id(product_id: int, include_inactive: bool = False) -> Optional[Dict[str, Any]]:
    """Retrieve a single product by its ID."""
    extra = "" if include_inactive else "AND is_active"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_PRODUCT_COLS} FROM products WHERE id = %s {extra};", (product_id,))
            return _row(cur.fetchone())


_STOPWORDS = {
    "a", "an", "the", "some", "any", "me", "show", "find", "i", "want", "need", "looking", "look",
    "for", "to", "of", "in", "on", "with", "and", "or", "do", "you", "have", "is", "are", "please",
    "something", "item", "items", "product", "products", "buy", "get", "my", "under", "below",
    "cheap", "best", "good", "new", "pkr", "rs", "size", "sizes", "available", "can", "what",
}
_SYNONYMS = {
    "hoodie": "hoodies", "hoody": "hoodies", "hoodies": "hoodies", "sweatshirt": "hoodies",
    "tee": "t-shirts", "tees": "t-shirts", "tshirt": "t-shirts", "tshirts": "t-shirts",
    "t-shirt": "t-shirts", "t-shirts": "t-shirts", "shirt": "t-shirts", "shirts": "t-shirts",
    "jersey": "t-shirts", "pants": "bottoms", "pant": "bottoms", "trousers": "bottoms",
    "jeans": "bottoms", "denim": "bottoms", "cargo": "bottoms", "cargos": "bottoms", "bottoms": "bottoms",
    "jacket": "outerwear", "jackets": "outerwear", "coat": "outerwear", "vest": "outerwear",
    "bomber": "outerwear", "puffer": "outerwear", "outerwear": "outerwear",
    "cap": "accessories", "caps": "accessories", "hat": "accessories", "beanie": "accessories",
    "bag": "accessories", "accessory": "accessories", "accessories": "accessories",
    "shoes": "footwear", "shoe": "footwear", "sneakers": "footwear", "sneaker": "footwear",
    "trainers": "footwear", "footwear": "footwear",
}


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9\-]+", text.lower()) if t not in _STOPWORDS and len(t) > 1]


def search_products(
    query: Optional[str] = None,
    category: Optional[str] = None,
    max_price: Optional[float] = None,
    size: Optional[str] = None,
    in_stock_only: bool = False,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Keyword search over the (small) active catalog, ranked by relevance."""
    products = get_products()
    cat = (category or "").strip().lower()
    cat = _SYNONYMS.get(cat, cat)
    size_norm = (size or "").strip().upper()
    words = _tokens(query or "")
    results = []
    for p in products:
        p_cat = (p.get("category") or "").lower()
        if cat and cat != p_cat:
            continue
        if max_price is not None and float(p["price"]) > float(max_price):
            continue
        if size_norm and size_norm not in [s.upper() for s in p["sizes"]]:
            continue
        if in_stock_only and p["stock"] <= 0:
            continue
        score = 0.0
        if words:
            name = p["name"].lower()
            desc = (p.get("description") or "").lower()
            for w in words:
                if _SYNONYMS.get(w) == p_cat:
                    score += 3
                if w in name:
                    score += 2
                if w in desc:
                    score += 1
                if w == p_cat:
                    score += 3
            if score == 0:
                continue
        results.append((score, p))
    results.sort(key=lambda sp: (-sp[0], sp[1]["id"]))
    return [p for _, p in results[:limit]]


def create_product(data: Dict[str, Any]) -> Dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO products (name, description, price, category, sizes, stock, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_PRODUCT_COLS};
                """,
                (
                    data["name"], data.get("description", ""), data["price"], data.get("category", ""),
                    data["sizes"], data.get("stock", 0), data.get("is_active", True),
                ),
            )
            return _row(cur.fetchone()) or {}


def update_product(product_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = ("name", "description", "price", "category", "sizes", "stock", "is_active")
    sets = [(k, data[k]) for k in allowed if k in data and data[k] is not None]
    if not sets:
        return get_product_by_id(product_id, include_inactive=True)
    clause = ", ".join(f"{k} = %s" for k, _ in sets)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE products SET {clause} WHERE id = %s RETURNING {_PRODUCT_COLS};",
                [v for _, v in sets] + [product_id],
            )
            return _row(cur.fetchone())


def delete_product(product_id: int) -> bool:
    """Soft delete (keeps order history intact)."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE products SET is_active = FALSE WHERE id = %s;", (product_id,))
            return cur.rowcount > 0


# --------------------------------------------------------------------------- orders
class OrderError(Exception):
    """A business-rule violation that should be explained to the customer."""


_ORDER_COLS = (
    "id, user_id, items, subtotal, shipping_fee, discount, discount_code, total_price, status, "
    "customer_name, phone, shipping_address, city, created_at, updated_at"
)


def quote_order(user_id: str, items: List[Dict[str, Any]], discount_code: Optional[str] = None) -> Dict[str, Any]:
    """Validate items against the live catalog and price them (no writes)."""
    if not items:
        raise OrderError("The order has no items.")
    lines = []
    subtotal = 0.0
    for it in items:
        product = get_product_by_id(int(it["product_id"]))
        if not product:
            raise OrderError(f"Product #{it['product_id']} does not exist.")
        qty = int(it.get("quantity") or 1)
        if qty < 1 or qty > 10:
            raise OrderError("Quantity must be between 1 and 10 per item.")
        size = str(it.get("size") or "").strip()
        sizes = product["sizes"]
        if len(sizes) == 1 and not size:
            size = sizes[0]
        match = next((s for s in sizes if s.upper() == size.upper()), None)
        if not match:
            raise OrderError(f"{product['name']} is available in sizes {', '.join(sizes)} (not '{size or 'unspecified'}').")
        if product["stock"] < qty:
            raise OrderError(
                f"{product['name']} is sold out." if product["stock"] <= 0
                else f"Only {product['stock']} left of {product['name']}."
            )
        line_total = float(product["price"]) * qty
        subtotal += line_total
        lines.append({
            "product_id": product["id"], "name": product["name"], "size": match,
            "quantity": qty, "unit_price": float(product["price"]), "line_total": line_total,
        })
    discount = 0.0
    code = (discount_code or "").strip().upper() or None
    if code:
        if code != WELCOME_CODE:
            raise OrderError(f"Discount code '{code}' is not valid.")
        if count_user_orders(user_id) > 0:
            raise OrderError(f"{WELCOME_CODE} is only valid on your first order.")
        discount = round(subtotal * WELCOME_DISCOUNT)
    shipping = 0.0 if subtotal >= FREE_SHIPPING_THRESHOLD else float(SHIPPING_FEE)
    return {
        "items": lines, "subtotal": subtotal, "discount": discount, "discount_code": code,
        "shipping_fee": shipping, "total": subtotal - discount + shipping,
    }


def count_user_orders(user_id: str) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM orders WHERE user_id = %s AND status <> 'cancelled';", (user_id,)
            )
            return int(cur.fetchone()["n"])


def create_order(
    user_id: str,
    items: List[Dict[str, Any]],
    shipping_address: str,
    city: str,
    phone: str,
    customer_name: Optional[str] = None,
    discount_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically re-validate stock, decrement it and insert the order."""
    quote = quote_order(user_id, items, discount_code)
    with get_db_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for line in quote["items"]:
                    cur.execute(
                        "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s AND is_active;",
                        (line["quantity"], line["product_id"], line["quantity"]),
                    )
                    if cur.rowcount != 1:
                        raise OrderError(f"{line['name']} just went out of stock.")
                first = quote["items"][0]
                cur.execute(
                    f"""
                    INSERT INTO orders (user_id, product_id, quantity, size, items, subtotal, shipping_fee,
                        discount, discount_code, total_price, status, customer_name, phone,
                        shipping_address, city)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                    RETURNING {_ORDER_COLS};
                    """,
                    (
                        user_id, first["product_id"], sum(i["quantity"] for i in quote["items"]), first["size"],
                        Jsonb(quote["items"]), quote["subtotal"], quote["shipping_fee"], quote["discount"],
                        quote["discount_code"], quote["total"], customer_name, phone, shipping_address, city,
                    ),
                )
                return _row(cur.fetchone()) or {}


def list_user_orders(user_id: str, order_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Orders that belong to `user_id` only."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if order_id is not None:
                cur.execute(
                    f"SELECT {_ORDER_COLS} FROM orders WHERE user_id = %s AND id = %s;", (user_id, order_id)
                )
            else:
                cur.execute(
                    f"SELECT {_ORDER_COLS} FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT %s;",
                    (user_id, limit),
                )
            return _rows(cur.fetchall())


def cancel_user_order(user_id: str, order_id: int) -> Dict[str, Any]:
    """Cancel one of the user's own orders and restock its items."""
    with get_db_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, status, items FROM orders WHERE id = %s AND user_id = %s FOR UPDATE;",
                    (order_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    raise OrderError(f"You have no order #{order_id}.")
                if row["status"] not in CANCELLABLE_STATUSES:
                    raise OrderError(f"Order #{order_id} is already {row['status']} and can no longer be cancelled.")
                for line in row["items"] or []:
                    cur.execute(
                        "UPDATE products SET stock = stock + %s WHERE id = %s;",
                        (int(line["quantity"]), int(line["product_id"])),
                    )
                cur.execute(
                    f"""UPDATE orders SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s RETURNING {_ORDER_COLS};""",
                    (order_id,),
                )
                return _row(cur.fetchone()) or {}


# ---------------------------------------------------------------------- admin: orders
def admin_list_orders(status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    f"SELECT {_ORDER_COLS} FROM orders WHERE status = %s ORDER BY created_at DESC LIMIT %s;",
                    (status, limit),
                )
            else:
                cur.execute(f"SELECT {_ORDER_COLS} FROM orders ORDER BY created_at DESC LIMIT %s;", (limit,))
            return _rows(cur.fetchall())


def admin_update_order_status(order_id: int, status: str) -> Optional[Dict[str, Any]]:
    if status not in ORDER_STATUSES:
        raise OrderError(f"Invalid status '{status}'.")
    with get_db_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT status, items FROM orders WHERE id = %s FOR UPDATE;", (order_id,))
                row = cur.fetchone()
                if not row:
                    return None
                if status == "cancelled" and row["status"] != "cancelled":
                    for line in row["items"] or []:
                        cur.execute(
                            "UPDATE products SET stock = stock + %s WHERE id = %s;",
                            (int(line["quantity"]), int(line["product_id"])),
                        )
                elif row["status"] == "cancelled" and status != "cancelled":
                    raise OrderError("A cancelled order cannot be re-opened.")
                cur.execute(
                    f"""UPDATE orders SET status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s RETURNING {_ORDER_COLS};""",
                    (status, order_id),
                )
                return _row(cur.fetchone())


# ---------------------------------------------------------------------------- users
def create_user(username: str, password_hash: str, display_name: Optional[str]) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, display_name, password_hash) VALUES (%s, %s, %s)
                   ON CONFLICT (username) DO NOTHING;""",
                (username, display_name, password_hash),
            )
            return cur.rowcount == 1


def get_user(username: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, display_name, password_hash, created_at FROM users WHERE username = %s;",
                (username,),
            )
            return _row(cur.fetchone())


def admin_list_customers() -> List[Dict[str, Any]]:
    """Everyone who has an account, chatted, ordered or has memory."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ids AS (
                    SELECT username AS user_id FROM users
                    UNION SELECT user_id FROM user_memories
                    UNION SELECT user_id FROM orders
                    UNION SELECT user_id FROM chat_logs
                )
                SELECT ids.user_id,
                       u.display_name,
                       (u.username IS NOT NULL) AS has_account,
                       m.name, m.preferred_size, m.city, m.budget, m.style_notes,
                       (SELECT COUNT(*) FROM orders o WHERE o.user_id = ids.user_id) AS orders,
                       (SELECT COALESCE(SUM(total_price), 0) FROM orders o
                         WHERE o.user_id = ids.user_id AND o.status <> 'cancelled') AS spent,
                       (SELECT COUNT(DISTINCT thread_id) FROM chat_logs c WHERE c.user_id = ids.user_id) AS threads,
                       (SELECT MAX(created_at) FROM chat_logs c WHERE c.user_id = ids.user_id) AS last_seen
                FROM ids
                LEFT JOIN users u ON u.username = ids.user_id
                LEFT JOIN user_memories m ON m.user_id = ids.user_id
                ORDER BY last_seen DESC NULLS LAST, ids.user_id
                LIMIT 500;
                """
            )
            return _rows(cur.fetchall())


# ------------------------------------------------------------------------ chat logs
def log_chat(
    user_id: str, thread_id: str, message: str, reply: str, tool_calls: List[Dict[str, Any]],
    tokens_in: int, tokens_out: int, latency_ms: int, blocked: bool, block_reason: Optional[str], error: bool,
) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_logs (user_id, thread_id, message, reply, tool_calls, tokens_in, tokens_out,
                                       latency_ms, blocked, block_reason, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    user_id, thread_id, message, reply, Jsonb(tool_calls), tokens_in, tokens_out,
                    latency_ms, blocked, block_reason, error,
                ),
            )


def list_user_threads(user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT thread_id,
                       MIN(created_at) AS started_at,
                       MAX(created_at) AS last_at,
                       COUNT(*) AS turns,
                       (ARRAY_AGG(message ORDER BY created_at ASC))[1] AS first_message
                FROM chat_logs WHERE user_id = %s
                GROUP BY thread_id ORDER BY last_at DESC LIMIT %s;
                """,
                (user_id, limit),
            )
            return _rows(cur.fetchall())


def get_thread_log(user_id: str, thread_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT message, reply, tool_calls, created_at FROM chat_logs
                   WHERE user_id = %s AND thread_id = %s ORDER BY created_at ASC, id ASC;""",
                (user_id, thread_id),
            )
            return _rows(cur.fetchall())


def admin_list_chats(user_id: Optional[str] = None, blocked_only: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
    where, params = [], []
    if user_id:
        where.append("user_id = %s")
        params.append(user_id)
    if blocked_only:
        where.append("blocked")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT id, user_id, thread_id, message, reply, tool_calls, tokens_in, tokens_out,
                           latency_ms, blocked, block_reason, error, created_at
                    FROM chat_logs {clause} ORDER BY created_at DESC, id DESC LIMIT %s;""",
                params + [limit],
            )
            return _rows(cur.fetchall())


def admin_stats() -> Dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status <> 'cancelled') AS orders,
                  COUNT(*) FILTER (WHERE status = 'pending') AS pending_orders,
                  COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_orders,
                  COALESCE(SUM(total_price) FILTER (WHERE status <> 'cancelled'), 0) AS revenue,
                  COALESCE(AVG(total_price) FILTER (WHERE status <> 'cancelled'), 0) AS avg_order_value
                FROM orders;
                """
            )
            orders = _row(cur.fetchone()) or {}
            cur.execute(
                """
                SELECT COUNT(*) AS messages,
                       COUNT(DISTINCT user_id) AS chat_users,
                       COUNT(DISTINCT (user_id, thread_id)) AS conversations,
                       COALESCE(SUM(tokens_in), 0) AS tokens_in,
                       COALESCE(SUM(tokens_out), 0) AS tokens_out,
                       COALESCE(AVG(latency_ms) FILTER (WHERE NOT blocked), 0) AS avg_latency_ms,
                       COUNT(*) FILTER (WHERE blocked) AS blocked,
                       COUNT(*) FILTER (WHERE error) AS errors
                FROM chat_logs;
                """
            )
            chats = _row(cur.fetchone()) or {}
            cur.execute(
                """
                SELECT line->>'name' AS name,
                       SUM((line->>'quantity')::int) AS units,
                       SUM((line->>'line_total')::numeric) AS revenue
                FROM orders, jsonb_array_elements(COALESCE(items, '[]'::jsonb)) AS line
                WHERE status <> 'cancelled'
                GROUP BY 1 ORDER BY revenue DESC LIMIT 8;
                """
            )
            top = _rows(cur.fetchall())
            cur.execute(
                """
                SELECT to_char(date_trunc('day', created_at AT TIME ZONE 'Asia/Karachi'), 'YYYY-MM-DD') AS day,
                       COUNT(*) AS orders, COALESCE(SUM(total_price), 0) AS revenue
                FROM orders WHERE status <> 'cancelled' AND created_at > NOW() - INTERVAL '14 days'
                GROUP BY 1 ORDER BY 1;
                """
            )
            daily = _rows(cur.fetchall())
            cur.execute(
                """
                SELECT elem->>'name' AS tool, COUNT(*) AS calls
                FROM chat_logs, jsonb_array_elements(tool_calls) AS elem
                GROUP BY 1 ORDER BY 2 DESC;
                """
            )
            tools = _rows(cur.fetchall())
            cur.execute(
                "SELECT id, name, stock FROM products WHERE is_active AND stock <= 10 ORDER BY stock ASC, id;"
            )
            low_stock = _rows(cur.fetchall())
            cur.execute("SELECT COUNT(*) AS n FROM users;")
            accounts = int(cur.fetchone()["n"])
    return {
        "orders": orders, "chats": chats, "top_products": top, "daily": daily,
        "tool_usage": tools, "low_stock": low_stock, "accounts": accounts,
    }


def ping() -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok;")
            return cur.fetchone()["ok"] == 1


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=_plain, ensure_ascii=False)


if __name__ == "__main__":
    init_db()
