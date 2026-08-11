# -*- coding: utf-8 -*-
"""Кофейный бонусный бот для MAX. v25 FINAL.
python3 main.py | qr | test
"""
import asyncio, csv, io, logging, os, shutil, sqlite3, sys, tempfile, threading, time, uuid
from collections import OrderedDict
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import qrcode, requests, uvicorn, urllib3
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)),".env"),override=True)
os.environ["TZ"]="Europe/Moscow"
time.tzset()
log = logging.getLogger("coffee_bot"); log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_ch = logging.StreamHandler(); _ch.setFormatter(_fmt); log.addHandler(_ch)
try:
    os.makedirs("logs", exist_ok=True)
    _fh = RotatingFileHandler("logs/bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    _fh.setFormatter(_fmt); log.addHandler(_fh)
except Exception: pass
try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

CUP = "☕"; WAVE = "👋"; CARD = "💳"; STAR = "⭐"; HIST = "📜"; HELP = "❓"
USERS = "👥"; SEARCH = "🔍"; EXPORT = "📤"; BACK = "⬅️"; RIGHT = "➡️"
PLUS = "➕"; MINUS = "➖"; EDIT = "✏️"; CROSS = "❌"; PARTY = "🎉"
WARN = "⚠️"; PHONE = "📞"; USER = "👤"; CHART = "📈"; RECEIPT = "🧾"
THINK = "🤔"; TOOLS = "🛠️"; GIFT = "🎁"; MONEY = "💰"; NO = "🚫"
OK = "✅"; HOUR = "⏳"; BRONZE = "🥉"; SILVER = "🥈"; GOLD = "🥇"; DIAM = "💎"
BAG = "🛒"; BULB = "💡"; CHART2 = "📊"; CAKE = "🎂"
MEDAL = "🏅"; HAND = "🤝"; MEGA = "📢"; TICKET = "🎟️"
PB_F = "▰"; PB_E = "▱"

def _env_int(n,d):
    try: return int(os.getenv(n,d))
    except (TypeError,ValueError): return d
def is_float(s):
    try: float(s); return True
    except ValueError: return False
def norm_phone(s):
    d="".join(ch for ch in s if ch.isdigit())
    if len(d)==11 and d[0] in ("7","8"): d=d[1:]
    return "7"+d if len(d)==10 else None

TOKEN=os.getenv("MAX_BOT_TOKEN","").strip(); API=os.getenv("MAX_API_BASE","https://platform-api2.max.ru").strip()
WEBHOOK_URL=os.getenv("MAX_WEBHOOK_URL","").strip(); WEBHOOK_SEC=os.getenv("MAX_WEBHOOK_SECRET","").strip()
ADMINS=set(x.strip() for x in os.getenv("ADMIN_IDS","").split(",") if x.strip())
STAFF=set(x.strip() for x in os.getenv("STAFF_IDS","").split(",") if x.strip())
WELCOME=_env_int("WELCOME_BONUS","100"); DB=os.getenv("DB_PATH","coffee_bot.db").strip() or "coffee_bot.db"
EXPIRE_DAYS=_env_int("POINTS_EXPIRE_DAYS","90"); WARN_DAYS=_env_int("POINTS_EXPIRE_WARNING_DAYS","7")
BDAY_BONUS=_env_int("BIRTHDAY_BONUS","200"); BDAY_DAYS=_env_int("BIRTHDAY_DAYS","3")
MAX_PAY=_env_int("MAX_PAY_PERCENT","50"); REF_BONUS=_env_int("REFERRAL_BONUS","50")
WINBACK_DAYS=_env_int("WINBACK_DAYS","14"); WINBACK_BONUS=_env_int("WINBACK_BONUS","50"); WINBACK_CD=_env_int("WINBACK_COOLDOWN_DAYS","30")
REVIEW_BONUS=_env_int("REVIEW_BONUS","50")
BACKUP_DIR=os.getenv("BACKUP_DIR","backups"); BACKUP_KEEP=_env_int("BACKUP_KEEP","7")
if not TOKEN: log.error("MAX_BOT_TOKEN не задан!")
def is_priv(u): return u in ADMINS or u in STAFF
_started_at=time.time()

LEVELS=[(0,BRONZE+" Новичок",3),(10,SILVER+" Постоялец",5),(30,GOLD+" Завсегдатай",7),(60,DIAM+" VIP",10)]
def pct(v): return max(p for n,_,p in LEVELS if v>=n)
def lvl_name(v):
    n0=LEVELS[0][1]
    for n,nm,_ in LEVELS:
        if v>=n: n0=nm
    return n0
def next_lvl(v):
    for n,nm,p in LEVELS:
        if v<n: return n,nm,p
    return None
def progress_bar(v):
    nl=next_lvl(v)
    if not nl: return f"{DIAM} Максимум!"
    prev=0
    for n,_,_ in LEVELS:
        if v>=n: prev=n
    span=nl[0]-prev; done=v-prev; seg=8
    filled=int(done/span*seg) if span>0 else seg
    return PB_F*filled+PB_E*(seg-filled)+f" {v}/{nl[0]}"

urllib3.disable_warnings(); http=requests.Session(); http.verify=False
H={"Authorization":TOKEN,"Content-Type":"application/json"}

def _conn():
    c=sqlite3.connect(DB,timeout=30,check_same_thread=False); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000"); c.execute("PRAGMA foreign_keys=ON"); return c
@contextmanager
def db():
    c=_conn()
    try:
        yield c; c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()

SCHEMA="""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,max_user_id TEXT UNIQUE NOT NULL,full_name TEXT,name_lc TEXT DEFAULT '',phone TEXT,card_number TEXT UNIQUE NOT NULL,visits_count INTEGER DEFAULT 0,total_spent REAL DEFAULT 0,level INTEGER DEFAULT 0,is_admin INTEGER DEFAULT 0,last_notify TEXT DEFAULT '',birthday TEXT DEFAULT '',bday_year INTEGER DEFAULT 0,referred_by TEXT DEFAULT '',ref_done INTEGER DEFAULT 0,last_winback TEXT DEFAULT '',last_visit TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS points_batches(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,points_left INTEGER NOT NULL,original_points INTEGER NOT NULL,source TEXT,comment TEXT,expires_at TIMESTAMP NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,type TEXT NOT NULL,points INTEGER NOT NULL,comment TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,amount REAL,item TEXT,receipt_id TEXT DEFAULT '',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY,points INTEGER,active INTEGER DEFAULT 1,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS promo_use(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,code TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS review_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,status TEXT DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT);
CREATE INDEX IF NOT EXISTS i_card ON users(card_number);CREATE INDEX IF NOT EXISTS i_phone ON users(phone);CREATE INDEX IF NOT EXISTS i_bu ON points_batches(user_id);CREATE INDEX IF NOT EXISTS i_be ON points_batches(expires_at);CREATE INDEX IF NOT EXISTS i_tx ON transactions(user_id);CREATE INDEX IF NOT EXISTS i_pu ON purchases(user_id);CREATE INDEX IF NOT EXISTS i_uc ON users(created_at);"""
def init_db():
    with db() as c: c.executescript(SCHEMA)
def migrate():
    with db() as c:
        cols=[r[1] for r in c.execute("PRAGMA table_info(users)")]
        for col,ddl in [("birthday","TEXT DEFAULT ''"),("bday_year","INTEGER DEFAULT 0"),("last_visit","TIMESTAMP"),("referred_by","TEXT DEFAULT ''"),("ref_done","INTEGER DEFAULT 0"),("last_winback","TEXT DEFAULT ''"),("name_lc","TEXT DEFAULT ''")]:
            if col not in cols: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        for r in c.execute("SELECT id,full_name FROM users WHERE full_name IS NOT NULL AND full_name!=''"):
            c.execute("UPDATE users SET name_lc=? WHERE id=?",((r["full_name"] or "").lower(),r["id"]))
        pcols=[r[1] for r in c.execute("PRAGMA table_info(purchases)")]
        if "receipt_id" not in pcols: c.execute("ALTER TABLE purchases ADD COLUMN receipt_id TEXT DEFAULT ''")
        for r in c.execute("SELECT id,phone FROM users WHERE phone IS NOT NULL AND phone!=''"):
            np=norm_phone(r["phone"])
            if np and np!=r["phone"]: c.execute("UPDATE users SET phone=? WHERE id=?",(np,r["id"]))
def kv_get(k,d=""):
    with db() as c:
        r=c.execute("SELECT value FROM kv WHERE key=?",(k,)).fetchone(); return r["value"] if r else d
def kv_set(k,v):
    with db() as c: c.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)",(k,v))

def do_backup():
    try:
        os.makedirs(BACKUP_DIR,exist_ok=True)
        c=sqlite3.connect(DB); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
        dst=os.path.join(BACKUP_DIR,"coffee_bot_"+datetime.now().strftime("%Y%m%d_%H%M")+".db")
        shutil.copy2(DB,dst)
        files=sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("coffee_bot_") and f.endswith(".db"))
        for f in files[:-BACKUP_KEEP]:
            try: os.remove(os.path.join(BACKUP_DIR,f))
            except OSError: pass
        kv_set("last_backup",datetime.now().strftime("%d.%m %H:%M"))
        log.info("[backup] %s",dst); return dst
    except Exception as e:
        log.error("[backup] %s",e); return None
def backup_loop():
    while True:
        now=datetime.now()
        nxt=now.replace(hour=3,minute=0,second=0,microsecond=0)
        if nxt<=now: nxt+=timedelta(days=1)
        time.sleep((nxt-now).total_seconds())
        do_backup()

def user_exists(uid):
    with db() as c: return c.execute("SELECT 1 FROM users WHERE max_user_id=?",(uid,)).fetchone() is not None
