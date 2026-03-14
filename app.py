"""
EcoBank — Bank Sampah Digital v2.0
Backend Server (Flask + SQLite + JWT)
Run: python server.py
"""

import sqlite3
import hashlib
import hmac
import os
import re
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, send_from_directory

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None

SECRET_KEY  = os.environ.get("SECRET_KEY", "ecobank_super_secret_key_2025!")
DB_PATH     = os.path.join(os.path.dirname(__file__), "ecobank.db")
TOKEN_EXP_H = 24
PORT        = int(os.environ.get("PORT", 5000))
DEBUG       = os.environ.get("DEBUG", "true").lower() == "true"

app = Flask(__name__, static_folder=os.path.dirname(os.path.abspath(__file__)), static_url_path="")

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"]  = origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def handle_options(path): return jsonify({}), 200

# ── SERVE FRONTEND ─────────────────────────────────────────
@app.route("/")
def serve_index():
    """Serve the frontend index.html"""
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    """Serve static files or fallback to index.html"""
    if path.startswith("api/"):
        return jsonify({"error": "Not found"}), 404
    try:
        return send_from_directory(app.static_folder, path)
    except Exception:
        return send_from_directory(app.static_folder, "index.html")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db: db.close()

def hash_password(plain):
    return hmac.new(SECRET_KEY.encode(), plain.encode(), hashlib.sha256).hexdigest()

def check_password(plain, hashed):
    return hmac.compare_digest(hash_password(plain), hashed)

def make_token(payload):
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXP_H)
    payload["exp"] = int(exp.timestamp())
    payload["iat"] = int(datetime.now(timezone.utc).timestamp())
    return pyjwt.encode(payload, SECRET_KEY, algorithm="HS256")

def decode_token(token):
    try: return pyjwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except: return None

def row_to_dict(row): return dict(row) if row else None
def rows_to_list(rows): return [dict(r) for r in rows]
def ok(data=None, msg="success", code=200):
    b = {"status":"ok","message":msg}
    if data is not None: b["data"] = data
    return jsonify(b), code
def err(msg="error", code=400):
    return jsonify({"status":"error","message":msg}), code
def validate_phone(hp): return bool(re.match(r"^08\d{7,12}$", hp))

