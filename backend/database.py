"""CartPilot Database Layer.

Provides psycopg (v3) connection management, schema initialization for
products, orders, and user_memories tables, product seeding with Pakistani
streetwear items, and user memory CRUD operations.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

# Load environment variables from .env file at repo root or environment
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)
load_dotenv()

DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

# Pakistani streetwear seed catalog (prices in PKR)
PAKISTANI_STREETWEAR_PRODUCTS: List[Dict[str, Any]] = [
    {
        "name": "Karachi Underground Oversized Hoodie",
        "description": "Heavyweight 400 GSM French terry fleece hoodie with Urdu calligraphy typography and cyberpunk truck-art accents.",
        "price": 6500.00,
        "category": "Hoodies",
        "sizes": ["S", "M", "L", "XL"],
        "stock": 45,
    },
    {
        "name": "Lahore Grunge Acid-Wash Boxy Tee",
        "description": "Vintage drop-shoulder distressed graphic tee crafted from 240 GSM single jersey cotton.",
        "price": 3200.00,
        "category": "T-Shirts",
        "sizes": ["M", "L", "XL"],
        "stock": 80,
    },
    {
        "name": "Rawalpindi Tactical Parachute Cargo Pants",
        "description": "Relaxed-fit utilitarian parachute cargo pants with deep tactical cargo pockets and adjustable ankle bungees.",
        "price": 5800.00,
        "category": "Bottoms",
        "sizes": ["S", "M", "L"],
        "stock": 35,
    },
    {
        "name": "Gulberg Ribbed Corduroy Trucker Jacket",
        "description": "Structured wide-wale corduroy outerwear jacket with quilted thermal lining and antique brass hardware.",
        "price": 9500.00,
        "category": "Outerwear",
        "sizes": ["M", "L", "XL"],
        "stock": 25,
    },
    {
        "name": "Indus Heritage Embroidered Snapback Cap",
        "description": "Structured 6-panel streetwear cap featuring high-density embroidery of traditional Indus geometric motifs.",
        "price": 2200.00,
        "category": "Accessories",
        "sizes": ["One Size"],
        "stock": 60,
    },
]

_pool = None


def get_connection(db_url: Optional[str] = None) -> psycopg.Connection:
    """Return a psycopg (v3) connection with dict_row row factory."""
    target_url = db_url or os.getenv("DATABASE_URL") or DATABASE_URL
    if not target_url:
        raise ValueError("DATABASE_URL is not set in environment or .env file.")
    return psycopg.connect(target_url, row_factory=dict_row)


def get_pool(db_url: Optional[str] = None):
    """Lazily initialize and return the global ConnectionPool."""
    global _pool
    if _pool is None:
        target_url = db_url or os.getenv("DATABASE_URL") or DATABASE_URL
        if not target_url:
            raise ValueError("DATABASE_URL is not set in environment or .env file.")
        try:
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                target_url,
                min_size=1,
                max_size=10,
                open=True,
                kwargs={"row_factory": dict_row},
            )
        except Exception:
            _pool = None
    return _pool


@contextmanager
def get_db_connection(db_url: Optional[str] = None) -> Generator[psycopg.Connection, None, None]:
    """Context manager for obtaining a database connection (pool or direct)."""
    pool = None
    try:
        pool = get_pool(db_url=db_url)
    except Exception:
        pool = None

    if pool is not None:
        with pool.connection() as conn:
            yield conn
    else:
        with get_connection(db_url=db_url) as conn:
            yield conn


def create_tables(conn: psycopg.Connection) -> None:
    """Create products, orders, and user_memories tables if they do not exist."""
    with conn.cursor() as cur:
        # 1. products table
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

        # 2. orders table
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

        # 3. user_memories table
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
        conn.commit()


def seed_products(conn: psycopg.Connection) -> None:
    """Seed 5 Pakistani streetwear products if products table is empty."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS count FROM products;")
        result = cur.fetchone()
        count = result["count"] if result else 0

        if count == 0:
            for item in PAKISTANI_STREETWEAR_PRODUCTS:
                cur.execute(
                    """
                    INSERT INTO products (name, description, price, category, sizes, stock)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (
                        item["name"],
                        item["description"],
                        item["price"],
                        item["category"],
                        item["sizes"],
                        item["stock"],
                    ),
                )
            conn.commit()
            print("Seeded 5 Pakistani streetwear products successfully.")
        else:
            print(f"Products table already has {count} entries; skipping seed.")


def init_db(db_url: Optional[str] = None) -> None:
    """Connect to DATABASE_URL, create tables, and seed initial products."""
    with get_connection(db_url=db_url) as conn:
        create_tables(conn)
        seed_products(conn)
    print("Database initialization complete.")


def get_user_memory(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve memory and preferences for a user by user_id."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, preferred_size, city, style_notes, updated_at
                FROM user_memories
                WHERE user_id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def upsert_user_memory(
    user_id: str,
    preferred_size: Optional[str] = None,
    city: Optional[str] = None,
    style_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert memory preferences for a given user_id."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_memories (user_id, preferred_size, city, style_notes, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    preferred_size = COALESCE(EXCLUDED.preferred_size, user_memories.preferred_size),
                    city = COALESCE(EXCLUDED.city, user_memories.city),
                    style_notes = COALESCE(EXCLUDED.style_notes, user_memories.style_notes),
                    updated_at = CURRENT_TIMESTAMP
                RETURNING user_id, preferred_size, city, style_notes, updated_at;
                """,
                (user_id, preferred_size, city, style_notes),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else {}


def get_products() -> List[Dict[str, Any]]:
    """Retrieve all products from the catalog."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, price, category, sizes, stock, created_at
                FROM products
                ORDER BY id ASC;
                """
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def get_product_by_id(product_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single product by its ID."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, price, category, sizes, stock, created_at
                FROM products
                WHERE id = %s;
                """,
                (product_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


if __name__ == "__main__":
    init_db()