def ensure_user(uid,name="",welcome=0):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(max_user_id,full_name,name_lc,card_number,is_admin) VALUES(?,?,?,?,?)",(uid,name,(name or "").lower(),"COFFEE"+uuid.uuid4().hex[:8].upper(),int(uid in ADMINS)))
        if name: c.execute("UPDATE users SET full_name=?,name_lc=? WHERE max_user_id=? AND (full_name IS NULL OR full_name='')",(name,(name or "").lower(),uid))
        row=c.execute("SELECT * FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if welcome>0 and not c.execute("SELECT 1 FROM transactions WHERE user_id=? AND type='welcome'",(row["id"],)).fetchone():
            _batch(c,row["id"],welcome,"welcome",GIFT+" Приветственный бонус")
            c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(row["id"],"welcome",welcome,GIFT+" Приветственный бонус"))
        return dict(row)
def _batch(c,uid,points,source,comment="",days=None):
    c.execute("INSERT INTO points_batches(user_id,points_left,original_points,source,comment,expires_at) VALUES(?,?,?,?,?,?)",(uid,points,points,source,comment,datetime.now()+timedelta(days=days or EXPIRE_DAYS)))
def balance(uid):
    with db() as c: return int(c.execute("SELECT COALESCE(SUM(points_left),0) b FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>?",(uid,datetime.now())).fetchone()["b"])
def expiring_soon(uid):
    with db() as c: return int(c.execute("SELECT COALESCE(SUM(points_left),0) b FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>? AND expires_at<=?",(uid,datetime.now(),datetime.now()+timedelta(days=WARN_DAYS))).fetchone()["b"])
def spend_points(uid,points,comment=""):
    if points<=0: return False,balance(uid)
    with db() as c:
        bal=int(c.execute("SELECT COALESCE(SUM(points_left),0) b FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>?",(uid,datetime.now())).fetchone()["b"])
        if points>bal: return False,bal
        left=points
        for b in c.execute("SELECT id,points_left FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>? ORDER BY expires_at",(uid,datetime.now())):
            if left<=0: break
            t=min(left,b["points_left"]); c.execute("UPDATE points_batches SET points_left=points_left-? WHERE id=?",(t,b["id"])); left-=t
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(uid,"writeoff",-points,comment or CARD+" Списание"))
        return True,bal-points
def find_user(q):
    qo=q.strip(); q=qo.lower()
    with db() as c:
        r=c.execute("SELECT * FROM users WHERE card_number=? OR max_user_id=?",(qo,qo)).fetchone()
        if r: return dict(r)
        d="".join(ch for ch in q if ch.isdigit())
        if len(d)>=4:
            r=c.execute("SELECT * FROM users WHERE phone LIKE ?",(f"%{d[-10:]}",)).fetchone()
            if r: return dict(r)
        r=c.execute("SELECT * FROM users WHERE name_lc LIKE ?",(f"%{q}%",)).fetchone()
        if r: return dict(r)
    return None
def history(uid,limit=10):
    with db() as c: return [dict(r) for r in c.execute("SELECT type,points,comment,created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT ?",(uid,limit))]
def purchases_of(uid,limit=5):
    with db() as c: return [dict(r) for r in c.execute("SELECT amount,GROUP_CONCAT(item, ', ') items,created_at FROM purchases WHERE user_id=? AND item!='' GROUP BY COALESCE(NULLIF(receipt_id,''),created_at) ORDER BY created_at DESC LIMIT ?",(uid,limit))]
def recent_items(uid,limit=6):
    with db() as c: return [r["item"] for r in c.execute("SELECT item FROM purchases WHERE user_id=? AND item!='' ORDER BY created_at DESC LIMIT ?",(uid,limit))]
def recent_clients(limit=6):
    with db() as c:
        rows=[dict(r) for r in c.execute("SELECT card_number,full_name FROM users WHERE last_visit IS NOT NULL ORDER BY last_visit DESC LIMIT ?",(limit,))]
        if not rows: rows=[dict(r) for r in c.execute("SELECT card_number,full_name FROM users ORDER BY id DESC LIMIT ?",(limit,))]
        return rows
def top_items(limit=10):
    with db() as c: return [dict(r) for r in c.execute("SELECT item,COUNT(*) cnt,COALESCE(SUM(amount),0) rev FROM purchases WHERE item!='' GROUP BY item ORDER BY cnt DESC LIMIT ?",(limit,))]
def search(q,page=0):
    q=q.strip().lower(); d="".join(ch for ch in q if ch.isdigit())
    with db() as c:
        if d and len(d)>=4:
            v1=d[-10:]; v2=("7"+d[1:])[-10:] if d[0]=="8" else d[-10:]
            cond="(phone LIKE ? OR phone LIKE ?)"; arg=(f"%{v1}%",f"%{v2}%")
        elif q.startswith("coffee"):
            cond="card_number LIKE ?"; arg=(f"%{q.upper()}%",)
        else:
            cond="name_lc LIKE ?"; arg=(f"%{q}%",)
        total=c.execute(f"SELECT COUNT(*) FROM users WHERE {cond}",arg).fetchone()[0]
        rows=[dict(r) for r in c.execute(f"SELECT * FROM users WHERE {cond} ORDER BY created_at DESC LIMIT 10 OFFSET ?",arg+(page*10,))]
    return rows,total
def abc_analysis():
    with db() as c: rows=c.execute("SELECT id,full_name,total_spent FROM users WHERE total_spent>0 ORDER BY total_spent DESC").fetchall()
    total=sum(r["total_spent"] for r in rows)
    if not total: return None
    A,B,C=[],[],[]; cum=0
    for r in rows:
        cum+=r["total_spent"]; share=cum/total
        (A if share<=0.8 else B if share<=0.95 else C).append(r)
    return A,B,C,total
def rfm_analysis():
    now=datetime.now()
    with db() as c: rows=c.execute("SELECT id,full_name,last_visit,visits_count,total_spent FROM users WHERE visits_count>0").fetchall()
    if not rows: return None
    data=[]
    for r in rows:
        try: lv=datetime.fromisoformat(r["last_visit"]) if r["last_visit"] else None
        except ValueError: lv=None
        rd=(now-lv).days if lv else 999
        data.append({"name":r["full_name"] or str(r["id"]),"r":rd,"f":r["visits_count"],"m":r["total_spent"]})
    def tert(v):
        s=sorted(v); n=len(s); return s[n//3],s[2*n//3]
    r1,r2=tert([d["r"] for d in data]); f1,f2=tert([d["f"] for d in data]); m1,m2=tert([d["m"] for d in data])
    for d in data:
        d["rs"]=3 if d["r"]<=r1 else 2 if d["r"]<=r2 else 1
        d["fs"]=3 if d["f"]>=f2 else 2 if d["f"]>=f1 else 1
        d["ms"]=3 if d["m"]>=m2 else 2 if d["m"]>=m1 else 1
    seg={"champions":[],"loyal":[],"promising":[],"atrisk":[],"sleeping":[]}
    for d in data:
        if d["rs"]==3 and d["fs"]==3 and d["ms"]==3: seg["champions"].append(d)
        elif d["fs"]>=2 and d["rs"]>=2: seg["loyal"].append(d)
        elif d["rs"]==3 and d["fs"]<=2: seg["promising"].append(d)
        elif d["rs"]<=2 and d["fs"]>=2: seg["atrisk"].append(d)
        else: seg["sleeping"].append(d)
    return seg
def export_csv():
    with db() as c:
        rows=c.execute("SELECT u.*, COALESCE((SELECT SUM(b.points_left) FROM points_batches b WHERE b.user_id=u.id AND b.points_left>0 AND b.expires_at>?),0) bal FROM users u ORDER BY created_at DESC",(datetime.now(),)).fetchall()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["ID","MAX ID","Имя","Телефон","Карта","Посещений","Потрачено","Баллы","ДР","Регистрация"])
    for r in rows: w.writerow([r["id"],r["max_user_id"],r["full_name"] or "",r["phone"] or "",r["card_number"],r["visits_count"],f"{r['total_spent']:.0f}",int(r["bal"]),r["birthday"],r["created_at"]])
    return out.getvalue()

def _post_retry(url,**kw):
    delay=1
    for _ in range(3):
        try:
            r=http.post(url,**kw)
            if r.status_code in (429,) or r.status_code>=500:
                time.sleep(delay); delay*=2; continue
            return r
        except Exception:
            time.sleep(delay); delay*=2
    return None
def send_text(uid,text):
    r=_post_retry(f"{API}/messages",params={"user_id":uid},json={"text":text},headers=H,timeout=10)
    if r is None or r.status_code!=200:
        log.error("[MAX] send_text fail %s",getattr(r,"status_code","-")); return False
    return True
def send_buttons(uid,text,buttons):
    r=_post_retry(f"{API}/messages",params={"user_id":uid},json={"text":text,"attachments":[{"type":"inline_keyboard","payload":{"buttons":buttons}}]},headers=H,timeout=10)
    if r is None or r.status_code!=200:
        log.error("[MAX] send_buttons fail %s",getattr(r,"status_code","-")); return False
    return True
def _upload(f):
    r=http.post(f"{API}/uploads",headers={"Authorization":TOKEN},files={"data":("qr.png",f,"image/png")},params={"type":"image"},timeout=30)
    if r.status_code!=200: return None
    return r.json().get("file_id")
def upload_image(src):
    try:
        if isinstance(src,str):
            with open(src,"rb") as f: return _upload(f)
        return _upload(src)
    except Exception as e:
        log.error("[upload] %s",e); return None
def send_image(uid,file_id,text=""):
    r=_post_retry(f"{API}/messages",params={"user_id":uid},json={"text":text,"attachments":[{"type":"image","payload":{"file_id":file_id}}]},headers=H,timeout=10)
    return r is not None and r.status_code==200
