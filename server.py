import sys
import os
import json
import urllib.request
import urllib.error
import http.server
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, timedelta

# Add fridge dir to path for db import
sys.path.insert(0, os.path.dirname(__file__))
import db

try:
    from config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = None

# Read from env so Railway can inject secrets without a config.py
if not GEMINI_API_KEY:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

API_KEY = os.environ.get("FRIDGE_API_KEY")  # key for /api/status

PORT = int(os.environ.get("PORT", 8000))
UPC_URL = "https://api.upcitemdb.com/prod/trial/lookup?upc={}"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={}"


# ── Gemini shelf-life ──────────────────────────────────────────────────────────

def get_shelf_life(product_name: str) -> dict:
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        return {"error": "no_api_key"}

    prompt = (
        f"You are a food safety expert. How many days after purchase can '{product_name}' "
        f"typically be kept in a refrigerator before it should be consumed or discarded? "
        f"Consider an unopened product stored at standard fridge temperature (4°C / 39°F). "
        f"If the product is shelf-stable or non-perishable, give a reasonable estimate assuming it is opened and refrigerated. "
        f"Reply with a SINGLE integer (number of days) and absolutely nothing else. No units, no explanation. Example: 7"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode()
    req = urllib.request.Request(
        GEMINI_URL.format(GEMINI_API_KEY),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        print(f"[Gemini] status=200 body={raw[:500]}")
        data = json.loads(raw)
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"[Gemini] text={text!r}")
        days = int("".join(filter(str.isdigit, text)))
        suggested = (date.today() + timedelta(days=days)).isoformat()
        return {"days": days, "suggested_expiry": suggested}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Gemini] HTTP {e.code} — {body}")
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        print(f"[Gemini] Exception: {e}")
        return {"error": str(e)}


# ── UPCitemdb lookup ───────────────────────────────────────────────────────────

def lookup(barcode: str) -> dict:
    req = urllib.request.Request(
        UPC_URL.format(barcode),
        headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"error": str(e.reason)}

    items = data.get("items", [])
    if not items:
        return {"error": "not found"}

    p = items[0]
    return {
        "barcode": barcode,
        "name": p.get("title") or "Unknown",
        "brand": p.get("brand") or "",
        "image_url": (p.get("images") or [""])[0],
        "lowest_price": p.get("lowest_recorded_price"),
    }


# ── HTML (read from file) ──────────────────────────────────────────────────────

def read_html() -> bytes:
    path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(path, "rb") as f:
        return f.read()


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  {args[0]} {args[1]}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send(200, "text/html", read_html())

        elif path == "/lookup":
            barcode = qs.get("upc", [""])[0]
            if not barcode:
                self._json(400, {"error": "missing upc"})
                return
            self._json(200, lookup(barcode))

        elif path == "/products":
            include_thrown = qs.get("thrown", [""])[0] == "1"
            db.refresh_statuses()
            self._json(200, db.list_products(include_thrown))

        elif path == "/alerts":
            db.refresh_statuses()
            self._json(200, db.get_alerts())

        elif path == "/shelf-life":
            name = qs.get("name", [""])[0]
            if not name:
                self._json(400, {"error": "missing name"})
                return
            self._json(200, get_shelf_life(name))

        elif path == "/api/status":
            key = qs.get("key", [""])[0]
            if not API_KEY or key != API_KEY:
                self._json(401, {"error": "unauthorized"})
                return
            db.refresh_statuses()
            products = db.list_products(include_thrown=False)
            alerts = db.get_alerts()
            self._json(200, {
                "products": len(products),
                "alerts": len(alerts),
            })

        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/product":
            required = ["barcode", "name", "expiry_date"]
            if not all(body.get(k) for k in required):
                self._json(400, {"error": f"missing fields: {required}"})
                return
            product = db.add_product(
                barcode=body["barcode"],
                name=body["name"],
                brand=body.get("brand", ""),
                image_url=body.get("image_url", ""),
                expiry_date=body["expiry_date"],
            )
            self._json(201, product)

        elif path.startswith("/product/") and path.endswith("/open"):
            barcode = path.split("/")[2]
            product = db.mark_opened(barcode)
            if product:
                self._json(200, product)
            else:
                self._json(404, {"error": "not found"})

        elif path.startswith("/product/") and path.endswith("/throw"):
            barcode = path.split("/")[2]
            product = db.mark_thrown(barcode)
            if product:
                self._json(200, product)
            else:
                self._json(404, {"error": "not found"})

        else:
            self._send(404, "text/plain", b"Not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self._send(code, "application/json", body)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)

    # Local dev: wrap with SSL if cert/key present (required for iPhone camera)
    cert = os.path.join(os.path.dirname(__file__), "cert.pem")
    key  = os.path.join(os.path.dirname(__file__), "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        proto = "https"
    else:
        proto = "http"

    ip = os.popen("ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null").read().strip()
    print(f"FridgeTracker running on:")
    print(f"  Local  → {proto}://localhost:{PORT}")
    if ip:
        print(f"  Network → {proto}://{ip}:{PORT}")
    print(f"  DB     → {os.path.abspath(db.DB_PATH)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
