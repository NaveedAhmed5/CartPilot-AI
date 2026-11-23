"""One-time demo data: two customer accounts with saved preferences and a few
orders, so the admin dashboard isn't empty on first deploy. Disable with
SEED_DEMO_DATA=false."""

import logging

from psycopg.types.json import Jsonb

from . import database as db
from .auth import hash_password

log = logging.getLogger("cartpilot.seed")

DEMO_PASSWORD = "demo1234"
DEMO_USERS = [
    {"username": "ali", "display_name": "Ali Raza", "memory": {"name": "Ali", "preferred_size": "L", "city": "Lahore", "style_notes": "likes oversized fits; prefers black"}},
    {"username": "sara", "display_name": "Sara Khan", "memory": {"name": "Sara", "preferred_size": "S", "city": "Karachi", "style_notes": "prefers light colours for summer"}},
]
# (username, product name, size, qty, status, days ago, address)
DEMO_ORDERS = [
    ("ali", "Karachi Underground Oversized Hoodie", "L", 1, "delivered", 9, "House 12, Street 4, Gulberg III"),
    ("ali", "Rawalpindi Tactical Parachute Cargo Pants", "L", 1, "shipped", 3, "House 12, Street 4, Gulberg III"),
    ("sara", "Clifton Sunset Graphic Tee", "S", 2, "confirmed", 2, "Flat 5B, Block 2, Clifton"),
    ("sara", "Anarkali Utility Crossbody Bag", "One Size", 1, "pending", 0, "Flat 5B, Block 2, Clifton"),
]


def seed_demo_data() -> None:
    with db.get_db_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM app_meta WHERE key = 'demo_seeded' FOR UPDATE;")
                if cur.fetchone():
                    return
                cur.execute("INSERT INTO app_meta (key, value) VALUES ('demo_seeded', '1') ON CONFLICT DO NOTHING;")
                if cur.rowcount == 0:
                    return
                for u in DEMO_USERS:
                    cur.execute(
                        """INSERT INTO users (username, display_name, password_hash) VALUES (%s, %s, %s)
                           ON CONFLICT (username) DO NOTHING;""",
                        (u["username"], u["display_name"], hash_password(DEMO_PASSWORD)),
                    )
                    m = u["memory"]
                    cur.execute(
                        """INSERT INTO user_memories (user_id, name, preferred_size, city, style_notes)
                           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO NOTHING;""",
                        (u["username"], m["name"], m["preferred_size"], m["city"], m["style_notes"]),
                    )
                names = {u["username"]: u["display_name"] for u in DEMO_USERS}
                cities = {u["username"]: u["memory"]["city"] for u in DEMO_USERS}
                for username, pname, size, qty, status, days, address in DEMO_ORDERS:
                    cur.execute("SELECT id, price FROM products WHERE name = %s;", (pname,))
                    p = cur.fetchone()
                    if not p:
                        continue
                    subtotal = float(p["price"]) * qty
                    shipping = 0.0 if subtotal >= db.FREE_SHIPPING_THRESHOLD else float(db.SHIPPING_FEE)
                    items = [{
                        "product_id": p["id"], "name": pname, "size": size, "quantity": qty,
                        "unit_price": float(p["price"]), "line_total": subtotal,
                    }]
                    cur.execute(
                        """
                        INSERT INTO orders (user_id, product_id, quantity, size, items, subtotal, shipping_fee,
                            discount, total_price, status, customer_name, phone, shipping_address, city,
                            created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s, %s,
                                NOW() - make_interval(days => %s), NOW() - make_interval(days => %s));
                        """,
                        (
                            username, p["id"], qty, size, Jsonb(items), subtotal, shipping, subtotal + shipping,
                            status, names[username], "03001234567", address, cities[username], days, days,
                        ),
                    )
    log.info("Demo data seeded (users: ali, sara / password %s)", DEMO_PASSWORD)