def generate_qr(card_number):
    qr=qrcode.QRCode(box_size=8,border=2)
    qr.add_data(card_number)
    qr.make(fit=True)
    img=qr.make_image(fill_color="black",back_color="white")
    buf=io.BytesIO(); img.save(buf,"PNG"); buf.seek(0); return buf
def show_qr(uid,name):
    u=ensure_user(uid,name)
    fid=upload_image(generate_qr(u["card_number"]))
    if not fid: return rep(f"{WARN} Не удалось создать QR.",back())
    send_image(uid,fid,f"{CARD} Ваша карта: {u['card_number']}\nПокажите этот QR бариста!")
    return None
def photo_of(d):
    m=d.get("message") or {}
    for a in (m.get("attachments") or []):
        p=a.get("payload") or {}
        if a.get("type") in ("image","photo") or p.get("url"):
            url=p.get("url") or (p.get("photo") or {}).get("url")
            fid=p.get("file_id") or (p.get("photo") or {}).get("file_id")
            if url or fid: return url,fid
    return None,None
def alert_admins(text):
    for a in ADMINS:
        send_text(int(a),text)
def setup_webhook():
    payload={"url":WEBHOOK_URL,"update_types":["message_created","bot_started","message_callback"]}
    if WEBHOOK_SEC: payload["secret"]=WEBHOOK_SEC
    r=http.post(f"{API}/subscriptions",headers=H,timeout=10,json=payload)
    if r.status_code!=200: raise RuntimeError(f"Webhook не зарегистрирован: {r.status_code} {r.text[:100]}")
    log.info("[MAX] webhook OK")
def get_updates():
    try:
        r=http.get(API+"/updates",params={"types":"message_created,bot_started,message_callback"},headers=H,timeout=70)
        if r.status_code!=200:
            log.error("[MAX] updates %s",r.status_code); return None
        d=r.json(); return d if isinstance(d,list) else d.get("updates",[])
    except requests.exceptions.ReadTimeout:
        return []
    except Exception as e:
        log.error("[MAX] %s",e); return None
def _sender(d): return d.get("user") or d.get("sender") or {}
def parse_incoming(d):
    if d.get("update_type") not in ("message_created","bot_started"): return None
    u=_sender(d) or (d.get("message") or {}).get("sender") or {}
    if not u.get("user_id"): return None
    text="/start" if d["update_type"]=="bot_started" else ((d.get("message") or {}).get("body") or {}).get("text","")
    return {"uid":int(u["user_id"]),"text":str(text).strip(),"name":f"{u.get('first_name','')} {u.get('last_name','')}".strip(),"payload":d.get("payload",""),"photo":photo_of(d)}

class Dedup:
    def __init__(s,size=5000): s.size,s.d,s.lock=size,OrderedDict(),threading.Lock()
    def seen(s,k):
        with s.lock:
            if k in s.d: return True
            s.d[k]=1
            if len(s.d)>s.size: s.d.popitem(last=False)
            return False
DEDUP=Dedup()
class Pending:
    TTL=300
    def __init__(s): s.d,s.lock={},threading.Lock()
    def set(s,u,data):
        with s.lock: s.d[u]=(data,time.time())
    def get(s,u):
        with s.lock:
            e=s.d.get(u)
            if e and time.time()-e[1]<s.TTL: return e[0]
            s.d.pop(u,None); return None
    def clear(s,u):
        with s.lock: s.d.pop(u,None)
PENDING=Pending(); PENDING_CASH=Pending(); PENDING_ID=Pending(); PENDING_PAYID=Pending(); PENDING_PAY=Pending(); ONBOARD=Pending(); PENDING_CHECK=Pending(); PENDING_SEARCH=Pending(); PENDING_REVIEW=Pending()

def cb(t,p): return {"type":"callback","text":t,"payload":p}
def back(): return [[cb(BACK+" Меню","show_menu")]]
def cancel(): return [[cb(CROSS+" Отмена","cancel_pending")]]
def rep(t,b=None): return {"text":t,"buttons":b or []}
def chunk(bs,n=2): return [bs[i:i+n] for i in range(0,len(bs),n)]
def recent_buttons(prefix):
    rows=recent_clients()
    if not rows: return []
    return chunk([cb(f"{USER} {r['full_name'] or r['card_number']}",f"{prefix}_{r['card_number']}") for r in rows])
def pick_buttons(rows,prefix):
    return chunk([cb(f"{USER} {r['full_name'] or r['card_number']} · {(r['phone'] or r['card_number'])[-4:]}",f"{prefix}_{r['card_number']}") for r in rows])
def fmt_client(r,bal=None):
    if bal is None: bal=balance(r["id"])
    return (f"{USER} {r['full_name'] or 'Без имени'}\n{CARD} {r['card_number']} · {PHONE} {r['phone'] or '-'}\n"
            f"{STAR} {bal} баллов · {CUP} {r['visits_count']} визитов\n{MONEY} Потрачено: {r['total_spent']:.0f} р.")
def nav(prefix,page,total):
    n=[]
    if page>0: n.append(cb(BACK,f"{prefix}:{page}"))
    if (page+1)*10<total: n.append(cb(RIGHT,f"{prefix}:{page+2}"))
    return [n] if n else []

def menu(uid,name):
    new=not user_exists(uid)
    u=ensure_user(uid,name,WELCOME if not is_priv(uid) else 0)
    bal=balance(u["id"]); name=name or u["full_name"] or "друг"; v=u["visits_count"]
    if new and not is_priv(uid):
        ONBOARD.set(uid,{"step":"phone"})
        t=(f"{PARTY} Добро пожаловать, {name}!{WAVE}\n{GIFT} Вам начислено {WELCOME} баллов!\n\n"
           f"{CARD} Карта: {u['card_number']}\n\nЗаполним профиль?\n{PHONE} Отправьте номер телефона (или «пропустить»):")
        return rep(t,cancel())
    t=(f"{CUP} Привет, {name}!{WAVE}\n\n{CARD} Карта: {u['card_number']}\n{STAR} Баланс: {bal} баллов\n"
       f"{lvl_name(v)} · кешбэк {pct(v)}%\n{CHART} {progress_bar(v)}\n\nВыберите раздел:")
    b=[[cb(CARD+" Карта","show_card"),cb(STAR+" Баланс","show_balance")],[cb(HIST+" История","show_history"),cb(HELP+" Помощь","show_help")]]
    if not is_priv(uid):
        b+=[[cb(MEDAL+" Награды","show_badges"),cb(HAND+" Пригласить","show_refer")],[cb(CARD+" QR-карта","show_qr"),cb(STAR+" Отзыв","show_review")]]
    if is_priv(uid):
        b+=[[cb(RECEIPT+" Чек","checkflow")],[cb(SEARCH+" Поиск","show_search"),cb(USERS+" Клиенты","show_clients")]]
        if uid in ADMINS: b+=[[cb(CHART2+" Топ","show_top"),cb(CHART2+" ABC","show_abc"),cb(CHART2+" RFM","show_rfm")],[cb(BULB+" Инсайты","show_insights"),cb(EXPORT+" CSV","export_csv"),cb(EXPORT+" Файлы","export_files")],[cb(MEGA+" Рассылка","show_broadcast"),cb(TOOLS+" Статус","show_status")]]
    return rep(t,b)

def card(u):
    v=u["visits_count"]; bal=balance(u["id"])
    t=(f"{CARD} Бонусная карта\n\nНомер: {u['card_number']}\nУровень: {lvl_name(v)} · {pct(v)}%\n"
       f"{CHART} {progress_bar(v)}\n"
       f"Баланс: {STAR} {bal} баллов\nВизитов: {CUP} {v}\n")
    nl=next_lvl(v)
    if nl: t+=f"\n{CHART} До {nl[1]}: ещё {nl[0]-v} визитов\n"
    ex=expiring_soon(u["id"])
    if ex: t+=f"\n{WARN} {ex} баллов сгорят за {WARN_DAYS} дн.!\n"
    if u["birthday"]: t+=f"\n{CAKE} ДР: {u['birthday']}\n"
    t+=f"\nБаллами оплачивается до {MAX_PAY}% чека.\nНазовите номер бариста {CUP}"
    return rep(t,back())
def hist(u):
    parts=[]
    buys=purchases_of(u["id"])
    if buys:
        parts.append(f"{BAG} Покупки:")
        parts+=[f"· {b['amount']:.0f} р. - {b['items']}" for b in buys]
        parts.append("")
    rows=history(u["id"])
    if rows:
        parts.append(f"{STAR} Операции с баллами:")
        parts+=[f"{r['points']:+d} · {r['comment'] or r['type']}" for r in rows]
    if not parts: return rep(f"{HIST} Пока пусто.",back())
    return rep("\n".join(parts),back())
def help_screen(u):
    t=(f"{HELP} Как это работает\n\n"
       f"{CUP} Назовите бариста номер карты или телефон перед оплатой\n"
       f"{STAR} Получайте кешбэк 3-10% баллами\n"
       f"{CARD} Оплачивайте баллами до {MAX_PAY}% чека\n"
       f"{HOUR} Баллы действуют {EXPIRE_DAYS} дней\n"
       f"{CAKE} В день рождения дарим {BDAY_BONUS} баллов (сгорят через {BDAY_DAYS} дн.)\n"
       f"{HAND} Приведи друга - получи {REF_BONUS} баллов\n"
       f"{STAR} Отзыв с фото - {REVIEW_BONUS} баллов после проверки\n\n"
       f"{CHART} Уровни:\n")
    for n,nm,p in LEVELS:
        t+=f"{nm} - {p}%"+(f" (от {n} визитов)" if n else "")+"\n"
    t+=f"\n{PHONE} /phone · {CAKE} /bday · {TICKET} /promo КОД · {HAND} /ref КОД · {STAR} /review"
    return rep(t,back())
