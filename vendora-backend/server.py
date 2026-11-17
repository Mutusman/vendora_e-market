"""VENDORA backend: Python standard library + SQLite. No pip install needed.

Run:   ADMIN_PASSWORD=choose-a-password python3 server.py
Open:  http://localhost:8000   (set HOST=0.0.0.0 to test from a phone on the same Wi-Fi)

Saves products, orders and seller applications in vendora.db.
It does NOT process payments, and it has no customer or seller accounts.
Admin access is a single shared password: fine for testing, not enough for a public launch.
"""
import hmac, json, os, re, secrets, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "vendora.db"
PASSWORD_SET = bool(os.environ.get("ADMIN_PASSWORD"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(8)
CATS = ["Fashion", "Gadgets & Electronics", "Kitchen Products", "Furniture",
        "Beauty & Personal Care", "Home Essentials", "Other Products"]
PHONE = re.compile(r"^(\+234|0)[789][01]\d{8}$")
EMAIL = re.compile(r"^\S+@\S+\.\S+$")
SEED = [
    ("Ankara Print Shirt", 12500, "Fashion", "👔"), ("Leather Sandals", 9800, "Fashion", "👡"),
    ("Aso-Oke Cap", 6500, "Fashion", "🧢"), ("Wireless Earbuds", 18500, "Gadgets & Electronics", "🎧"),
    ("20,000mAh Power Bank", 15000, "Gadgets & Electronics", "🔋"), ("Smart Watch", 32000, "Gadgets & Electronics", "⌚"),
    ("Non-stick Frying Pan", 8500, "Kitchen Products", "🍳"), ("Blender 1.5L", 24000, "Kitchen Products", "🥤"),
    ("Cutlery Set (24pc)", 11000, "Kitchen Products", "🍴"), ("Study Desk", 45000, "Furniture", "🪑"),
    ("3-Seater Sofa", 185000, "Furniture", "🛋️"), ("Shea Butter Body Cream", 4500, "Beauty & Personal Care", "🧴"),
    ("Perfume Oil 50ml", 7500, "Beauty & Personal Care", "🌸"), ("Bedsheet Set", 16500, "Home Essentials", "🛏️"),
    ("Rechargeable Lamp", 9000, "Home Essentials", "💡"), ("Gift Hamper Box", 14000, "Other Products", "🎁"),
]


class Err(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def rows(sql, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def run(sql, args=()):
    c = sqlite3.connect(DB)
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid, cur.rowcount
    finally:
        c.close()


def init_db():
    run("""CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL, price INTEGER NOT NULL, cat TEXT NOT NULL, emoji TEXT NOT NULL)""")
    run("""CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE,
           name TEXT, phone TEXT, address TEXT, notes TEXT, items TEXT, subtotal INTEGER, created TEXT)""")
    run("""CREATE TABLE IF NOT EXISTS sellers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, biz TEXT,
           phone TEXT, email TEXT, cat TEXT, created TEXT)""")
    if not rows("SELECT id FROM products LIMIT 1"):
        c = sqlite3.connect(DB)
        c.executemany("INSERT INTO products(name,price,cat,emoji) VALUES(?,?,?,?)", SEED)
        c.commit()
        c.close()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"


def clean_product(d):
    name = str(d.get("name", "")).strip()
    try:
        price = int(d.get("price"))
    except (TypeError, ValueError):
        price = 0
    cat, emoji = d.get("cat"), str(d.get("emoji") or "📦")[:8]
    if not 1 <= len(name) <= 80 or not 1 <= price <= 100_000_000 or cat not in CATS:
        raise Err(400, "Invalid product: needs a name, a price above 0 and a valid category.")
    return name, price, cat, emoji


def place_order(d):
    name, phone, address = [str(d.get(k, "")).strip() for k in ("name", "phone", "address")]
    notes = str(d.get("notes", "")).strip()[:500]
    if not 2 <= len(name) <= 100:
        raise Err(400, "Enter your full name.")
    if not PHONE.match(phone.replace(" ", "")):
        raise Err(400, "Enter a valid Nigerian phone number.")
    if not 8 <= len(address) <= 300:
        raise Err(400, "Enter your full delivery address.")
    items = d.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise Err(400, "Your cart is empty or invalid.")
    lines, subtotal = [], 0
    for it in items:  # prices always come from the database, never from the browser
        try:
            pid, qty = int(it["id"]), int(it["qty"])
        except (KeyError, TypeError, ValueError):
            raise Err(400, "Invalid cart.")
        if not 1 <= qty <= 99:
            raise Err(400, "Invalid quantity.")
        found = rows("SELECT * FROM products WHERE id=?", (pid,))
        if not found:
            raise Err(400, "A product in your cart is no longer available.")
        p = found[0]
        lines.append({"id": pid, "name": p["name"], "emoji": p["emoji"], "price": p["price"], "qty": qty})
        subtotal += p["price"] * qty
    ref = "VND-" + secrets.token_hex(3).upper()
    run("INSERT INTO orders(ref,name,phone,address,notes,items,subtotal,created) VALUES(?,?,?,?,?,?,?,?)",
        (ref, name, phone, address, notes, json.dumps(lines), subtotal, now()))
    return {"ref": ref, "items": lines, "subtotal": subtotal}


def add_seller(d):
    name, biz, phone, email = [str(d.get(k, "")).strip() for k in ("name", "biz", "phone", "email")]
    cat = d.get("cat")
    if not (2 <= len(name) <= 100 and 2 <= len(biz) <= 100):
        raise Err(400, "Enter your name and business name.")
    if not PHONE.match(phone.replace(" ", "")) or not EMAIL.match(email) or len(email) > 150:
        raise Err(400, "Enter a valid Nigerian phone number and email.")
    if cat not in CATS:
        raise Err(400, "Choose a valid category.")
    run("INSERT INTO sellers(name,biz,phone,email,cat,created) VALUES(?,?,?,?,?,?)",
        (name, biz, phone, email, cat, now()))
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, data, ctype="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("" if ctype == "application/json" else "; charset=utf-8"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            raise Err(413, "Request too large.")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise Err(400, "Invalid JSON.")
        if not isinstance(d, dict):
            raise Err(400, "Invalid JSON.")
        return d

    def admin(self):
        given = self.headers.get("X-Admin-Password", "").encode()
        if not hmac.compare_digest(given, ADMIN_PASSWORD.encode()):
            time.sleep(0.5)
            raise Err(401, "Wrong admin password.")

    def route(self, m):
        try:
            p = self.path.split("?")[0].rstrip("/") or "/"
            if m == "GET" and p == "/":
                return self.reply(200, (ROOT / "static" / "index.html").read_bytes(), "text/html")
            if p == "/api/products":
                if m == "GET":
                    return self.reply(200, rows("SELECT * FROM products ORDER BY id"))
                if m == "POST":
                    self.admin()
                    pid, _ = run("INSERT INTO products(name,price,cat,emoji) VALUES(?,?,?,?)", clean_product(self.body()))
                    return self.reply(201, rows("SELECT * FROM products WHERE id=?", (pid,))[0])
            mt = re.fullmatch(r"/api/products/(\d+)", p)
            if mt and m == "PUT":
                self.admin()
                _, n = run("UPDATE products SET name=?,price=?,cat=?,emoji=? WHERE id=?",
                           clean_product(self.body()) + (int(mt.group(1)),))
                if not n:
                    raise Err(404, "Product not found.")
                return self.reply(200, {"ok": True})
            if mt and m == "DELETE":
                self.admin()
                run("DELETE FROM products WHERE id=?", (int(mt.group(1)),))
                return self.reply(200, {"ok": True})
            if p == "/api/orders":
                if m == "POST":
                    return self.reply(201, place_order(self.body()))
                if m == "GET":
                    self.admin()
                    out = rows("SELECT * FROM orders ORDER BY id DESC")
                    for o in out:
                        o["items"] = json.loads(o["items"])
                    return self.reply(200, out)
            if p == "/api/sellers":
                if m == "POST":
                    return self.reply(201, add_seller(self.body()))
                if m == "GET":
                    self.admin()
                    return self.reply(200, rows("SELECT * FROM sellers ORDER BY id DESC"))
            raise Err(404, "Not found.")
        except Err as e:
            self.reply(e.code, {"error": e.msg})
        except Exception as e:
            print("Server error:", repr(e))
            self.reply(500, {"error": "Server error."})

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PUT(self): self.route("PUT")
    def do_DELETE(self): self.route("DELETE")


if __name__ == "__main__":
    init_db()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    if not PASSWORD_SET:
        print(f"No ADMIN_PASSWORD set. Temporary admin password for this run: {ADMIN_PASSWORD}")
    print(f"VENDORA running at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