def gen_id(prefix, key, db):
    cur = db.execute("UPDATE counter SET value=value+1 WHERE key=? RETURNING value", (key,))
    row = cur.fetchone()
    num = row["value"] if row else 999
    db.commit()
    return f"{prefix}{num:03d}"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS nasabah (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, alamat TEXT NOT NULL,
            hp TEXT NOT NULL UNIQUE, saldo INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL, nasabah_id TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (nasabah_id) REFERENCES nasabah(id)
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pemasok_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL, name TEXT NOT NULL, kontak TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sembako (
            id TEXT PRIMARY KEY, nama TEXT NOT NULL, satuan TEXT NOT NULL DEFAULT 'kg',
            harga INTEGER NOT NULL, stok REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS jenis_sampah (
            id TEXT PRIMARY KEY, jenis TEXT NOT NULL, harga INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS setoran (
            id TEXT PRIMARY KEY, tanggal TEXT NOT NULL,
            nasabah_id TEXT NOT NULL, jenis_sampah_id TEXT NOT NULL,
            berat REAL NOT NULL, harga_per_kg INTEGER NOT NULL, total INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (nasabah_id) REFERENCES nasabah(id),
            FOREIGN KEY (jenis_sampah_id) REFERENCES jenis_sampah(id)
        );
        CREATE TABLE IF NOT EXISTS penarikan (
            id TEXT PRIMARY KEY, tanggal TEXT NOT NULL,
            nasabah_id TEXT NOT NULL, metode TEXT NOT NULL DEFAULT 'cash',
            jumlah INTEGER NOT NULL, sembako_id TEXT, qty REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (nasabah_id) REFERENCES nasabah(id),
            FOREIGN KEY (sembako_id) REFERENCES sembako(id)
        );
        CREATE TABLE IF NOT EXISTS counter (
            key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 1
        );
    """)
    for key, val in [("nasabah",5),("jenis",6),("setoran",9),("penarikan",4),("sembako",5),("pemasok",2)]:
        cur.execute("INSERT OR IGNORE INTO counter(key,value) VALUES(?,?)",(key,val))
    cur.execute("INSERT OR IGNORE INTO admin_users(username,password,name,email) VALUES(?,?,?,?)",
                ("admin",hash_password("admin123"),"Administrator","admin@ecobank.id"))
    for uname,upw,name,kontak in [("pemasok1","pemasok123","Toko Makmur Jaya","081234000001"),
                                   ("pemasok2","pemasok456","UD Sembako Berkah","081234000002")]:
        cur.execute("INSERT OR IGNORE INTO pemasok_users(username,password,name,kontak) VALUES(?,?,?,?)",
                    (uname,hash_password(upw),name,kontak))
    for row in [("SMB001","Beras","kg",14000,500.0),("SMB002","Gula","kg",17000,200.0),
                ("SMB003","Minyak","ltr",20000,150.0),("SMB004","Telur","kg",28000,80.0)]:
        cur.execute("INSERT OR IGNORE INTO sembako(id,nama,satuan,harga,stok) VALUES(?,?,?,?,?)",row)
    for row in [("N001","Siti Rahayu","Jl. Merdeka No. 12, Jakarta","081234567890",125000),
                ("N002","Budi Santoso","Jl. Pahlawan No. 5, Bandung","085678901234",78500),
                ("N003","Dewi Kusuma","Jl. Kenanga No. 8, Surabaya","087890123456",210000),
                ("N004","Ahmad Fauzi","Jl. Anggrek No. 20, Yogyakarta","082345678901",45000)]:
        cur.execute("INSERT OR IGNORE INTO nasabah(id,name,alamat,hp,saldo) VALUES(?,?,?,?,?)",row)
    for uname,upw,nid in [("siti","siti123","N001"),("budi","budi123","N002"),
                           ("dewi","dewi123","N003"),("ahmad","ahmad123","N004")]:
        cur.execute("INSERT OR IGNORE INTO users(username,password,nasabah_id) VALUES(?,?,?)",
                    (uname,hash_password(upw),nid))
    for row in [("S001","Botol Plastik",3000),("S002","Kertas/Kardus",1500),
                ("S003","Kaleng Aluminium",8000),("S004","Besi/Logam",5000),("S005","Kaca/Botol Kaca",1000)]:
        cur.execute("INSERT OR IGNORE INTO jenis_sampah(id,jenis,harga) VALUES(?,?,?)",row)
    for row in [("SET001","2025-01-10","N001","S001",5,3000,15000),
                ("SET002","2025-01-15","N002","S002",8,1500,12000),
                ("SET003","2025-01-20","N003","S003",3,8000,24000),
                ("SET004","2025-02-05","N001","S004",10,5000,50000),
                ("SET005","2025-02-12","N004","S001",4,3000,12000),
                ("SET006","2025-02-18","N002","S003",2,8000,16000),
                ("SET007","2025-03-01","N003","S002",12,1500,18000),
                ("SET008","2025-03-10","N001","S005",6,1000,6000)]:
        cur.execute("INSERT OR IGNORE INTO setoran(id,tanggal,nasabah_id,jenis_sampah_id,berat,harga_per_kg,total) VALUES(?,?,?,?,?,?,?)",row)
    for row in [("TAR001","2025-01-25","N001","cash",30000,None,None),
                ("TAR002","2025-02-28","N002","cash",20000,None,None),
                ("TAR003","2025-03-05","N003","sembako",28000,"SMB001",2.0)]:
        cur.execute("INSERT OR IGNORE INTO penarikan(id,tanggal,nasabah_id,metode,jumlah,sembako_id,qty) VALUES(?,?,?,?,?,?,?)",row)
    conn.commit(); conn.close()
    print("✅ Database initialized:", DB_PATH)

# ── MIDDLEWARE ──────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization","")
        if not auth.startswith("Bearer "): return err("Token tidak ditemukan",401)
        payload = decode_token(auth[7:])
        if not payload: return err("Token tidak valid atau sudah kadaluarsa",401)
        g.user = payload
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization","")
        if not auth.startswith("Bearer "): return err("Token tidak ditemukan",401)
        payload = decode_token(auth[7:])
        if not payload: return err("Token tidak valid",401)
        if payload.get("role") != "admin": return err("Akses ditolak: hanya admin",403)
        g.user = payload
        return f(*args, **kwargs)
    return decorated

def require_pemasok(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization","")
        if not auth.startswith("Bearer "): return err("Token tidak ditemukan",401)
        payload = decode_token(auth[7:])
        if not payload: return err("Token tidak valid",401)
        if payload.get("role") not in ("pemasok","admin"): return err("Akses ditolak: hanya pemasok",403)
        g.user = payload
        return f(*args, **kwargs)
    return decorated

# ── ROUTES ─────────────────────────────────────────────────

@app.get("/api/health")
def health(): return ok({"server":"EcoBank API","version":"2.0.0","status":"running"})

@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role     = (data.get("role") or "user").strip()
    if not username or not password: return err("Username dan password wajib diisi")
    db = get_db()
    if role == "admin":
        a = row_to_dict(db.execute("SELECT * FROM admin_users WHERE username=?",(username,)).fetchone())
        if not a or not check_password(password,a["password"]): return err("Username atau password salah",401)
        token = make_token({"sub":a["id"],"username":a["username"],"name":a["name"],"role":"admin"})
        return ok({"token":token,"user":{"id":a["id"],"username":a["username"],"name":a["name"],"role":"admin"}},"Login berhasil")
    elif role == "pemasok":
        pm = row_to_dict(db.execute("SELECT * FROM pemasok_users WHERE username=?",(username,)).fetchone())
        if not pm or not check_password(password,pm["password"]): return err("Username atau password salah",401)
        token = make_token({"sub":pm["id"],"username":pm["username"],"name":pm["name"],"role":"pemasok","kontak":pm.get("kontak","")})
        return ok({"token":token,"user":{"id":pm["id"],"username":pm["username"],"name":pm["name"],"role":"pemasok","kontak":pm.get("kontak","")}},"Login berhasil")
    else:
        u = row_to_dict(db.execute("SELECT u.*,n.id as nasabah_id,n.name,n.alamat,n.hp,n.saldo FROM users u JOIN nasabah n ON u.nasabah_id=n.id WHERE u.username=?",(username,)).fetchone())
        if not u or not check_password(password,u["password"]): return err("Username atau password salah",401)
        token = make_token({"sub":u["id"],"username":u["username"],"nasabah_id":u["nasabah_id"],"name":u["name"],"role":"user"})
        nasabah = row_to_dict(db.execute("SELECT * FROM nasabah WHERE id=?",(u["nasabah_id"],)).fetchone())
        return ok({"token":token,"user":{"id":u["id"],"username":u["username"],"name":u["name"],"role":"user","nasabah":nasabah}},"Login berhasil")

@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    username=(data.get("username") or "").strip()
    password=(data.get("password") or "").strip()
    name=(data.get("name") or "").strip()
    alamat=(data.get("alamat") or "").strip()
    hp=(data.get("hp") or "").strip()
    if not all([username,password,name,alamat,hp]): return err("Semua field wajib diisi")
    if len(username)<3: return err("Username minimal 3 karakter")
    if not re.match(r"^[a-z0-9_]+$",username): return err("Username hanya huruf kecil, angka, underscore")
    if len(password)<6: return err("Password minimal 6 karakter")
    if not validate_phone(hp): return err("No HP tidak valid (format: 08xxxxxxxxxx)")
    if len(name)<3: return err("Nama minimal 3 karakter")
    db=get_db()
    if db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone(): return err("Username sudah digunakan")
    if db.execute("SELECT id FROM nasabah WHERE hp=?",(hp,)).fetchone(): return err("No HP sudah terdaftar")
    nid=gen_id("N","nasabah",db)
    db.execute("INSERT INTO nasabah(id,name,alamat,hp,saldo) VALUES(?,?,?,?,0)",(nid,name,alamat,hp))
    db.execute("INSERT INTO users(username,password,nasabah_id,role) VALUES(?,?,?,'user')",(username,hash_password(password),nid))
    db.commit()
    nasabah=row_to_dict(db.execute("SELECT * FROM nasabah WHERE id=?",(nid,)).fetchone())
    return ok({"nasabah":nasabah,"username":username},"Registrasi berhasil",201)

@app.get("/api/auth/me")
@require_auth
def me():
    db=get_db(); u=g.user
    if u["role"]=="admin":
        a=row_to_dict(db.execute("SELECT id,username,name,email FROM admin_users WHERE username=?",(u["username"],)).fetchone())
        return ok({"role":"admin",**a})
    elif u["role"]=="pemasok":
        pm=row_to_dict(db.execute("SELECT id,username,name,kontak FROM pemasok_users WHERE username=?",(u["username"],)).fetchone())
        return ok({"role":"pemasok",**pm})
    else:
        nasabah=row_to_dict(db.execute("SELECT * FROM nasabah WHERE id=?",(u["nasabah_id"],)).fetchone())
        return ok({"role":"user","username":u["username"],"nasabah":nasabah})

# ── NASABAH ────────────────────────────────────────────────

@app.get("/api/nasabah")
@require_admin
def get_nasabah():
    db=get_db(); q=request.args.get("q","").strip().lower()
    if q: rows=db.execute("SELECT * FROM nasabah WHERE lower(name) LIKE ? OR lower(id) LIKE ? OR hp LIKE ? ORDER BY id",(f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    else: rows=db.execute("SELECT * FROM nasabah ORDER BY id").fetchall()
    return ok(rows_to_list(rows))

@app.get("/api/nasabah/<id>")
@require_auth
def get_nasabah_by_id(id):
    db=get_db(); u=g.user
    if u["role"]=="user" and u.get("nasabah_id")!=id: return err("Akses ditolak",403)
    row=db.execute("SELECT * FROM nasabah WHERE id=?",(id,)).fetchone()
    if not row: return err("Nasabah tidak ditemukan",404)
    return ok(row_to_dict(row))

@app.post("/api/nasabah")
@require_admin
def create_nasabah():
    data=request.get_json(silent=True) or {}
    name=(data.get("name") or "").strip(); alamat=(data.get("alamat") or "").strip(); hp=(data.get("hp") or "").strip()
    if not all([name,alamat,hp]): return err("Semua field wajib diisi")
    if not validate_phone(hp): return err("No HP tidak valid")
    db=get_db()
    if db.execute("SELECT id FROM nasabah WHERE hp=?",(hp,)).fetchone(): return err("No HP sudah terdaftar")
    nid=gen_id("N","nasabah",db)
    db.execute("INSERT INTO nasabah(id,name,alamat,hp,saldo) VALUES(?,?,?,?,0)",(nid,name,alamat,hp))
    uname=re.sub(r"[^a-z0-9]","",name.split()[0].lower())[:12]
    if db.execute("SELECT id FROM users WHERE username=?",(uname,)).fetchone(): uname=uname+nid[-3:]
    db.execute("INSERT INTO users(username,password,nasabah_id) VALUES(?,?,?)",(uname,hash_password("user123"),nid))
    db.commit()
    nasabah=row_to_dict(db.execute("SELECT * FROM nasabah WHERE id=?",(nid,)).fetchone())
    return ok({"nasabah":nasabah,"username":uname,"default_password":"user123"},"Nasabah ditambahkan",201)

@app.put("/api/nasabah/<id>")
@require_admin
def update_nasabah(id):
    data=request.get_json(silent=True) or {}
    name=(data.get("name") or "").strip(); alamat=(data.get("alamat") or "").strip(); hp=(data.get("hp") or "").strip()
    if not all([name,alamat,hp]): return err("Semua field wajib diisi")
    if not validate_phone(hp): return err("No HP tidak valid")
    db=get_db()
    if db.execute("SELECT id FROM nasabah WHERE hp=? AND id!=?",(hp,id)).fetchone(): return err("No HP sudah digunakan nasabah lain")
    db.execute("UPDATE nasabah SET name=?,alamat=?,hp=? WHERE id=?",(name,alamat,hp,id)); db.commit()
    row=db.execute("SELECT * FROM nasabah WHERE id=?",(id,)).fetchone()
    if not row: return err("Nasabah tidak ditemukan",404)
    return ok(row_to_dict(row),"Nasabah diperbarui")

@app.delete("/api/nasabah/<id>")
@require_admin
def delete_nasabah(id):
    db=get_db()
    if not db.execute("SELECT id FROM nasabah WHERE id=?",(id,)).fetchone(): return err("Nasabah tidak ditemukan",404)
    db.execute("DELETE FROM setoran WHERE nasabah_id=?",(id,))
    db.execute("DELETE FROM penarikan WHERE nasabah_id=?",(id,))
    db.execute("DELETE FROM users WHERE nasabah_id=?",(id,))
    db.execute("DELETE FROM nasabah WHERE id=?",(id,)); db.commit()
    return ok(None,f"Nasabah {id} dihapus")

# ── JENIS SAMPAH ───────────────────────────────────────────

@app.get("/api/jenis-sampah")
@require_auth
def get_jenis_sampah():
    return ok(rows_to_list(get_db().execute("SELECT * FROM jenis_sampah ORDER BY jenis").fetchall()))

@app.post("/api/jenis-sampah")
@require_admin
def create_jenis_sampah():
    data=request.get_json(silent=True) or {}
    jenis=(data.get("jenis") or "").strip(); harga=data.get("harga")
    if not jenis or not harga: return err("Jenis dan harga wajib diisi")
    try: harga=int(harga); assert harga>=0
    except: return err("Harga harus angka positif")
    db=get_db(); sid=gen_id("S","jenis",db)
    db.execute("INSERT INTO jenis_sampah(id,jenis,harga) VALUES(?,?,?)",(sid,jenis,harga)); db.commit()
    return ok({"id":sid,"jenis":jenis,"harga":harga},"Jenis sampah ditambahkan",201)

@app.put("/api/jenis-sampah/<id>")
@require_admin
def update_jenis_sampah(id):
    data=request.get_json(silent=True) or {}
    jenis=(data.get("jenis") or "").strip(); harga=data.get("harga")
    if not jenis or not harga: return err("Jenis dan harga wajib diisi")
    try: harga=int(harga)
    except: return err("Harga tidak valid")
    db=get_db(); db.execute("UPDATE jenis_sampah SET jenis=?,harga=? WHERE id=?",(jenis,harga,id)); db.commit()
    return ok({"id":id,"jenis":jenis,"harga":harga},"Jenis sampah diperbarui")

@app.delete("/api/jenis-sampah/<id>")
@require_admin
def delete_jenis_sampah(id):
    db=get_db()
    if not db.execute("SELECT id FROM jenis_sampah WHERE id=?",(id,)).fetchone(): return err("Tidak ditemukan",404)
    db.execute("DELETE FROM jenis_sampah WHERE id=?",(id,)); db.commit()
    return ok(None,"Jenis sampah dihapus")

# ── SEMBAKO ────────────────────────────────────────────────

@app.get("/api/sembako")
@require_auth
def get_sembako():
    return ok(rows_to_list(get_db().execute("SELECT * FROM sembako ORDER BY nama").fetchall()))

@app.post("/api/sembako")
@require_pemasok
def create_sembako():
    data=request.get_json(silent=True) or {}
    nama=(data.get("nama") or "").strip(); satuan=(data.get("satuan") or "kg").strip()
    harga=data.get("harga"); stok=data.get("stok",0)
    if not nama or not harga: return err("Nama dan harga wajib diisi")
    try: harga=int(harga); stok=float(stok); assert harga>=0 and stok>=0
    except: return err("Harga dan stok harus angka positif")
    db=get_db(); sid=gen_id("SMB","sembako",db)
    db.execute("INSERT INTO sembako(id,nama,satuan,harga,stok) VALUES(?,?,?,?,?)",(sid,nama,satuan,harga,stok)); db.commit()
    return ok({"id":sid,"nama":nama,"satuan":satuan,"harga":harga,"stok":stok},"Sembako ditambahkan",201)

@app.put("/api/sembako/<id>")
@require_pemasok
def update_sembako(id):
    data=request.get_json(silent=True) or {}
    db=get_db()
    row=db.execute("SELECT * FROM sembako WHERE id=?",(id,)).fetchone()
    if not row: return err("Sembako tidak ditemukan",404)
    nama=(data.get("nama") or row["nama"]).strip(); satuan=(data.get("satuan") or row["satuan"]).strip()
    harga=data.get("harga",row["harga"]); stok=data.get("stok",row["stok"])
    try: harga=int(harga); stok=float(stok); assert harga>=0 and stok>=0
    except: return err("Harga dan stok harus angka positif")
    db.execute("UPDATE sembako SET nama=?,satuan=?,harga=?,stok=? WHERE id=?",(nama,satuan,harga,stok,id)); db.commit()
    return ok({"id":id,"nama":nama,"satuan":satuan,"harga":harga,"stok":stok},"Sembako diperbarui")

@app.delete("/api/sembako/<id>")
@require_admin
def delete_sembako(id):
    db=get_db()
    if not db.execute("SELECT id FROM sembako WHERE id=?",(id,)).fetchone(): return err("Tidak ditemukan",404)
    db.execute("DELETE FROM sembako WHERE id=?",(id,)); db.commit()
    return ok(None,"Sembako dihapus")

@app.post("/api/sembako/<id>/restok")
@require_pemasok
def restok_sembako(id):
    data=request.get_json(silent=True) or {}
    qty=data.get("qty")
    try: qty=float(qty); assert qty>0
    except: return err("Qty harus angka positif")
    db=get_db()
    row=db.execute("SELECT * FROM sembako WHERE id=?",(id,)).fetchone()
    if not row: return err("Sembako tidak ditemukan",404)
    new_stok=row["stok"]+qty
    db.execute("UPDATE sembako SET stok=? WHERE id=?",(new_stok,id)); db.commit()
    return ok({"id":id,"stok_lama":row["stok"],"tambahan":qty,"stok_baru":new_stok},
              f"Stok {row['nama']} bertambah {qty} {row['satuan']}")

# ── SETORAN ────────────────────────────────────────────────

@app.get("/api/setoran")
@require_auth
def get_setoran():
    db=get_db(); u=g.user
    base="SELECT s.*,n.name as nasabah_name,j.jenis as jenis_nama FROM setoran s JOIN nasabah n ON s.nasabah_id=n.id JOIN jenis_sampah j ON s.jenis_sampah_id=j.id"
    nid=request.args.get("nasabah_id")
    if u["role"] in ("admin","pemasok"):
        rows=db.execute(base+(" WHERE s.nasabah_id=? ORDER BY s.tanggal DESC"if nid else" ORDER BY s.tanggal DESC"),*([(nid,)]if nid else[])).fetchall()
    else:
        rows=db.execute(base+" WHERE s.nasabah_id=? ORDER BY s.tanggal DESC",(u["nasabah_id"],)).fetchall()
    return ok(rows_to_list(rows))

@app.post("/api/setoran")
@require_admin
def create_setoran():
    data=request.get_json(silent=True) or {}
    tanggal=(data.get("tanggal") or "").strip(); nasabah_id=(data.get("nasabah_id") or "").strip()
    jenis_id=(data.get("jenis_sampah_id") or "").strip(); berat=data.get("berat")
    if not all([tanggal,nasabah_id,jenis_id,berat]): return err("Semua field wajib diisi")
    try: berat=float(berat); assert berat>0
    except: return err("Berat harus angka positif")
    db=get_db()
    jenis=row_to_dict(db.execute("SELECT * FROM jenis_sampah WHERE id=?",(jenis_id,)).fetchone())
    if not jenis: return err("Jenis sampah tidak ditemukan",404)
    total=round(berat*jenis["harga"]); sid=gen_id("SET","setoran",db)
    db.execute("INSERT INTO setoran(id,tanggal,nasabah_id,jenis_sampah_id,berat,harga_per_kg,total) VALUES(?,?,?,?,?,?,?)",
               (sid,tanggal,nasabah_id,jenis_id,berat,jenis["harga"],total))
    db.execute("UPDATE nasabah SET saldo=saldo+? WHERE id=?",(total,nasabah_id)); db.commit()
    result=row_to_dict(db.execute("SELECT s.*,n.name as nasabah_name,j.jenis as jenis_nama FROM setoran s JOIN nasabah n ON s.nasabah_id=n.id JOIN jenis_sampah j ON s.jenis_sampah_id=j.id WHERE s.id=?",(sid,)).fetchone())
    result["saldo_baru"]=db.execute("SELECT saldo FROM nasabah WHERE id=?",(nasabah_id,)).fetchone()["saldo"]
    return ok(result,f"Setoran berhasil! Saldo bertambah Rp {total:,}",201)

# ── PENARIKAN (cash + sembako) ─────────────────────────────

@app.get("/api/penarikan")
@require_auth
def get_penarikan():
    db=get_db(); u=g.user
    base=("SELECT p.*,n.name as nasabah_name,s.nama as sembako_nama,s.satuan as sembako_satuan "
          "FROM penarikan p JOIN nasabah n ON p.nasabah_id=n.id LEFT JOIN sembako s ON p.sembako_id=s.id")
    nid=request.args.get("nasabah_id")
    if u["role"] in ("admin","pemasok"):
        rows=db.execute(base+(" WHERE p.nasabah_id=? ORDER BY p.tanggal DESC"if nid else" ORDER BY p.tanggal DESC"),*([(nid,)]if nid else[])).fetchall()
    else:
        rows=db.execute(base+" WHERE p.nasabah_id=? ORDER BY p.tanggal DESC",(u["nasabah_id"],)).fetchall()
    return ok(rows_to_list(rows))

@app.post("/api/penarikan")
@require_admin
def create_penarikan():
    data=request.get_json(silent=True) or {}
    tanggal=(data.get("tanggal") or "").strip(); nasabah_id=(data.get("nasabah_id") or "").strip()
    metode=(data.get("metode") or "cash").strip().lower()
    if not all([tanggal,nasabah_id]): return err("Tanggal dan nasabah wajib diisi")
    if metode not in ("cash","sembako"): return err("Metode harus cash atau sembako")
    db=get_db()
    nasabah=db.execute("SELECT * FROM nasabah WHERE id=?",(nasabah_id,)).fetchone()
    if not nasabah: return err("Nasabah tidak ditemukan",404)
    sembako_id=None; qty=None; smb=None
    if metode=="cash":
        jumlah=data.get("jumlah")
        try: jumlah=int(jumlah); assert jumlah>=1000
        except: return err("Jumlah minimal Rp 1.000")
        if jumlah>nasabah["saldo"]: return err(f"Saldo tidak cukup! Saldo: Rp {nasabah['saldo']:,}")
    else:
        sembako_id=(data.get("sembako_id") or "").strip()
        if not sembako_id: return err("Pilih jenis sembako")
        qty=data.get("qty")
        try: qty=float(qty); assert qty>0
        except: return err("Qty harus angka positif")
        smb=db.execute("SELECT * FROM sembako WHERE id=?",(sembako_id,)).fetchone()
        if not smb: return err("Sembako tidak ditemukan",404)
        if qty>smb["stok"]: return err(f"Stok {smb['nama']} tidak cukup! Stok: {smb['stok']} {smb['satuan']}")
        jumlah=round(qty*smb["harga"])
        if jumlah>nasabah["saldo"]: return err(f"Saldo tidak cukup! Diperlukan Rp {jumlah:,}, saldo Rp {nasabah['saldo']:,}")
        db.execute("UPDATE sembako SET stok=stok-? WHERE id=?",(qty,sembako_id))
    pid=gen_id("TAR","penarikan",db)
    db.execute("INSERT INTO penarikan(id,tanggal,nasabah_id,metode,jumlah,sembako_id,qty) VALUES(?,?,?,?,?,?,?)",
               (pid,tanggal,nasabah_id,metode,jumlah,sembako_id,qty))
    db.execute("UPDATE nasabah SET saldo=saldo-? WHERE id=?",(jumlah,nasabah_id)); db.commit()
    saldo_baru=db.execute("SELECT saldo FROM nasabah WHERE id=?",(nasabah_id,)).fetchone()["saldo"]
    msg=(f"Penarikan Rp {jumlah:,} berhasil (Cash)" if metode=="cash"
         else f"Penarikan {qty} {smb['satuan']} {smb['nama']} berhasil (Rp {jumlah:,})")
    return ok({"id":pid,"tanggal":tanggal,"nasabah_id":nasabah_id,"metode":metode,
               "jumlah":jumlah,"sembako_id":sembako_id,"qty":qty,"saldo_baru":saldo_baru},msg,201)

# ── STATISTIK ──────────────────────────────────────────────

@app.get("/api/stats")
@require_admin
def get_stats():
    db=get_db()
    total_nasabah =db.execute("SELECT COUNT(*) as c FROM nasabah").fetchone()["c"]
    total_saldo   =db.execute("SELECT COALESCE(SUM(saldo),0) as s FROM nasabah").fetchone()["s"]
    total_berat   =db.execute("SELECT COALESCE(SUM(berat),0) as b FROM setoran").fetchone()["b"]
    total_setoran =db.execute("SELECT COALESCE(SUM(total),0) as t FROM setoran").fetchone()["t"]
    count_setoran =db.execute("SELECT COUNT(*) as c FROM setoran").fetchone()["c"]
    count_penarikan=db.execute("SELECT COUNT(*) as c FROM penarikan").fetchone()["c"]
    count_sembako =db.execute("SELECT COUNT(*) as c FROM sembako").fetchone()["c"]
    monthly=db.execute("SELECT strftime('%m',tanggal) as bulan,SUM(total) as total,SUM(berat) as berat FROM setoran GROUP BY bulan ORDER BY bulan").fetchall()
    jenis_dist=db.execute("SELECT j.jenis,SUM(s.berat) as total_berat FROM setoran s JOIN jenis_sampah j ON s.jenis_sampah_id=j.id GROUP BY j.id ORDER BY total_berat DESC").fetchall()
    penarikan_by_metode=db.execute("SELECT metode,COUNT(*) as count,SUM(jumlah) as total FROM penarikan GROUP BY metode").fetchall()
    return ok({"total_nasabah":total_nasabah,"total_saldo":total_saldo,"total_berat":total_berat,
               "total_setoran":total_setoran,"count_setoran":count_setoran,"count_penarikan":count_penarikan,
               "count_sembako":count_sembako,"monthly":rows_to_list(monthly),"jenis_dist":rows_to_list(jenis_dist),
               "penarikan_by_metode":rows_to_list(penarikan_by_metode)})

@app.get("/api/stats/user")
@require_auth
def get_user_stats():
    db=get_db(); u=g.user
    if u["role"]=="admin": return err("Endpoint untuk nasabah saja",403)
    nid=u["nasabah_id"]
    nasabah=row_to_dict(db.execute("SELECT * FROM nasabah WHERE id=?",(nid,)).fetchone())
    total_berat=db.execute("SELECT COALESCE(SUM(berat),0) as b FROM setoran WHERE nasabah_id=?",(nid,)).fetchone()["b"]
    total_nilai=db.execute("SELECT COALESCE(SUM(total),0) as t FROM setoran WHERE nasabah_id=?",(nid,)).fetchone()["t"]
    count_set=db.execute("SELECT COUNT(*) as c FROM setoran WHERE nasabah_id=?",(nid,)).fetchone()["c"]
    total_tarik=db.execute("SELECT COALESCE(SUM(jumlah),0) as j FROM penarikan WHERE nasabah_id=?",(nid,)).fetchone()["j"]
    count_tarik=db.execute("SELECT COUNT(*) as c FROM penarikan WHERE nasabah_id=?",(nid,)).fetchone()["c"]
    monthly=db.execute("SELECT strftime('%m',tanggal) as bulan,SUM(berat) as berat,SUM(total) as total FROM setoran WHERE nasabah_id=? GROUP BY bulan ORDER BY bulan",(nid,)).fetchall()
    return ok({"nasabah":nasabah,"total_berat":total_berat,"total_nilai":total_nilai,"count_setoran":count_set,
               "total_tarik":total_tarik,"count_penarikan":count_tarik,"monthly":rows_to_list(monthly)})

@app.get("/api/stats/pemasok")
@require_pemasok
def get_pemasok_stats():
    db=get_db()
    sembako_list=rows_to_list(db.execute("SELECT * FROM sembako ORDER BY nama").fetchall())
    total_nilai_stok=sum(s["harga"]*s["stok"] for s in sembako_list)
    count_smb_penarikan=db.execute("SELECT COUNT(*) as c FROM penarikan WHERE metode='sembako'").fetchone()["c"]
    recent=rows_to_list(db.execute("SELECT p.*,n.name as nasabah_name,s.nama as sembako_nama,s.satuan FROM penarikan p JOIN nasabah n ON p.nasabah_id=n.id LEFT JOIN sembako s ON p.sembako_id=s.id WHERE p.metode='sembako' ORDER BY p.tanggal DESC LIMIT 10").fetchall())
    return ok({"sembako":sembako_list,"total_nilai_stok":total_nilai_stok,"count_penarikan_sembako":count_smb_penarikan,"recent_penarikan":recent})

@app.get("/api/transaksi")
@require_auth
def get_all_transaksi():
    db=get_db()
    s=rows_to_list(db.execute("SELECT s.id,s.tanggal,s.nasabah_id,n.name as nasabah_name,'setoran' as tipe,j.jenis as detail,s.berat,s.total as jumlah,NULL as metode FROM setoran s JOIN nasabah n ON s.nasabah_id=n.id JOIN jenis_sampah j ON s.jenis_sampah_id=j.id").fetchall())
    p=rows_to_list(db.execute("SELECT p.id,p.tanggal,p.nasabah_id,n.name as nasabah_name,'penarikan' as tipe,COALESCE(s.nama,'Cash') as detail,p.qty as berat,p.jumlah,p.metode FROM penarikan p JOIN nasabah n ON p.nasabah_id=n.id LEFT JOIN sembako s ON p.sembako_id=s.id").fetchall())
    all_rows=s+p; all_rows.sort(key=lambda x:x["tanggal"],reverse=True)
    return ok(all_rows)

# ── MAIN ───────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print(f"""
╔══════════════════════════════════════════════════╗
║     🌿  EcoBank API Server v2.0                  ║
║     Running on http://localhost:{PORT}              ║
╠══════════════════════════════════════════════════╣
║  Role: admin | user (nasabah) | pemasok          ║
║  POST  /api/auth/login                           ║
║  POST  /api/auth/register                        ║
║  GET/POST/PUT/DEL /api/sembako                   ║
║  POST  /api/sembako/:id/restok                   ║
║  POST  /api/penarikan  (metode: cash|sembako)    ║
║  GET   /api/stats/pemasok                        ║
╚══════════════════════════════════════════════════╝""")
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