def badges_of(u):
    b=[]; v=u["visits_count"]
    if v>=1: b.append(f"{CUP} Первый кофе")
    if v>=10: b.append(f"{SILVER} Постоялец")
    if v>=30: b.append(f"{GOLD} Завсегдатай")
    if v>=60: b.append(f"{DIAM} VIP")
    if u["birthday"]: b.append(f"{CAKE} Именинник")
    if u["total_spent"]>=5000: b.append(f"{MONEY} Гурман")
    with db() as c: fr=c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?",(u["card_number"],)).fetchone()[0]
    if fr: b.append(f"{HAND} Друг кофейни ({fr})")
    with db() as c: rv=c.execute("SELECT COUNT(*) FROM review_requests WHERE user_id=? AND status='ok'",(u["id"],)).fetchone()[0]
    if rv: b.append(f"{STAR} За отзыв ({rv})")
    return b
def badges_screen(u):
    b=badges_of(u)
    if not b: return rep(f"{MEDAL} Пока нет наград.\nЗагляните за кофе!",back())
    return rep(f"{MEDAL} Ваши награды:\n\n"+"\n".join("• "+x for x in b),back())
def refer_screen(u):
    return rep(f"{HAND} Приведи друга!\n\nТвой код: {u['card_number']}\nДруг вводит: /ref {u['card_number']}\n\nТы получишь {REF_BONUS} баллов после его первого визита.",back())
def review_screen(u):
    PENDING_REVIEW.set(u["max_user_id"],"1")
    return rep(f"{STAR} Оставьте отзыв о кофейне (Яндекс/2ГИС) и пришлите сюда скриншот.\nПосле проверки начислим {REVIEW_BONUS} баллов!",cancel()+back())
