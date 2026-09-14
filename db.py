import sqlite3
import os
from datetime import date, datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "fridge.db")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                barcode      TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                brand        TEXT,
                image_url    TEXT,
                expiry_date  TEXT,
                opened_at    TEXT,
                thrown_at    TEXT,
                added_at     TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'ok'
            )
        """)
        conn.commit()


def _compute_status(expiry_date: str | None, thrown_at: str | None) -> str:
    if thrown_at:
        return "thrown"
    if not expiry_date:
        return "ok"
    delta = (date.fromisoformat(expiry_date) - date.today()).days
    if delta < 0:
        return "expired"
    if delta <= 3:
        return "expiring_soon"
    return "ok"


def add_product(barcode: str, name: str, brand: str, image_url: str, expiry_date: str) -> dict:
    status = _compute_status(expiry_date, None)
    with connect() as conn:
        conn.execute("""
            INSERT INTO products (barcode, name, brand, image_url, expiry_date, added_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(barcode) DO UPDATE SET
                name=excluded.name, brand=excluded.brand, image_url=excluded.image_url,
                expiry_date=excluded.expiry_date, thrown_at=NULL, opened_at=NULL,
                status=excluded.status
        """, (barcode, name, brand, image_url, expiry_date, datetime.now().isoformat(timespec="seconds"), status))
        conn.commit()
    return get_product(barcode)


def get_product(barcode: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM products WHERE barcode=?", (barcode,)).fetchone()
    return dict(row) if row else None


def list_products(include_thrown=False) -> list[dict]:
    with connect() as conn:
        if include_thrown:
            rows = conn.execute("SELECT * FROM products ORDER BY expiry_date ASC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM products WHERE thrown_at IS NULL ORDER BY expiry_date ASC"
            ).fetchall()
    # refresh statuses
    result = []
    for row in rows:
        d = dict(row)
        d["status"] = _compute_status(d.get("expiry_date"), d.get("thrown_at"))
        result.append(d)
    return result


def mark_opened(barcode: str) -> dict | None:
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute("UPDATE products SET opened_at=? WHERE barcode=?", (now, barcode))
        conn.commit()
    return get_product(barcode)


def mark_thrown(barcode: str) -> dict | None:
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            "UPDATE products SET thrown_at=?, status='thrown' WHERE barcode=?",
            (now, barcode)
        )
        conn.commit()
    return get_product(barcode)


def get_alerts() -> list[dict]:
    return [p for p in list_products() if p["status"] in ("expiring_soon", "expired")]


def refresh_statuses():
    """Recalculate status for all non-thrown products (call periodically)."""
    products = list_products()
    with connect() as conn:
        for p in products:
            new_status = _compute_status(p.get("expiry_date"), p.get("thrown_at"))
            conn.execute("UPDATE products SET status=? WHERE barcode=?", (new_status, p["barcode"]))
        conn.commit()


# Init DB on import
init()


if __name__ == "__main__":
    # Quick smoke test
    add_product("3017620422003", "Nutella", "Ferrero", "", str(date.today() + timedelta(days=2)))
    add_product("0016000275263", "Cheerios", "General Mills", "", str(date.today() + timedelta(days=10)))
    add_product("TEST001", "Vieux yaourt", "Danone", "", str(date.today() - timedelta(days=1)))

    print("=== Frigo ===")
    for p in list_products():
        print(f"  [{p['status']:14}] {p['name']} — expire {p['expiry_date']}")

    print("\n=== Alertes ===")
    for p in get_alerts():
        print(f"  ⚠️  {p['name']} ({p['status']})")
