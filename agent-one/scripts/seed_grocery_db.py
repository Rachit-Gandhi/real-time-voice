"""
Seed script — creates grocery_store.db with grocery_items and orders tables.
Run from the agent-one directory:
    uv run python scripts/seed_grocery_db.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "grocery_store.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS grocery_items (
    item_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    price         REAL    NOT NULL,
    stock_qty     INTEGER NOT NULL,
    unit          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT    NOT NULL,
    customer_phone TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',
    total_amount  REAL    NOT NULL DEFAULT 0,
    notes         TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    item_id       INTEGER NOT NULL REFERENCES grocery_items(item_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL    NOT NULL
);
"""

ITEMS = [
    # (name, category, price, stock_qty, unit)
    # Produce
    ("Banana",              "Produce",    0.25,  200, "each"),
    ("Apple (Gala)",        "Produce",    0.60,  150, "each"),
    ("Avocado",             "Produce",    1.20,   80, "each"),
    ("Broccoli",            "Produce",    1.80,   60, "kg"),
    ("Carrot Bag",          "Produce",    1.50,   90, "pack"),
    ("Spinach (bag)",       "Produce",    2.50,   70, "pack"),
    ("Tomato",              "Produce",    0.40,  120, "each"),
    ("Onion",               "Produce",    0.30,  200, "each"),
    ("Garlic",              "Produce",    0.50,  150, "each"),
    ("Potato (1 kg)",       "Produce",    1.20,  100, "pack"),
    ("Lemon",               "Produce",    0.35,  180, "each"),
    ("Strawberries (punnet)","Produce",   3.50,   50, "pack"),
    ("Cucumber",            "Produce",    0.80,   90, "each"),
    ("Bell Pepper",         "Produce",    0.90,   80, "each"),
    ("Mushrooms (250 g)",   "Produce",    2.20,   60, "pack"),
    # Dairy
    ("Whole Milk (1 L)",    "Dairy",      1.30,  120, "litre"),
    ("Cheddar Cheese (400g)","Dairy",     4.50,   80, "pack"),
    ("Greek Yoghurt (500 g)","Dairy",     2.80,   70, "pack"),
    ("Butter (250 g)",      "Dairy",      2.50,   90, "pack"),
    ("Eggs (12 pack)",      "Dairy",      3.20,  100, "pack"),
    ("Cream Cheese (200 g)","Dairy",      2.40,   60, "pack"),
    ("Sour Cream (250 g)",  "Dairy",      1.80,   55, "pack"),
    # Meat & Seafood
    ("Chicken Breast (1 kg)","Meat",      7.50,   60, "kg"),
    ("Beef Mince (500 g)",  "Meat",       5.00,   50, "pack"),
    ("Salmon Fillet (300 g)","Seafood",   8.00,   40, "pack"),
    ("Bacon (200 g)",       "Meat",       4.00,   70, "pack"),
    ("Pork Sausages (6 pk)","Meat",       4.50,   55, "pack"),
    ("Lamb Chops (500 g)",  "Meat",       9.00,   35, "pack"),
    # Bakery
    ("White Bread Loaf",    "Bakery",     2.50,   80, "each"),
    ("Sourdough Loaf",      "Bakery",     4.50,   40, "each"),
    ("Croissant",           "Bakery",     1.20,   60, "each"),
    ("Bagels (4 pack)",     "Bakery",     3.00,   50, "pack"),
    # Pantry
    ("Basmati Rice (1 kg)", "Pantry",     2.80,  100, "pack"),
    ("Penne Pasta (500 g)", "Pantry",     1.50,  120, "pack"),
    ("Olive Oil (500 ml)",  "Pantry",     6.50,   70, "bottle"),
    ("Tinned Tomatoes",     "Pantry",     0.90,  200, "tin"),
    ("Coconut Milk (400 ml)","Pantry",    1.80,   80, "tin"),
    ("Peanut Butter (340 g)","Pantry",    3.20,   65, "jar"),
    ("Honey (500 g)",       "Pantry",     4.50,   55, "jar"),
    ("Soy Sauce (150 ml)",  "Pantry",     2.00,   90, "bottle"),
    ("Salt (1 kg)",         "Pantry",     0.80,  150, "pack"),
    ("Black Pepper (50 g)", "Pantry",     1.50,  120, "pack"),
    # Beverages
    ("Orange Juice (1 L)",  "Beverages",  2.50,   90, "litre"),
    ("Sparkling Water (1 L)","Beverages", 1.00,  150, "litre"),
    ("Coffee Beans (250 g)","Beverages",  7.00,   60, "pack"),
    ("Green Tea (20 bags)", "Beverages",  3.00,   80, "pack"),
    ("Cola (1.5 L)",        "Beverages",  2.20,  100, "bottle"),
    # Snacks & Frozen
    ("Potato Chips (150 g)","Snacks",     2.50,  100, "pack"),
    ("Dark Chocolate (100 g)","Snacks",   2.80,   80, "pack"),
    ("Frozen Peas (1 kg)",  "Frozen",     2.00,   70, "pack"),
    ("Frozen Pizza",        "Frozen",     6.00,   50, "each"),
]

SAMPLE_ORDERS = [
    ("Alice Smith",  "+1-555-0101", "delivered", [
        (1, 4),   # 4 bananas
        (16, 2),  # 2 litres milk
        (20, 1),  # 1 dozen eggs
    ]),
    ("Bob Patel",    "+1-555-0102", "preparing", [
        (23, 2),  # 2 kg chicken breast
        (34, 1),  # rice
        (36, 2),  # 2 tins tomatoes
    ]),
    ("Carol Nguyen", "+1-555-0103", "pending", [
        (30, 1),  # sourdough
        (18, 1),  # Greek yoghurt
        (47, 1),  # coffee beans
    ]),
]


def seed(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    conn.executemany(
        "INSERT INTO grocery_items (name, category, price, stock_qty, unit) VALUES (?,?,?,?,?)",
        ITEMS,
    )

    for customer_name, phone, status, lines in SAMPLE_ORDERS:
        total = sum(
            ITEMS[item_idx - 1][2] * qty   # price * qty (item_id is 1-based)
            for item_idx, qty in lines
        )
        cur = conn.execute(
            "INSERT INTO orders (customer_name, customer_phone, status, total_amount) VALUES (?,?,?,?)",
            (customer_name, phone, status, round(total, 2)),
        )
        order_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?,?,?,?)",
            [(order_id, item_id, qty, ITEMS[item_id - 1][2]) for item_id, qty in lines],
        )

    conn.commit()
    conn.close()
    print(f"Created {db_path}")
    print(f"  grocery_items : {len(ITEMS)} rows")
    print(f"  orders        : {len(SAMPLE_ORDERS)} rows")


if __name__ == "__main__":
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing {DB_PATH.name}")
    seed(DB_PATH)