def submit_review(uid,photo):
    url,fid=photo or (None,None)
    with db() as c:
        row=c.execute("SELECT id FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if row: c.execute("INSERT INTO review_requests(user_id,status) VALUES(?,'pending')",(row["id"],))
    for a in ADMINS:
        aid=int(a); sent=False
        if fid: sent=send_image(aid,fid,f"{STAR} Клиент прислал отзыв! Проверьте:")
        elif url:
            try:
                r=http.get(url,timeout=20)
                with tempfile.NamedTemporaryFile(suffix=".png",delete=False) as f: f.write(r.content); path=f.name
                up=upload_image(path)
                try: os.unlink(path)
                except OSError: pass
                if up: sent=send_image(aid,up,f"{STAR} Клиент прислал отзыв! Проверьте:")
            except Exception: sent=False
        if not sent: send_text(aid,f"{STAR} Клиент прислал отзыв (скрин не переслался). Проверьте на платформе.")
        send_buttons(aid,f"{STAR} Отзыв клиента. Начислить {REVIEW_BONUS}?",[[cb(OK+" Начислить",f"review_ok_{uid}"),cb(CROSS+" Нет",f"review_no_{uid}")]])
    return rep(f"{OK} Спасибо! Отзыв на проверке. Начислим {REVIEW_BONUS} после подтверждения.",back())
def do_refer(uid,code):
    inv=find_user(code)
    if not inv: return rep(f"{SEARCH} Код не найден.",back())
    if inv["max_user_id"]==uid: return rep(f"{WARN} Нельзя указать себя.",back())
    with db() as c:
        u=c.execute("SELECT visits_count,referred_by FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if not u: return rep(f"{WARN} Сначала /start.",back())
        if u["referred_by"]: return rep(f"{WARN} Код уже указан.",back())
        if u["visits_count"]>0: return rep(f"{WARN} Код можно ввести до первого визита.",back())
        c.execute("UPDATE users SET referred_by=? WHERE max_user_id=?",(inv["card_number"],uid))
    return rep(f"{OK} Код принят! После первого визита друг получит {REF_BONUS}.",back())
def promo_create(code,points):
    with db() as c: c.execute("INSERT OR REPLACE INTO promos(code,points,active) VALUES(?,?,1)",(code.upper(),points))
    return rep(f"{TICKET} Промокод {code.upper()} на {points} создан.",back())
def promo_stop(code):
    with db() as c: c.execute("UPDATE promos SET active=0 WHERE code=?",(code.upper(),))
    return rep(f"{TICKET} Промокод {code.upper()} деактивирован.",back())
def promo_redeem(uid,code):
    code=code.upper()
    with db() as c:
        r=c.execute("SELECT * FROM promos WHERE code=? AND active=1",(code,)).fetchone()
        if not r: return rep(f"{WARN} Промокод не найден.",back())
        u=c.execute("SELECT id FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if not u: return rep(f"{WARN} Сначала /start.",back())
        if c.execute("SELECT 1 FROM promo_use WHERE user_id=? AND code=?",(u["id"],code)).fetchone():
            return rep(f"{WARN} Вы уже использовали этот код.",back())
        c.execute("INSERT INTO promo_use(user_id,code) VALUES(?,?)",(u["id"],code))
        _batch(c,u["id"],r["points"],"promo",TICKET+" Промокод "+code)
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(u["id"],"accrual",r["points"],TICKET+" Промокод "+code))
    return rep(f"{OK} +{r['points']} баллов по коду {code}!",back())
def _send_broadcast(seg,body,admin_uid):
    now=datetime.now(); ma=now-timedelta(days=30)
    with db() as c:
        if seg=="all": rows=c.execute("SELECT max_user_id FROM users").fetchall()
        elif seg=="active": rows=c.execute("SELECT max_user_id FROM users WHERE last_visit>=?",(ma,)).fetchall()
        else: rows=c.execute("SELECT max_user_id FROM users WHERE last_visit<? OR last_visit IS NULL",(ma,)).fetchall()
    n=0
    for r in rows:
        if send_text(int(r["max_user_id"]),body): n+=1
        time.sleep(0.5)
    log.info("[broadcast] %s -> %d",seg,n)
    send_text(admin_uid,f"{MEGA} Рассылка завершена. Отправлено: {n}.")
def do_broadcast(text,uid):
    p=text.split()
    seg="active"; body=text
    if p and p[0].lower() in ("all","active","sleep"):
        seg=p[0].lower(); body=text.split(maxsplit=1)[1] if len(p)>1 else ""
    if not body: return rep(f"{MEGA} Формат: /broadcast [all|active|sleep] текст",back())
    threading.Thread(target=_send_broadcast,args=(seg,body,int(uid)),daemon=True).start()
    return rep(f"{MEGA} Рассылка запущена: {seg}.",back())
def do_export_files():
    now=datetime.now()
    with db() as c:
        users=c.execute("SELECT u.*, COALESCE((SELECT SUM(b.points_left) FROM points_batches b WHERE b.user_id=u.id AND b.points_left>0 AND b.expires_at>?),0) bal FROM users u ORDER BY created_at DESC",(now,)).fetchall()
        buys=c.execute("SELECT p.amount,p.item,p.created_at,u.full_name,u.card_number,u.phone FROM purchases p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC").fetchall()
    ts=now.strftime("%Y%m%d_%H%M")
    f1,f2=f"clients_{ts}.csv",f"purchases_{ts}.csv"
    with open(f1,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["ID","Имя","Телефон","Карта","Посещений","Потрачено","Баллы","ДР","Регистрация"])
        for r in users: w.writerow([r["id"],r["full_name"] or "",r["phone"] or "",r["card_number"],r["visits_count"],f"{r['total_spent']:.0f}",int(r["bal"]),r["birthday"],r["created_at"]])
    with open(f2,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["Дата","Имя","Карта","Телефон","Сумма","Товар"])
        for r in buys: w.writerow([r["created_at"],r["full_name"] or "",r["card_number"],r["phone"] or "",f"{r['amount']:.0f}",r["item"] or ""])
    return rep(f"{EXPORT} Файлы готовы:\n{f1} · {f2}\nСкачайте через WinSCP.",back())
def do_status(uid):
    if not is_priv(uid): return rep(f"{NO} Только персонал.",back())
    with db() as c:
        u=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        tx=c.execute("SELECT COUNT(*) n FROM transactions").fetchone()["n"]
    up=int(time.time()-_started_at)
    t=(f"{TOOLS} Статус\n\n{OK} Аптайм: {up//3600}ч {(up%3600)//60}м\n{USERS} Клиентов: {u}\n{STAR} Операций: {tx}\n"
       f"{HOUR} Последний бэкап: {kv_get('last_backup','-')}\n{RECEIPT} БД: {os.path.getsize(DB)//1024} КБ\n{CHART} Режим: {'webhook' if WEBHOOK_URL else 'polling'}")
    return rep(t,back())
def do_abc(uid):
    if uid not in ADMINS: return rep(f"{NO} Только админ.",back())
    r=abc_analysis()
    if not r: return rep(f"{CHART2} Пока нет данных о тратах.",back())
    A,B,C,total=r
    def names(x): return ", ".join((n["full_name"] or str(n["id"])) for n in x[:5]) or "-"
    t=(f"{CHART2} ABC-анализ\n\n{MONEY} Выручка: {total:.0f} р.\n\n"
       f"{GOLD} A ({len(A)}): 80% выручки\n{names(A)}\n\n"
       f"{SILVER} B ({len(B)}): 15%\n{names(B)}\n\n"
       f"{BRONZE} C ({len(C)}): 5%\n{names(C)}\n\n"
       f"{BULB} A - внимание и ранний доступ; B - повышать частоту; C - winback-промо.")
    return rep(t,back())
def do_rfm(uid):
    if uid not in ADMINS: return rep(f"{NO} Только админ.",back())
    s=rfm_analysis()
    if not s: return rep(f"{CHART2} Пока нет визитов для RFM.",back())
    def names(x): return ", ".join(n["name"] for n in x[:5]) or "-"
    t=(f"{CHART2} RFM-сегменты\n\n"
       f"{GOLD} Чемпионы ({len(s['champions'])}): {names(s['champions'])}\n"
       f"{STAR} Лояльные ({len(s['loyal'])}): {names(s['loyal'])}\n"
       f"{CHART} Перспективные ({len(s['promising'])}): {names(s['promising'])}\n"
       f"{WARN} На грани ({len(s['atrisk'])}): {names(s['atrisk'])}\n"
       f"{HOUR} Уснувшие ({len(s['sleeping'])}): {names(s['sleeping'])}\n\n"
       f"{BULB} Чемпионам - VIP; лояльным - частота; перспективным - 2-й визит; на грани - промо; уснувшим - winback.")
    return rep(t,back())
def set_phone(uid,text):
    p=text.split()
    if len(p)<2: return rep(f"{PHONE} Укажите: /phone 79991234567",back())
    d=norm_phone(p[1])
    if not d: return rep(f"{PHONE} Неверный формат",back())
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE phone=? AND max_user_id!=?",(d,uid)).fetchone(): return rep(f"{PHONE} Уже привязан.",back())
        c.execute("UPDATE users SET phone=? WHERE max_user_id=?",(d,uid))
    return rep(f"{PHONE} Сохранено: {d}",back())
def parse_bday(s):
    try:
        dt=datetime.strptime(s,"%d.%m"); return dt.day,dt.month
    except ValueError:
        return None
def set_bday(uid,text):
    p=text.split()
    if len(p)<2: return rep(f"{CAKE} Укажите: /bday 15.05",back())
    r=parse_bday(p[1])
    if not r: return rep(f"{CAKE} Неверная дата. Пример: /bday 15.05",back())
    dd,mm=r
    with db() as c: c.execute("UPDATE users SET birthday=? WHERE max_user_id=?",(f"{dd:02d}.{mm:02d}",uid))
    return rep(f"{CAKE} Сохранено: {dd:02d}.{mm:02d}\nВ ДР дарим {BDAY_BONUS} баллов (сгорят через {BDAY_DAYS} дн.)!",back())
def clients(uid,page=0):
    if uid not in ADMINS: return rep(f"{NO} Только админ.",back())
    rows,total=search("",page)
    if not rows: return rep(f"{USERS} Пока пусто.",back())
    return rep(f"{USERS} Клиенты · стр. {page+1} · всего {total}\nВыберите:",pick_buttons(rows,"sel")+nav("cp",page,total)+back())
def do_search(uid,q,page=0):
    if not is_priv(uid): return rep(f"{NO} Только персонал.",back())
    if not q: return rep(f"{SEARCH} /find Иван · /find 7999 · /find COFFEE",back())
    rows,total=search(q,page)
    if not rows:
        with db() as c: allc=[dict(r) for r in c.execute("SELECT card_number,full_name,phone FROM users ORDER BY id DESC LIMIT 6")]
        return rep(f"{SEARCH} «{q}» - не найдено. Выберите из списка:",pick_buttons(allc,"sel")+back())
    return rep(f"{SEARCH} «{q}» · {total}\nВыберите клиента:",pick_buttons(rows,"sel")+nav("sp",page,total)+back())
def do_export(uid):
    if uid not in ADMINS: return rep(f"{NO} Только админ.",back())
    l=export_csv().split("\n")[:21]
    t=f"{EXPORT} База:\n\n"+"\n".join(l)
    if len(l)>=21: t+="\n... (первые 20). Полный файл: /files"
    return rep(t,back())
def do_top(uid):
    if not is_priv(uid): return rep(f"{NO} Только персонал.",back())
    rows=top_items()
    if not rows: return rep(f"{BAG} Пока нет данных.\nДобавляйте товары при кешбэке: «500 латте, круассан».",back())
    l=[f"{BAG} Топ товаров:",""]+[f"{i+1}. {r['item']} · {r['cnt']} раз · {r['rev']:.0f} р." for i,r in enumerate(rows)]
    return rep("\n".join(l),back())
def do_insights(uid):
    if uid not in ADMINS: return rep(f"{NO} Только админ.",back())
    now=datetime.now(); ma=now-timedelta(days=30)
    with db() as c:
        total=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active=c.execute("SELECT COUNT(*) FROM users WHERE last_visit>=?",(ma,)).fetchone()[0]
        dormant=c.execute("SELECT COUNT(*) FROM users WHERE last_visit<? AND last_visit IS NOT NULL",(ma,)).fetchone()[0]
        avg=c.execute("SELECT COALESCE(AVG(amount),0) FROM purchases").fetchone()[0]
    top=top_items(5)
    t=(f"{BULB} Инсайты\n\n{USERS} Всего: {total}\n{CHART} Актив. за 30 дн: {active}\n"
       f"{HOUR} Уснувших (>30 дн): {dormant}\n{RECEIPT} Средний чек: {avg:.0f} р.\n")
    if top: t+="\n"+BAG+" Топ: "+", ".join(r["item"] for r in top)+"\n"
    ideas=[]
    if dormant: ideas.append(f"Вернуть {dormant} уснувших: /broadcast sleep промо")
    if len(top)>=2: ideas.append(f"Бандл: «{top[0]['item']} + {top[1]['item']}» за баллы")
    ideas.append("Двойной кешбэк в тихие часы")
    t+="\n"+OK+" Идеи:\n"+"\n".join("- "+i for i in ideas)
    return rep(t,back())
def admin_card(u):
    items=recent_items(u["id"])
    txt=fmt_client(u)
    if items: txt+=f"\n{BAG} Покупает: {', '.join(items)}"
    b=[[cb(PLUS+"50",f"add_50_{u['card_number']}"),cb(PLUS+"100",f"add_100_{u['card_number']}"),cb(PLUS+"200",f"add_200_{u['card_number']}")],
       [cb(MINUS+"50",f"sub_50_{u['card_number']}"),cb(MINUS+"100",f"sub_100_{u['card_number']}"),cb(MINUS+"200",f"sub_200_{u['card_number']}")],
       [cb(RECEIPT+" Чек",f"chk_{u['card_number']}"),cb(BAG+" Покупки",f"buy_{u['card_number']}")]]+back()
    return rep(txt,b)
def apply_delta(uid,delta,target,comment=""):
    if delta>0:
        with db() as c:
            _batch(c,target["id"],delta,"manual",comment or f"{PLUS} {delta}")
            c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(target["id"],"accrual",delta,comment or f"{PLUS} {delta}"))
    else:
        ok,nb=spend_points(target["id"],-delta,comment or f"{MINUS} {-delta}")
        if not ok: return rep(f"{WARN} Нельзя списать {-delta}. Баланс: {nb}",back())
    PENDING.clear(uid)
    return rep(f"{OK} {PLUS if delta>0 else MINUS} {abs(delta)}\nНовый баланс: {STAR} {balance(target['id'])}",back())
def apply_cashback(target,amount,items=None):
    pts=int(amount*pct(target["visits_count"])/100)
    rid=uuid.uuid4().hex[:8]
    inv_uid=None
    with db() as c:
        _batch(c,target["id"],pts,"cashback",f"{MONEY} Кешбэк за чек {amount:.0f} р.")
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(target["id"],"accrual",pts,f"{MONEY} Кешбэк за чек {amount:.0f} р."))
        c.execute("UPDATE users SET visits_count=visits_count+1,total_spent=total_spent+?,last_visit=? WHERE id=?",(amount,datetime.now(),target["id"]))
        if items: c.executemany("INSERT INTO purchases(user_id,amount,item,receipt_id) VALUES(?,?,?,?)",[(target["id"],amount,it,rid) for it in items])
        ref=c.execute("SELECT referred_by,ref_done FROM users WHERE id=?",(target["id"],)).fetchone()
        if ref and ref["referred_by"] and not ref["ref_done"]:
            inv_row=c.execute("SELECT id,max_user_id FROM users WHERE card_number=?",(ref["referred_by"],)).fetchone()
            if inv_row:
                _batch(c,inv_row["id"],REF_BONUS,"referral",HAND+" За друга")
                c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(inv_row["id"],"accrual",REF_BONUS,HAND+" За друга"))
                c.execute("UPDATE users SET ref_done=1 WHERE id=?",(target["id"],))
                inv_uid=inv_row["max_user_id"]
        u2=c.execute("SELECT visits_count,level FROM users WHERE id=?",(target["id"],)).fetchone()
        nl=max((i for i,(n,_,_) in enumerate(LEVELS) if u2["visits_count"]>=n),default=0)
        up=nl!=u2["level"]
        if up: c.execute("UPDATE users SET level=? WHERE id=?",(nl,target["id"]))
    if inv_uid:
        send_text(int(inv_uid),f"{PARTY} Ваш друг совершил первый визит! +{REF_BONUS} баллов {HAND}")
    v=u2["visits_count"]
    msg=f"{OK} Кешбэк начислен!\n\n{RECEIPT} Чек: {amount:.0f} р.\n{lvl_name(v)} · +{pts} баллов\n{STAR} Баланс: {balance(target['id'])}"
    if up: msg+=f"\n\n{PARTY} Новый уровень: {lvl_name(v)} · {pct(v)}%!"
    return rep(msg,back())
def check_prompt_amount(uid,cn,t):
    return rep(f"{RECEIPT} {t['full_name'] if t else cn}\nСумма чека и товары, например: 600 латте, круассан",cancel()+back())
def check_confirm(uid,cn,amount,items):
    t=find_user(cn); bal=balance(t["id"]) if t else 0
    pts=int(amount*pct(t["visits_count"])/100) if t else 0
    cap=min(bal,int(amount*MAX_PAY/100))
    btn=[[cb(f"{MINUS} {cap}",f"ckd_{cap}_{cn}"),cb("Без баллов",f"ckn_{cn}")]] if cap>0 else [[cb("Без баллов",f"ckn_{cn}")]]
    return rep(f"{RECEIPT} Чек: {amount:.0f} р.\n{MONEY} Кешбэк: +{pts}\n{STAR} Баланс: {bal} · списать до {cap}?\nВыберите:",btn+cancel()+back())
def check_finalize(uid,cn,amount,items,deduct):
    t=find_user(cn)
    if not t: return rep(f"{WARN} не найден",back())
    pre=""
    if deduct>0:
        ok,nb=spend_points(t["id"],deduct,f"{CARD} Оплата баллами")
        if not ok: return rep(f"{WARN} Не хватило баллов",back())
        pre=f"{CARD} Списано {deduct}\n"
    r=apply_cashback(t,amount,items)
    r["text"]=pre+r["text"]; PENDING_CHECK.clear(uid)
    return r
def cash_amount_prompt(uid,cn,t):
    btn=chunk([cb("300",f"qa_300_{cn}"),cb("500",f"qa_500_{cn}"),cb("700",f"qa_700_{cn}"),cb("1000",f"qa_1000_{cn}")])
    return rep(f"{MONEY} {t['full_name'] if t else cn} · кешбэк {pct(t['visits_count']) if t else 0}%\nСумма чека (товары через запятую) или кнопка:",btn+cancel()+back())
def cashback_cmd(uid,text):
    p=text.split()
    if len(p)<3: return rep(f"{MONEY} Формат: /cashback 500 COFFEE... [товары,через,запятую]",back())
    if not is_float(p[1]): return rep(f"{MONEY} Неверная сумма",back())
    amount=float(p[1])
    if amount<=0: return rep(f"{MONEY} Сумма > 0",back())
    t=find_user(p[2])
    if not t: return rep(f"{SEARCH} не найден",back())
    items=[x.strip().lower() for x in " ".join(p[3:]).split(",") if x.strip()]
    return apply_cashback(t,amount,items)

def handle_onboard(uid,text,name=""):
    ob=ONBOARD.get(uid); t=text.strip()
    if ob["step"]=="phone":
        if "пропустить" in t.lower() or t in ("-","нет"):
            ONBOARD.set(uid,{"step":"bday"}); return rep(f"{CAKE} Теперь дата рождения: 15.05 (или «пропустить»):",cancel())
        d=norm_phone(t)
        if d:
            with db() as c:
                if c.execute("SELECT 1 FROM users WHERE phone=? AND max_user_id!=?",(d,uid)).fetchone():
                    return rep(f"{WARN} Номер уже привязан к другой карте. Другой или «пропустить».",cancel())
                c.execute("UPDATE users SET phone=?,name_lc=name_lc WHERE max_user_id=?",(d,uid))
            ONBOARD.set(uid,{"step":"bday"}); return rep(f"{PHONE} Сохранено!\n{CAKE} Дата рождения: 15.05 (или «пропустить»):",cancel())
        return rep(f"{WARN} Пример: 79991234567 (или «пропустить»)",cancel())
    if ob["step"]=="bday":
        if "пропустить" in t.lower() or t in ("-","нет"):
            ONBOARD.clear(uid); return menu(uid,name)
        r=None
        for tok in t.split():
            r=parse_bday(tok)
            if r: break
        if not r: return rep(f"{WARN} Формат: 15.05 (или «пропустить»)",cancel())
        dd,mm=r
        with db() as c: c.execute("UPDATE users SET birthday=? WHERE max_user_id=?",(f"{dd:02d}.{mm:02d}",uid))
        ONBOARD.clear(uid); return menu(uid,name)
    ONBOARD.clear(uid); return menu(uid,name)

def handle_message(uid,text,name,payload="",photo=None):
    uid=str(uid); t=text.strip(); p=t.split(); cmd=t.lower()
    if name:
        with db() as c: c.execute("UPDATE users SET full_name=?,name_lc=? WHERE max_user_id=? AND (full_name IS NULL OR full_name='')",(name,(name or "").lower(),uid))
    if payload=="show_card": return card(ensure_user(uid,name,WELCOME if not is_priv(uid) else 0))
    if payload.startswith("ref_"):
        if not user_exists(uid): ensure_user(uid,name,WELCOME)
        return do_refer(uid,payload[4:])
    if cmd in ("/start","/help"):
        if cmd=="/start":
            for P in (PENDING,PENDING_CASH,PENDING_ID,PENDING_PAYID,PENDING_PAY,PENDING_CHECK,PENDING_SEARCH,PENDING_REVIEW): P.clear(uid)
        ONBOARD.clear(uid); return menu(uid,name)
    ob=ONBOARD.get(uid)
    if ob and not is_priv(uid):
        if t.lower() in ("отмена","cancel","/cancel"):
            ONBOARD.clear(uid); return rep(f"{CROSS} Отменено.",back())
        return handle_onboard(uid,t,name)
    if PENDING_REVIEW.get(uid):
        PENDING_REVIEW.clear(uid)
        return submit_review(uid,photo)
    if is_priv(uid) and p:
        op=p[0]
        if t.lower() in ("отмена","cancel","/cancel","/menu"):
            for P in (PENDING,PENDING_CASH,PENDING_ID,PENDING_PAYID,PENDING_PAY,PENDING_CHECK,PENDING_SEARCH): P.clear(uid)
            if t.lower()=="/menu": return menu(uid,name)
            return rep(f"{CROSS} Действие отменено.",back())
        if PENDING_SEARCH.get(uid) and not op.startswith("/"):
            PENDING_SEARCH.clear(uid); return do_search(uid,t)
        if PENDING_ID.get(uid):
            target=find_user(op)
            if target:
                PENDING_ID.clear(uid); PENDING_CASH.set(uid,target["card_number"])
                return cash_amount_prompt(uid,target["card_number"],target)
            return rep(f"{SEARCH} «{op}» не найден. Телефон или карта?",cancel()+back())
        if PENDING_PAYID.get(uid):
            target=find_user(op)
            if target:
                PENDING_PAYID.clear(uid); PENDING_PAY.set(uid,{"card":target["card_number"],"amount":None})
                return rep(f"{USER} {target['full_name'] or target['card_number']} · {CARD} {target['card_number']} · {STAR} {balance(target['id'])}\nСумма покупки:",cancel()+back())
            return rep(f"{SEARCH} не найден. Телефон или карта?",cancel()+back())
        pay=PENDING_PAY.get(uid)
        if pay is not None:
            card_no=pay["card"]; amt=pay.get("amount")
            target=find_user(card_no)
            if not target:
                PENDING_PAY.clear(uid); return rep(f"{WARN} Клиент не найден.",back())
            bal=balance(target["id"])
            if amt is None:
                amount=None
                for tok in p:
                    if is_float(tok): amount=float(tok); break
                if amount is None or amount<=0: return rep(f"{WARN} Введите сумму чека числом, например: 500",cancel()+back())
                maxpay=min(bal,int(amount*MAX_PAY/100))
                PENDING_PAY.set(uid,{"card":card_no,"amount":amount})
                btn=[[cb(f"{MINUS} {maxpay}",f"deduct_{maxpay}_{card_no}")]] if maxpay>0 else []
                return rep(f"{RECEIPT} Чек: {amount:.0f} р.\n{STAR} Баланс: {bal}\nМожно списать до {maxpay} баллов ({MAX_PAY}%).\nНажмите кнопку или введите число / max:",btn+cancel()+back())
            amount=float(amt); cap=min(bal,int(amount*MAX_PAY/100))
            if op.lower()=="max": deduct=cap
            elif op.isdigit(): deduct=int(op)
            else: return rep(f"{THINK} Число или max.",cancel()+back())
            if deduct<=0 or deduct>cap: return rep(f"{WARN} Можно 1..{cap}",cancel()+back())
            ok,nb=spend_points(target["id"],deduct,f"{CARD} Оплата баллами")
            PENDING_PAY.clear(uid)
            return rep(f"{OK} Списано {deduct}\nОстаток: {STAR} {nb}",back()) if ok else rep(f"{WARN} Не хватило баллов",back())
        chk=PENDING_CHECK.get(uid)
        if chk is not None and chk.get("card") is None:
            target=find_user(op)
            if target:
                chk["card"]=target["card_number"]; PENDING_CHECK.set(uid,chk)
                return check_prompt_amount(uid,target["card_number"],target)
            return rep(f"{SEARCH} не найден.",cancel()+back())
        if chk is not None and chk.get("card") and chk.get("amount") is None:
            amount=None
            for tok in p:
                if is_float(tok): amount=float(tok); break
            if amount is None or amount<=0: return rep(f"{WARN} Введите сумму чека числом.",cancel()+back())
            items=[]
            for tok in p:
                if is_float(tok): continue
                items+=[x.strip().lower() for x in tok.split(",") if x.strip()]
            chk["amount"]=amount; chk["items"]=items; PENDING_CHECK.set(uid,chk)
            return check_confirm(uid,chk["card"],amount,items)
        if len(op)>1 and op[0] in "+-" and op[1:].isdigit():
            delta=int(op)
            if delta!=0:
                target=None
                if len(p)>=2:
                    target=find_user(p[1])
                    if not target: return rep(f"{SEARCH} «{p[1]}» не найден.",back())
                else:
                    cn=PENDING.get(uid)
                    if cn: target=find_user(cn)
                if target: return apply_delta(uid,delta,target," ".join(p[2:]))
                return rep(f"{THINK} Укажите: {op} COFFEE... или кнопка в карточке",back())
        elif is_float(op):
            amount=float(op); cn=PENDING_CASH.get(uid)
            if cn:
                if amount<=0: return rep(f"{WARN} Сумма чека должна быть > 0.",cancel()+back())
                target=find_user(cn)
                if target:
                    PENDING_CASH.clear(uid)
                    items=[x.strip().lower() for x in " ".join(p[1:]).split(",") if x.strip()]
                    return apply_cashback(target,amount,items)
            return rep(f"{THINK} Сначала выберите клиента (кнопка Кешбэк)",back())
        if op=="?" and len(p)>=2:
            target=find_user(p[1])
            return admin_card(target) if target else rep(f"{SEARCH} не найден",back())
        if cmd.startswith("/cashback"): return cashback_cmd(uid,t)
        if cmd.startswith("/promo_stop") and len(p)>=2: return promo_stop(p[1])
        if cmd.startswith("/promo") and len(p)>=3 and p[2].isdigit():
            return promo_create(p[1],int(p[2]))
        if cmd=="/broadcast": return do_broadcast(t.split(maxsplit=1)[1] if len(p)>1 else "",uid)
        if cmd=="/files": return do_export_files()
        if cmd=="/status": return do_status(uid)
        if cmd=="/abc": return do_abc(uid)
        if cmd=="/rfm": return do_rfm(uid)
        if cmd.startswith("/clients"):
            page=int(p[1])-1 if len(p)>1 and p[1].isdigit() else 0
            return clients(uid,page)
        if cmd.startswith("/find"): return do_search(uid,t[5:].strip())
        if cmd=="/export": return do_export(uid)
        if cmd=="/top": return do_top(uid)
        if cmd=="/insights": return do_insights(uid)
    u=ensure_user(uid,name)
    if cmd=="/card": return card(u)
    if cmd=="/balance":
        ex=expiring_soon(u["id"]); msg=f"{STAR} Баланс: {balance(u['id'])} баллов."
        if ex: msg+=f"\n{WARN} {ex} сгорят за {WARN_DAYS} дн.!"
        return rep(msg,back())
    if cmd=="/history": return hist(u)
    if cmd.startswith("/phone"): return set_phone(uid,t)
    if cmd.startswith("/bday"): return set_bday(uid,t)
    if cmd.startswith("/ref"): return do_refer(uid,p[1] if len(p)>1 else "")
    if cmd.startswith("/review"): return review_screen(u)
    if cmd.startswith("/promo"): return promo_redeem(uid,p[1] if len(p)>1 else "")
    hint=f"{THINK} Не понял. /help - команды."
    if is_priv(uid): hint=f"{TOOLS} Персонал:\n{RECEIPT} Чек · {SEARCH} Поиск\n/find 7999 · /top · /abc · /rfm · /status"
    elif not u["phone"]: hint+=f"\n{PHONE} /phone · {CAKE} /bday · {TICKET} /promo · {HAND} /ref · {STAR} /review"
    return rep(hint,back())

def handle_callback(uid,payload,name):
    uid=str(uid); u=ensure_user(uid,name)
    PRIV=("cashflow","payflow","show_search","show_top","show_abc","show_rfm","show_status","checkflow")
    if payload in PRIV or payload.startswith(("add_","sub_","input_","cash_","pay_","sp:","deduct_","rcc_","rcp_","qa_","sel_","buy_","ck_","chk_","ckd_","ckn_")):
        if not is_priv(uid): return rep(f"{NO} Только персонал.",back())
    if payload in ("show_clients","export_csv","export_files","show_insights","show_broadcast") or payload.startswith(("cp:","review_ok_","review_no_")):
        if uid not in ADMINS: return rep(f"{NO} Только админ.",back())
    if payload=="show_menu": return menu(uid,name)
    if payload=="show_help": return help_screen(u)
    if payload=="show_card": return card(u)
    if payload=="show_balance": return handle_message(uid,"/balance",name)
    if payload=="show_history": return hist(u)
    if payload=="show_badges": return badges_screen(u)
    if payload=="show_refer": return refer_screen(u)
    if payload=="show_review": return review_screen(u)
    if payload=="show_qr": return show_qr(uid,name)
    if payload=="show_status": return do_status(uid)
    if payload=="show_abc": return do_abc(uid)
    if payload=="show_rfm": return do_rfm(uid)
    if payload=="show_clients": return clients(uid)
    if payload=="show_search":
        PENDING_SEARCH.set(uid,"1"); return do_search(uid,"")
    if payload=="show_top": return do_top(uid)
    if payload=="show_insights": return do_insights(uid)
    if payload=="show_broadcast": return rep(f"{MEGA} Рассылка\n/broadcast [all|active|sleep] текст\n\nall - всем\nactive - были за 30 дн\nsleep - уснувшие",back())
    if payload=="export_csv": return do_export(uid)
    if payload=="export_files": return do_export_files()
    if payload.startswith("review_ok_"):
        ru=payload[len("review_ok_"):]
        with db() as c:
            row=c.execute("SELECT id FROM users WHERE max_user_id=?",(ru,)).fetchone()
            if row:
                _batch(c,row["id"],REVIEW_BONUS,"review",STAR+" За отзыв")
                c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(row["id"],"accrual",REVIEW_BONUS,STAR+" За отзыв"))
                c.execute("UPDATE review_requests SET status='ok' WHERE user_id=?",(row["id"],))
        send_text(int(ru),f"{PARTY} Отзыв подтверждён! +{REVIEW_BONUS} баллов {STAR}")
        return rep(f"{OK} Начислено {REVIEW_BONUS}.",back())
    if payload.startswith("review_no_"):
        ru=payload[len("review_no_"):]
        send_text(int(ru),f"{WARN} Пока не можем начислить баллы за отзыв. Убедитесь, что он опубликован.")
        return rep(f"{OK} Отклонено.",back())
    if payload.startswith("sel_"):
        target=find_user(payload[4:])
        return admin_card(target) if target else rep(f"{WARN} Не найден.",back())
    if payload.startswith("buy_"):
        target=find_user(payload[4:])
        if not target: return rep(f"{WARN} Не найден.",back())
        buys=purchases_of(target["id"],10)
        if not buys: return rep(f"{BAG} Покупок пока нет.",back())
        return rep(f"{BAG} {target['full_name'] or target['card_number']}:\n"+"\n".join(f"· {b['amount']:.0f} р. - {b['items']}" for b in buys),back())
    if payload=="checkflow":
        PENDING_CHECK.set(uid,{"card":None,"amount":None,"items":None})
        return rep(f"{RECEIPT} Чек\nВыберите клиента или введите телефон/карту/имя:",recent_buttons("ck")+cancel()+back())
    if payload.startswith("chk_") or payload.startswith("ck_"):
        cn=payload[4:] if payload.startswith("chk_") else payload[3:]
        PENDING_CHECK.set(uid,{"card":cn,"amount":None,"items":None}); return check_prompt_amount(uid,cn,find_user(cn))
    if payload.startswith("ckd_") or payload.startswith("ckn_"):
        if payload.startswith("ckd_"):
            parts=payload.split("_",2)
            try: deduct=int(parts[1])
            except ValueError: deduct=0
            cn=parts[2]
        else:
            deduct=0; cn=payload[4:]
        chk=PENDING_CHECK.get(uid) or {}
        if not chk.get("amount"): return rep(f"{WARN} Сначала сумма.",back())
        return check_finalize(uid,cn,chk["amount"],chk.get("items"),deduct)
    if payload.startswith("cashflow"):
        PENDING_ID.set(uid,"1")
        return rep(f"{MONEY} Кешбэк\nВыберите клиента или введите телефон/карту/имя:",recent_buttons("rcc")+cancel()+back())
    if payload.startswith("payflow"):
        PENDING_PAYID.set(uid,"1")
        return rep(f"{CARD} Оплата баллами\nВыберите клиента или введите телефон/карту/имя:",recent_buttons("rcp")+cancel()+back())
    if payload=="cancel_pending":
        for P in (PENDING,PENDING_CASH,PENDING_ID,PENDING_PAYID,PENDING_PAY,ONBOARD,PENDING_CHECK,PENDING_SEARCH,PENDING_REVIEW): P.clear(uid)
        return rep(f"{CROSS} Отменено.",back())
    if payload.startswith("rcc_"):
        PENDING_ID.clear(uid); cn=payload[4:]; PENDING_CASH.set(uid,cn); return cash_amount_prompt(uid,cn,find_user(cn))
    if payload.startswith("rcp_"):
        PENDING_PAYID.clear(uid); cn=payload[4:]; PENDING_PAY.set(uid,{"card":cn,"amount":None}); t=find_user(cn)
        return rep(f"{USER} {(t['full_name'] or t['card_number']) if t else cn} · {STAR} {balance(t['id']) if t else 0}\nСумма покупки:",cancel()+back())
    if payload.startswith("qa_"):
        parts=payload.split("_",2); target=find_user(parts[2])
        if target:
            PENDING_ID.clear(uid); PENDING_CASH.clear(uid); return apply_cashback(target,int(parts[1]))
    if payload.startswith("cp:"): return clients(uid,int(payload.split(":",1)[1]))
    if payload.startswith("sp:"):
        parts=payload.split(":",2); return do_search(uid,parts[2] if len(parts)>2 else "",int(parts[1]))
    if payload.startswith("deduct_"):
        parts=payload.split("_",2)
        try: amount=int(parts[1])
        except ValueError: return rep(f"{WARN} Ошибка суммы.",back())
        target=find_user(parts[2])
        if not target: return rep(f"{WARN} Клиент не найден.",back())
        ok,nb=spend_points(target["id"],amount,f"{CARD} Оплата баллами")
        PENDING_PAY.clear(uid)
        return rep(f"{OK} Списано {amount}\nОстаток: {STAR} {nb}",back()) if ok else rep(f"{WARN} Не хватило баллов",back())
    if payload.startswith("add_") or payload.startswith("sub_"):
        parts=payload.split("_",2); target=find_user(parts[2])
        if target: return apply_delta(uid,int(parts[1]) if payload.startswith("add_") else -int(parts[1]),target)
    if payload.startswith("input_"):
        cn=payload[6:]; PENDING.set(uid,cn); return rep(f"{CARD} {cn}\nНапишите: +50 или -100",cancel()+back())
    if payload.startswith("cash_"):
        PENDING_ID.clear(uid); cn=payload[5:]; PENDING_CASH.set(uid,cn); return cash_amount_prompt(uid,cn,find_user(cn))
    if payload.startswith("pay_"):
        PENDING_PAYID.clear(uid); cn=payload[4:]; PENDING_PAY.set(uid,{"card":cn,"amount":None}); t=find_user(cn)
        return rep(f"{USER} {(t['full_name'] or t['card_number']) if t else cn} · {STAR} {balance(t['id']) if t else 0}\nСумма покупки:",cancel()+back())
    return rep(f"{THINK} Неизвестно.",back())

def expire_loop():
    while True:
        try:
            now=datetime.now()
            with db() as c:
                for b in c.execute("SELECT id,user_id,points_left FROM points_batches WHERE expires_at<=? AND points_left>0",(now,)):
                    c.execute("UPDATE points_batches SET points_left=0 WHERE id=?",(b["id"],))
                    c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(b["user_id"],"expired",-b["points_left"],HOUR+" Сгорание"))
            with db() as c:
                users=c.execute("SELECT u.id,u.max_user_id,u.last_notify,u.birthday,u.bday_year,u.full_name FROM users u "
                                "WHERE u.birthday!='' OR EXISTS(SELECT 1 FROM points_batches b WHERE b.user_id=u.id AND b.points_left>0 AND b.expires_at<=?)",
                                (now+timedelta(days=WARN_DAYS),)).fetchall()
            for r in users:
                if r["birthday"]:
                    ddmm=parse_bday(r["birthday"])
                    if ddmm and ddmm[0]==now.day and ddmm[1]==now.month and r["bday_year"]!=now.year:
                        with db() as c:
                            _batch(c,r["id"],BDAY_BONUS,"birthday",GIFT+" Бонус ко дню рождения",BDAY_DAYS)
                            c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(r["id"],"accrual",BDAY_BONUS,CAKE+" Бонус ко дню рождения"))
                            c.execute("UPDATE users SET bday_year=? WHERE id=?",(now.year,r["id"]))
                        send_text(int(r["max_user_id"]),f"{PARTY} {r['full_name'] or 'Друг'}, с днём рождения!\n{GIFT} Дарим {BDAY_BONUS} баллов - потратьте за {BDAY_DAYS} дн. {CUP}")
                if r["last_notify"]:
                    try:
                        if (now-datetime.fromisoformat(r["last_notify"])).days<3: continue
                    except ValueError: pass
                ex=expiring_soon(r["id"])
                if ex>0:
                    if send_text(int(r["max_user_id"]),f"{WARN} {ex} баллов сгорят за {WARN_DAYS} дн. - загляните! {CUP}"):
                        with db() as c: c.execute("UPDATE users SET last_notify=? WHERE id=?",(now.isoformat(),r["id"]))
                    time.sleep(0.6)
            wb_cut=(now-timedelta(days=WINBACK_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            cd_cut=(now-timedelta(days=WINBACK_CD)).strftime("%Y-%m-%d %H:%M:%S")
            with db() as c:
                wb=c.execute("SELECT id,max_user_id,full_name FROM users WHERE (last_winback IS NULL OR last_winback='' OR last_winback<?) AND (last_visit IS NULL OR last_visit<?) AND created_at<?",(cd_cut,wb_cut,wb_cut)).fetchall()
            for r in wb:
                with db() as c:
                    _batch(c,r["id"],WINBACK_BONUS,"winback",HAND+" Мы скучали",7)
                    c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(r["id"],"accrual",WINBACK_BONUS,HAND+" Мы скучали"))
                    c.execute("UPDATE users SET last_winback=? WHERE id=?",(now.strftime("%Y-%m-%d %H:%M:%S"),r["id"]))
                send_text(int(r["max_user_id"]),f"{HAND} {r['full_name'] or 'Друг'}, мы скучаем! Вас давно не было.\n{GIFT} Дарим {WINBACK_BONUS} баллов - сгорят через 7 дн. Загляните! {CUP}")
                time.sleep(0.6)
        except Exception as e: log.error("[expire] %s",e)
        time.sleep(3600)

def process_update(d,src="hook"):
    m=d.get("marker")
    if src=="poll" and m is not None:
        try:
            if int(m)<=int(kv_get("last_marker","0")): return
        except ValueError: pass
    key=m if m is not None else (d.get("update_type"),d.get("timestamp"),_sender(d).get("user_id"),((d.get("message") or {}).get("body") or {}).get("text",""))
    if DEDUP.seen(key):
        log.info("[skip] dedup %s",key); return
    try:
        if d.get("update_type")=="message_callback":
            u=_sender(d); uid=u.get("user_id") or ((d.get("message") or {}).get("recipient") or {}).get("user_id")
            payload=(d.get("callback") or {}).get("payload") or d.get("payload") or ""
            if uid and payload:
                log.info("[+] callback %s: %s",uid,payload)
                r=handle_callback(uid,payload,u.get("first_name",""))
                if r:
                    if r["buttons"]: send_buttons(int(uid),r["text"],r["buttons"])
                    else: send_text(int(uid),r["text"])
            return
        inc=parse_incoming(d)
        if not inc: return
        log.info("[+] %s: %r",inc["uid"],inc["text"])
        r=handle_message(str(inc["uid"]),inc["text"],inc["name"],inc.get("payload",""),inc.get("photo"))
        if r:
            if r["buttons"]: send_buttons(inc["uid"],r["text"],r["buttons"])
            else: send_text(inc["uid"],r["text"])
    finally:
        if src=="poll" and m is not None: kv_set("last_marker",str(m))
def poller_loop():
    log.info("[main] Long Polling")
    fail=0
    while True:
        ups=get_updates()
        if ups is None:
            fail+=1
            if fail==5: alert_admins(f"{WARN} Нет связи с MAX API. Бот продолжает пытаться.")
            time.sleep(3); continue
        if fail>=5: alert_admins(f"{OK} Связь с MAX восстановлена.")
        fail=0
        try:
            for d in ups: process_update(d,"poll")
        except Exception as e: log.error("[poller] %s",e)
        time.sleep(2)

_started=False
@asynccontextmanager
async def lifespan(app):
    global _started
    init_db(); migrate()
    if not _started:
        _started=True
        if WEBHOOK_URL:
            try:
                setup_webhook()
            except Exception as e:
                log.error("[webhook] %s -> polling",e)
                threading.Thread(target=poller_loop,daemon=True).start()
        else:
            threading.Thread(target=poller_loop,daemon=True).start()
        threading.Thread(target=expire_loop,daemon=True).start()
        threading.Thread(target=backup_loop,daemon=True).start()
        threading.Thread(target=lambda:alert_admins(f"{OK} Бот запущен."),daemon=True).start()
    yield
app=FastAPI(lifespan=lifespan)
@app.get("/assets/{name}")
def assets(name:str):
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),"site",name)
    if os.path.isfile(p): return FileResponse(p)
    raise HTTPException(404,"Not found")
@app.get("/api/card")
def api_card(phone:str="", x_api_key: str = Header(default="")):
    # Защита: проверяем секретный ключ из заголовка
    site_key = os.getenv("SITE_API_KEY", "")
    if site_key and x_api_key != site_key:
        raise HTTPException(403, "Forbidden")
    
    d="".join(ch for ch in phone if ch.isdigit())
    if len(d)<4: return {"ok":False}
    with db() as c:
        r=c.execute("SELECT id,visits_count FROM users WHERE phone LIKE ?",(f"%{d[-10:]}",)).fetchone()
        if not r: return {"ok":False}
        bal=balance(r["id"]); v=r["visits_count"]
    return {"ok":True,"points":bal,"visits":v,"level":lvl_name(v),"pct":pct(v)}
@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/",response_class=HTMLResponse)
def index():
    p=os.path.join(os.path.dirname(os.path.abspath(__file__)),"site","index.html")
    try:
        with open(p,encoding="utf-8") as f: return f.read()
    except OSError:
        return "<h1>Утро ☕ сайт скоро откроется</h1>"
@app.post("/max/webhook")
async def webhook(request:Request,x_max_bot_api_secret:str|None=Header(default=None)):
    if WEBHOOK_SEC and x_max_bot_api_secret!=WEBHOOK_SEC: raise HTTPException(401,"Bad signature")
    try: d=await request.json()
    except Exception: raise HTTPException(400,"Bad JSON")
    log.debug("[webhook] in: %s marker=%s",d.get("update_type"),d.get("marker"))
    await asyncio.to_thread(process_update,d)
    return {"ok":True}

def make_table_qr():
    try: me=http.get(f"{API}/me",headers=H,timeout=10).json()
    except Exception as e: print("API /me недоступен:",e); return
    uname=me.get("username") or str(me.get("user_id",""))
    qrcode.make(f"https://max.ru/{uname}?payload=show_card").save("table_qr.png")
    print("QR сохранён: table_qr.png")
def self_test():
    assert norm_phone("+7 999 123-45-67")=="79991234567"
    assert norm_phone("89991234567")=="79991234567"
    assert norm_phone("9991234567")=="79991234567"
    assert pct(0)==3 and pct(10)==5 and pct(30)==7 and pct(60)==10
    assert progress_bar(5).endswith("5/10")
    assert is_float("500") and not is_float("abc")
    assert "алексей" in "Алексей".lower()
    print("SELF-TEST OK")
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="qr": make_table_qr()
    elif len(sys.argv)>1 and sys.argv[1]=="test": self_test()
    else: uvicorn.run(app,host="127.0.0.1",port=8000)
