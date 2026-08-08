# -*- coding: utf-8 -*-
"""РљРѕС„РµР№РЅС‹Р№ Р±РѕРЅСѓСЃРЅС‹Р№ Р±РѕС‚ РґР»СЏ MAX.
Р­РјРѕРґР·Рё Р·Р°РґР°РЅС‹ ASCII-СЌСЃРєРµР№РїР°РјРё - РЅРµ Р·Р°РІРёСЃСЏС‚ РѕС‚ РєРѕРґРёСЂРѕРІРєРё С„Р°Р№Р»Р°.
python3 main.py      - СЃРµСЂРІРµСЂ
python3 main.py qr   - QR РґР»СЏ СЃС‚РѕР»РѕРІ
"""
import asyncio, csv, io, logging, os, sqlite3, sys, threading, time, uuid
from collections import OrderedDict
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta

import qrcode, requests, uvicorn, urllib3
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

load_dotenv()
log = logging.getLogger("coffee_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
try: sys.stdout.reconfigure(line_buffering=True)
except Exception: pass

# ---- СЌРјРѕРґР·Рё РєР°Рє ASCII-СЌСЃРєРµР№РїС‹ (РїРµСЂРµР¶РёРІСѓС‚ Р»СЋР±СѓСЋ РєРѕРґРёСЂРѕРІРєСѓ) ----
CUP = "?"; WAVE = "??"; CARD = "??"; STAR = "?"; HIST = "??"; HELP = "?"
USERS = "??"; SEARCH = "??"; EXPORT = "??"; BACK = "??"; RIGHT = "??"
PLUS = "?"; MINUS = "?"; EDIT = "??"; CROSS = "?"; PARTY = "??"
WARN = "??"; PHONE = "??"; USER = "??"; CHART = "??"; RECEIPT = "??"
THINK = "??"; TOOLS = "???"; GIFT = "??"; MONEY = "??"; NO = "??"
OK = "?"; HOUR = "?"; BRONZE = "??"; SILVER = "??"; GOLD = "??"; DIAM = "??"
BAG = "??"; BULB = "??"; CHART2 = "??"; CAKE = "??"
MEDAL = "??"; HAND = "??"; MEGA = "??"; TICKET = "???"
PB_F = "?"; PB_E = "?"

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
if not TOKEN: log.error("MAX_BOT_TOKEN РЅРµ Р·Р°РґР°РЅ!")
def is_priv(u): return u in ADMINS or u in STAFF

LEVELS=[(0,BRONZE+" РќРѕРІРёС‡РѕРє",3),(10,SILVER+" РџРѕСЃС‚РѕСЏР»РµС†",5),(30,GOLD+" Р—Р°РІСЃРµРіРґР°С‚Р°Р№",7),(60,DIAM+" VIP",10)]
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
    if not nl: return f"{DIAM} РњР°РєСЃРёРјСѓРј!"
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
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,max_user_id TEXT UNIQUE NOT NULL,full_name TEXT,phone TEXT,card_number TEXT UNIQUE NOT NULL,visits_count INTEGER DEFAULT 0,total_spent REAL DEFAULT 0,level INTEGER DEFAULT 0,is_admin INTEGER DEFAULT 0,last_notify TEXT DEFAULT '',birthday TEXT DEFAULT '',bday_year INTEGER DEFAULT 0,referred_by TEXT DEFAULT '',ref_done INTEGER DEFAULT 0,last_winback TEXT DEFAULT '',last_visit TIMESTAMP,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS points_batches(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,points_left INTEGER NOT NULL,original_points INTEGER NOT NULL,source TEXT,comment TEXT,expires_at TIMESTAMP NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,type TEXT NOT NULL,points INTEGER NOT NULL,comment TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,amount REAL,item TEXT,receipt_id TEXT DEFAULT '',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY,points INTEGER,active INTEGER DEFAULT 1,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS promo_use(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,code TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS i_card ON users(card_number);CREATE INDEX IF NOT EXISTS i_phone ON users(phone);CREATE INDEX IF NOT EXISTS i_bu ON points_batches(user_id);CREATE INDEX IF NOT EXISTS i_be ON points_batches(expires_at);"""
def init_db():
    with db() as c: c.executescript(SCHEMA)
def migrate():
    with db() as c:
        cols=[r[1] for r in c.execute("PRAGMA table_info(users)")]
        for col,ddl in [("birthday","TEXT DEFAULT ''"),("bday_year","INTEGER DEFAULT 0"),("last_visit","TIMESTAMP"),("referred_by","TEXT DEFAULT ''"),("ref_done","INTEGER DEFAULT 0"),("last_winback","TEXT DEFAULT ''")]:
            if col not in cols: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        pcols=[r[1] for r in c.execute("PRAGMA table_info(purchases)")]
        if "receipt_id" not in pcols: c.execute("ALTER TABLE purchases ADD COLUMN receipt_id TEXT DEFAULT ''")
        for r in c.execute("SELECT id,phone FROM users WHERE phone IS NOT NULL AND phone!=''"):
            np=norm_phone(r["phone"])
            if np and np!=r["phone"]: c.execute("UPDATE users SET phone=? WHERE id=?",(np,r["id"]))

def user_exists(uid):
    with db() as c: return c.execute("SELECT 1 FROM users WHERE max_user_id=?",(uid,)).fetchone() is not None
def ensure_user(uid,name="",welcome=0):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(max_user_id,full_name,card_number,is_admin) VALUES(?,?,?,?)",(uid,name,"COFFEE"+uuid.uuid4().hex[:8].upper(),int(uid in ADMINS)))
        if name: c.execute("UPDATE users SET full_name=? WHERE max_user_id=? AND (full_name IS NULL OR full_name='')",(name,uid))
        row=c.execute("SELECT * FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if welcome>0 and not c.execute("SELECT 1 FROM transactions WHERE user_id=? AND type='welcome'",(row["id"],)).fetchone():
            _batch(c,row["id"],welcome,"welcome",GIFT+" РџСЂРёРІРµС‚СЃС‚РІРµРЅРЅС‹Р№ Р±РѕРЅСѓСЃ")
            c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(row["id"],"welcome",welcome,GIFT+" РџСЂРёРІРµС‚СЃС‚РІРµРЅРЅС‹Р№ Р±РѕРЅСѓСЃ"))
        return dict(row)
def _batch(c,uid,points,source,comment="",days=None):
    c.execute("INSERT INTO points_batches(user_id,points_left,original_points,source,comment,expires_at) VALUES(?,?,?,?,?,?)",(uid,points,points,source,comment,datetime.now()+timedelta(days=days or EXPIRE_DAYS)))
def balance(uid):
    with db() as c: return int(c.execute("SELECT COALESCE(SUM(points_left),0) b FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>?",(uid,datetime.now())).fetchone()["b"])
def expiring_soon(uid):
    with db() as c: return int(c.execute("SELECT COALESCE(SUM(points_left),0) b FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>? AND expires_at<=?",(uid,datetime.now(),datetime.now()+timedelta(days=WARN_DAYS))).fetchone()["b"])
def add_points(uid,points,source,comment=""):
    with db() as c:
        _batch(c,uid,points,source,comment); c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(uid,"accrual",points,comment or source))
def spend_points(uid,points,comment=""):
    if points<=0: return False,balance(uid)
    with db() as c:
        bal=int(c.execute("SELECT COALESCE(SUM(points_left),0) b FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>?",(uid,datetime.now())).fetchone()["b"])
        if points>bal: return False,bal
        left=points
        for b in c.execute("SELECT id,points_left FROM points_batches WHERE user_id=? AND points_left>0 AND expires_at>? ORDER BY expires_at",(uid,datetime.now())):
            if left<=0: break
            t=min(left,b["points_left"]); c.execute("UPDATE points_batches SET points_left=points_left-? WHERE id=?",(t,b["id"])); left-=t
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(uid,"writeoff",-points,comment or CARD+" РЎРїРёСЃР°РЅРёРµ"))
        return True,bal-points
def add_visit(uid):
    with db() as c:
        c.execute("UPDATE users SET visits_count=visits_count+1,last_visit=? WHERE id=?",(datetime.now(),uid))
        u=c.execute("SELECT visits_count,level FROM users WHERE id=?",(uid,)).fetchone()
        nl=max((i for i,(n,_,_) in enumerate(LEVELS) if u["visits_count"]>=n),default=0)
        up=nl!=u["level"]
        if up: c.execute("UPDATE users SET level=? WHERE id=?",(nl,uid))
        return u["visits_count"],up
def find_user(q):
    qo=q.strip(); q=qo.lower()
    with db() as c:
        r=c.execute("SELECT * FROM users WHERE LOWER(card_number)=? OR max_user_id=?",(q,qo)).fetchone()
        if r: return dict(r)
        d="".join(ch for ch in q if ch.isdigit())[-10:]
        if len(d)>=10:
            r=c.execute("SELECT * FROM users WHERE phone LIKE ?",(f"%{d}",)).fetchone()
            if r: return dict(r)
        r=c.execute("SELECT * FROM users WHERE LOWER(full_name) LIKE ?",(f"%{q}",)).fetchone()
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
            cond="phone LIKE ? OR phone LIKE ?"; arg=(f"%{v1}%",f"%{v2}%")
        elif q.startswith("coffee"):
            cond="LOWER(card_number) LIKE ?"; arg=(f"%{q}%",)
        else:
            cond="LOWER(full_name) LIKE ?"; arg=(f"%{q}%",)
        total=c.execute(f"SELECT COUNT(*) FROM users WHERE {cond}",arg).fetchone()[0]
        rows=[dict(r) for r in c.execute(f"SELECT * FROM users WHERE {cond} ORDER BY created_at DESC LIMIT 10 OFFSET ?",arg+(page*10,))]
    return rows,total
def export_csv():
    with db() as c:
        rows=c.execute("SELECT u.*, COALESCE((SELECT SUM(b.points_left) FROM points_batches b WHERE b.user_id=u.id AND b.points_left>0 AND b.expires_at>?),0) bal FROM users u ORDER BY created_at DESC",(datetime.now(),)).fetchall()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["ID","MAX ID","РРјСЏ","РўРµР»РµС„РѕРЅ","РљР°СЂС‚Р°","РџРѕСЃРµС‰РµРЅРёР№","РџРѕС‚СЂР°С‡РµРЅРѕ","Р‘Р°Р»Р»С‹","Р”Р ","Р РµРіРёСЃС‚СЂР°С†РёСЏ"])
    for r in rows: w.writerow([r["id"],r["max_user_id"],r["full_name"] or "",r["phone"] or "",r["card_number"],r["visits_count"],f"{r['total_spent']:.0f}",int(r["bal"]),r["birthday"],r["created_at"]])
    return out.getvalue()

def send_text(uid,text):
    try:
        r=http.post(f"{API}/messages",params={"user_id":uid},json={"text":text},headers=H,timeout=10)
        if r.status_code!=200: log.error("[MAX] %s %s",r.status_code,r.text[:200]); return False
        return True
    except Exception as e: log.error("[MAX] %s",e); return False
def send_buttons(uid,text,buttons):
    try:
        r=http.post(f"{API}/messages",params={"user_id":uid},json={"text":text,"attachments":[{"type":"inline_keyboard","payload":{"buttons":buttons}}]},headers=H,timeout=10)
        if r.status_code!=200: log.error("[MAX] %s %s",r.status_code,r.text[:200]); return False
        return True
    except Exception as e: log.error("[MAX] %s",e); return False
def setup_webhook():
    r=http.post(f"{API}/subscriptions",headers=H,timeout=10,json={"url":WEBHOOK_URL,"secret":WEBHOOK_SEC,"update_types":["message_created","bot_started","message_callback"]})
    if r.status_code!=200: raise RuntimeError(f"Webhook РЅРµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅ: {r.status_code}")
    log.info("[MAX] webhook OK")
def get_updates():
    try:
        r=http.get(API+"/updates",params={"types":"message_created,bot_started,message_callback"},headers=H,timeout=25)
        if r.status_code!=200: log.error("[MAX] %s %s",r.status_code,r.text[:200]); return []
        d=r.json(); return d if isinstance(d,list) else d.get("updates",[])
    except Exception as e: log.error("[MAX] %s",e); return []
def _sender(d): return d.get("user") or d.get("sender") or {}
def parse_incoming(d):
    if d.get("update_type") not in ("message_created","bot_started"): return None
    u=_sender(d)
    if not u.get("user_id"): return None
    text="/start" if d["update_type"]=="bot_started" else ((d.get("message") or {}).get("body") or {}).get("text","")
    return {"uid":int(u["user_id"]),"text":str(text).strip(),"name":f"{u.get('first_name','')} {u.get('last_name','')}".strip(),"payload":d.get("payload","")}

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
PENDING=Pending(); PENDING_CASH=Pending(); PENDING_ID=Pending(); PENDING_PAYID=Pending(); PENDING_PAY=Pending(); ONBOARD=Pending()

def cb(t,p): return {"type":"callback","text":t,"payload":p}
def back(): return [[cb(BACK+" РњРµРЅСЋ","show_menu")]]
def cancel(): return [[cb(CROSS+" РћС‚РјРµРЅР°","cancel_pending")]]
def rep(t,b=None): return {"text":t,"buttons":b or []}
def chunk(bs,n=2): return [bs[i:i+n] for i in range(0,len(bs),n)]
def recent_buttons(prefix):
    rows=recent_clients()
    if not rows: return []
    return chunk([cb(f"{USER} {r['full_name'] or r['card_number']}",f"{prefix}_{r['card_number']}") for r in rows])
def pick_buttons(rows,prefix):
    return chunk([cb(f"{USER} {r['full_name'] or r['card_number']} В· {(r['phone'] or r['card_number'])[-4:]}",f"{prefix}_{r['card_number']}") for r in rows])
def fmt_client(r,bal=None):
    if bal is None: bal=balance(r["id"])
    return (f"{USER} {r['full_name'] or 'Р‘РµР· РёРјРµРЅРё'}\n{CARD} {r['card_number']} В· {PHONE} {r['phone'] or '-'}\n"
            f"{STAR} {bal} Р±Р°Р»Р»РѕРІ В· {CUP} {r['visits_count']} РІРёР·РёС‚РѕРІ\n{MONEY} РџРѕС‚СЂР°С‡РµРЅРѕ: {r['total_spent']:.0f} СЂ.")
def nav(prefix,page,total):
    n=[]
    if page>0: n.append(cb(BACK,f"{prefix}:{page}"))
    if (page+1)*10<total: n.append(cb(RIGHT,f"{prefix}:{page+2}"))
    return [n] if n else []

def menu(uid,name):
    new=not user_exists(uid)
    u=ensure_user(uid,name,WELCOME if not is_priv(uid) else 0)
    bal=balance(u["id"]); name=name or u["full_name"] or "РґСЂСѓРі"; v=u["visits_count"]
    if new and not is_priv(uid):
        ONBOARD.set(uid,{"step":"phone"})
        t=(f"{PARTY} Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ, {name}!{WAVE}\n{GIFT} Р’Р°Рј РЅР°С‡РёСЃР»РµРЅРѕ {WELCOME} Р±Р°Р»Р»РѕРІ!\n\n"
           f"{CARD} РљР°СЂС‚Р°: {u['card_number']}\n\nР—Р°РїРѕР»РЅРёРј РїСЂРѕС„РёР»СЊ?\n{PHONE} РћС‚РїСЂР°РІСЊС‚Рµ РЅРѕРјРµСЂ С‚РµР»РµС„РѕРЅР° (РёР»Рё В«РїСЂРѕРїСѓСЃС‚РёС‚СЊВ»):")
        return rep(t,cancel())
    t=(f"{CUP} РџСЂРёРІРµС‚, {name}!{WAVE}\n\n{CARD} РљР°СЂС‚Р°: {u['card_number']}\n{STAR} Р‘Р°Р»Р°РЅСЃ: {bal} Р±Р°Р»Р»РѕРІ\n"
       f"{lvl_name(v)} В· РєРµС€Р±СЌРє {pct(v)}%\n{CHART} {progress_bar(v)}\n\nР’С‹Р±РµСЂРёС‚Рµ СЂР°Р·РґРµР»:")
    b=[[cb(CARD+" РљР°СЂС‚Р°","show_card"),cb(STAR+" Р‘Р°Р»Р°РЅСЃ","show_balance")],[cb(HIST+" РСЃС‚РѕСЂРёСЏ","show_history"),cb(HELP+" РџРѕРјРѕС‰СЊ","show_help")]]
    if not is_priv(uid):
        b+=[[cb(MEDAL+" РќР°РіСЂР°РґС‹","show_badges"),cb(HAND+" РџСЂРёРіР»Р°СЃРёС‚СЊ","show_refer")]]
    if is_priv(uid):
        b+=[[cb(MONEY+" РљРµС€Р±СЌРє","cashflow"),cb(CARD+" РћРїР»Р°С‚Р° Р±Р°Р»Р»Р°РјРё","payflow")],[cb(SEARCH+" РџРѕРёСЃРє","show_search"),cb(USERS+" РљР»РёРµРЅС‚С‹","show_clients")]]
        if uid in ADMINS: b+=[[cb(CHART2+" РўРѕРї","show_top"),cb(BULB+" РРЅСЃР°Р№С‚С‹","show_insights")],[cb(EXPORT+" CSV","export_csv"),cb(EXPORT+" Р¤Р°Р№Р»С‹","export_files"),cb(MEGA+" Р Р°СЃСЃС‹Р»РєР°","show_broadcast")]]
    return rep(t,b)

def card(u):
    v=u["visits_count"]; bal=balance(u["id"])
    t=(f"{CARD} Р‘РѕРЅСѓСЃРЅР°СЏ РєР°СЂС‚Р°\n\nРќРѕРјРµСЂ: {u['card_number']}\nРЈСЂРѕРІРµРЅСЊ: {lvl_name(v)} В· {pct(v)}%\n"
       f"{CHART} {progress_bar(v)}\n"
       f"Р‘Р°Р»Р°РЅСЃ: {STAR} {bal} Р±Р°Р»Р»РѕРІ\nР’РёР·РёС‚РѕРІ: {CUP} {v}\n")
    nl=next_lvl(v)
    if nl: t+=f"\n{CHART} Р”Рѕ {nl[1]}: РµС‰С‘ {nl[0]-v} РІРёР·РёС‚РѕРІ\n"
    ex=expiring_soon(u["id"])
    if ex: t+=f"\n{WARN} {ex} Р±Р°Р»Р»РѕРІ СЃРіРѕСЂСЏС‚ Р·Р° {WARN_DAYS} РґРЅ.!\n"
    if u["birthday"]: t+=f"\n{CAKE} Р”Р : {u['birthday']}\n"
    t+=f"\nР‘Р°Р»Р»Р°РјРё РѕРїР»Р°С‡РёРІР°РµС‚СЃСЏ РґРѕ {MAX_PAY}% С‡РµРєР°.\nРќР°Р·РѕРІРёС‚Рµ РЅРѕРјРµСЂ Р±Р°СЂРёСЃС‚Р° {CUP}"
    return rep(t,back())
def hist(u):
    parts=[]
    buys=purchases_of(u["id"])
    if buys:
        parts.append(f"{BAG} РџРѕРєСѓРїРєРё:")
        parts+=[f"В· {b['amount']:.0f} СЂ. - {b['items']}" for b in buys]
        parts.append("")
    rows=history(u["id"])
    if rows:
        parts.append(f"{STAR} РћРїРµСЂР°С†РёРё СЃ Р±Р°Р»Р»Р°РјРё:")
        parts+=[f"{r['points']:+d} В· {r['comment'] or r['type']}" for r in rows]
    if not parts: return rep(f"{HIST} РџРѕРєР° РїСѓСЃС‚Рѕ.",back())
    return rep("\n".join(parts),back())
def help_screen(u):
    t=(f"{HELP} РљР°Рє СЌС‚Рѕ СЂР°Р±РѕС‚Р°РµС‚\n\n"
       f"{CUP} РќР°Р·РѕРІРёС‚Рµ Р±Р°СЂРёСЃС‚Р° РЅРѕРјРµСЂ РєР°СЂС‚С‹ РёР»Рё С‚РµР»РµС„РѕРЅ РїРµСЂРµРґ РѕРїР»Р°С‚РѕР№\n"
       f"{STAR} РџРѕР»СѓС‡Р°Р№С‚Рµ РєРµС€Р±СЌРє 3-10% Р±Р°Р»Р»Р°РјРё\n"
       f"{CARD} РћРїР»Р°С‡РёРІР°Р№С‚Рµ Р±Р°Р»Р»Р°РјРё РґРѕ {MAX_PAY}% С‡РµРєР°\n"
       f"{HOUR} Р‘Р°Р»Р»С‹ РґРµР№СЃС‚РІСѓСЋС‚ {EXPIRE_DAYS} РґРЅРµР№\n"
       f"{CAKE} Р’ РґРµРЅСЊ СЂРѕР¶РґРµРЅРёСЏ РґР°СЂРёРј {BDAY_BONUS} Р±Р°Р»Р»РѕРІ (СЃРіРѕСЂСЏС‚ С‡РµСЂРµР· {BDAY_DAYS} РґРЅ.)\n"
       f"{HAND} РџСЂРёРІРµРґРё РґСЂСѓРіР° - РїРѕР»СѓС‡Рё {REF_BONUS} Р±Р°Р»Р»РѕРІ\n\n"
       f"{CHART} РЈСЂРѕРІРЅРё:\n")
    for n,nm,p in LEVELS:
        t+=f"{nm} - {p}%"+(f" (РѕС‚ {n} РІРёР·РёС‚РѕРІ)" if n else "")+"\n"
    t+=f"\n{PHONE} /phone В· {CAKE} /bday В· {TICKET} /promo РљРћР” В· {HAND} /ref РљРћР”"
    return rep(t,back())
def badges_of(u):
    b=[]; v=u["visits_count"]
    if v>=1: b.append(f"{CUP} РџРµСЂРІС‹Р№ РєРѕС„Рµ")
    if v>=10: b.append(f"{SILVER} РџРѕСЃС‚РѕСЏР»РµС†")
    if v>=30: b.append(f"{GOLD} Р—Р°РІСЃРµРіРґР°С‚Р°Р№")
    if v>=60: b.append(f"{DIAM} VIP")
    if u["birthday"]: b.append(f"{CAKE} РРјРµРЅРёРЅРЅРёРє")
    if u["total_spent"]>=5000: b.append(f"{MONEY} Р“СѓСЂРјР°РЅ")
    with db() as c: fr=c.execute("SELECT COUNT(*) FROM users WHERE referred_by=?",(u["card_number"],)).fetchone()[0]
    if fr: b.append(f"{HAND} Р”СЂСѓРі РєРѕС„РµР№РЅРё ({fr})")
    return b
def badges_screen(u):
    b=badges_of(u)
    if not b: return rep(f"{MEDAL} РџРѕРєР° РЅРµС‚ РЅР°РіСЂР°Рґ.\nР—Р°РіР»СЏРЅРёС‚Рµ Р·Р° РєРѕС„Рµ!",back())
    return rep(f"{MEDAL} Р’Р°С€Рё РЅР°РіСЂР°РґС‹:\n\n"+"\n".join("вЂў "+x for x in b),back())
def refer_screen(u):
    return rep(f"{HAND} РџСЂРёРІРµРґРё РґСЂСѓРіР°!\n\nРўРІРѕР№ РєРѕРґ: {u['card_number']}\nР”СЂСѓРі РІРІРѕРґРёС‚: /ref {u['card_number']}\n\nРўС‹ РїРѕР»СѓС‡РёС€СЊ {REF_BONUS} Р±Р°Р»Р»РѕРІ РїРѕСЃР»Рµ РµРіРѕ РїРµСЂРІРѕРіРѕ РІРёР·РёС‚Р°.",back())
def do_refer(uid,code):
    inv=find_user(code)
    if not inv: return rep(f"{SEARCH} РљРѕРґ РЅРµ РЅР°Р№РґРµРЅ.",back())
    if inv["max_user_id"]==uid: return rep(f"{WARN} РќРµР»СЊР·СЏ СѓРєР°Р·Р°С‚СЊ СЃРµР±СЏ.",back())
    with db() as c:
        u=c.execute("SELECT visits_count,referred_by FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if not u: return rep(f"{WARN} РЎРЅР°С‡Р°Р»Р° /start.",back())
        if u["referred_by"]: return rep(f"{WARN} РљРѕРґ СѓР¶Рµ СѓРєР°Р·Р°РЅ.",back())
        if u["visits_count"]>0: return rep(f"{WARN} РљРѕРґ РјРѕР¶РЅРѕ РІРІРµСЃС‚Рё РґРѕ РїРµСЂРІРѕРіРѕ РІРёР·РёС‚Р°.",back())
        c.execute("UPDATE users SET referred_by=? WHERE max_user_id=?",(inv["card_number"],uid))
    return rep(f"{OK} РљРѕРґ РїСЂРёРЅСЏС‚! РџРѕСЃР»Рµ РїРµСЂРІРѕРіРѕ РІРёР·РёС‚Р° РґСЂСѓРі РїРѕР»СѓС‡РёС‚ {REF_BONUS}.",back())
def promo_create(code,points):
    with db() as c: c.execute("INSERT OR REPLACE INTO promos(code,points,active) VALUES(?,?,1)",(code.upper(),points))
    return rep(f"{TICKET} РџСЂРѕРјРѕРєРѕРґ {code.upper()} РЅР° {points} СЃРѕР·РґР°РЅ.",back())
def promo_stop(code):
    with db() as c: c.execute("UPDATE promos SET active=0 WHERE code=?",(code.upper(),))
    return rep(f"{TICKET} РџСЂРѕРјРѕРєРѕРґ {code.upper()} РґРµР°РєС‚РёРІРёСЂРѕРІР°РЅ.",back())
def promo_redeem(uid,code):
    code=code.upper()
    with db() as c:
        r=c.execute("SELECT * FROM promos WHERE code=? AND active=1",(code,)).fetchone()
        if not r: return rep(f"{WARN} РџСЂРѕРјРѕРєРѕРґ РЅРµ РЅР°Р№РґРµРЅ.",back())
        u=c.execute("SELECT id FROM users WHERE max_user_id=?",(uid,)).fetchone()
        if not u: return rep(f"{WARN} РЎРЅР°С‡Р°Р»Р° /start.",back())
        if c.execute("SELECT 1 FROM promo_use WHERE user_id=? AND code=?",(u["id"],code)).fetchone():
            return rep(f"{WARN} Р’С‹ СѓР¶Рµ РёСЃРїРѕР»СЊР·РѕРІР°Р»Рё СЌС‚РѕС‚ РєРѕРґ.",back())
        c.execute("INSERT INTO promo_use(user_id,code) VALUES(?,?)",(u["id"],code))
        _batch(c,u["id"],r["points"],"promo",TICKET+" РџСЂРѕРјРѕРєРѕРґ "+code)
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(u["id"],"accrual",r["points"],TICKET+" РџСЂРѕРјРѕРєРѕРґ "+code))
    return rep(f"{OK} +{r['points']} Р±Р°Р»Р»РѕРІ РїРѕ РєРѕРґСѓ {code}!",back())
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
    send_text(admin_uid,f"{MEGA} Р Р°СЃСЃС‹Р»РєР° Р·Р°РІРµСЂС€РµРЅР°. РћС‚РїСЂР°РІР»РµРЅРѕ: {n}.")
def do_broadcast(text,uid):
    p=text.split()
    seg="active"; body=text
    if p and p[0].lower() in ("all","active","sleep"):
        seg=p[0].lower(); body=text.split(maxsplit=1)[1] if len(p)>1 else ""
    if not body: return rep(f"{MEGA} Р¤РѕСЂРјР°С‚: /broadcast [all|active|sleep] С‚РµРєСЃС‚",back())
    threading.Thread(target=_send_broadcast,args=(seg,body,int(uid)),daemon=True).start()
    return rep(f"{MEGA} Р Р°СЃСЃС‹Р»РєР° Р·Р°РїСѓС‰РµРЅР°: {seg}.",back())
def do_export_files():
    now=datetime.now()
    with db() as c:
        users=c.execute("SELECT u.*, COALESCE((SELECT SUM(b.points_left) FROM points_batches b WHERE b.user_id=u.id AND b.points_left>0 AND b.expires_at>?),0) bal FROM users u ORDER BY created_at DESC",(now,)).fetchall()
        buys=c.execute("SELECT p.amount,p.item,p.created_at,u.full_name,u.card_number,u.phone FROM purchases p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC").fetchall()
    with open("clients.csv","w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["ID","РРјСЏ","РўРµР»РµС„РѕРЅ","РљР°СЂС‚Р°","РџРѕСЃРµС‰РµРЅРёР№","РџРѕС‚СЂР°С‡РµРЅРѕ","Р‘Р°Р»Р»С‹","Р”Р ","Р РµРіРёСЃС‚СЂР°С†РёСЏ"])
        for r in users: w.writerow([r["id"],r["full_name"] or "",r["phone"] or "",r["card_number"],r["visits_count"],f"{r['total_spent']:.0f}",int(r["bal"]),r["birthday"],r["created_at"]])
    with open("purchases.csv","w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["Р”Р°С‚Р°","РРјСЏ","РљР°СЂС‚Р°","РўРµР»РµС„РѕРЅ","РЎСѓРјРјР°","РўРѕРІР°СЂ"])
        for r in buys: w.writerow([r["created_at"],r["full_name"] or "",r["card_number"],r["phone"] or "",f"{r['amount']:.0f}",r["item"] or ""])
    return rep(f"{EXPORT} Р¤Р°Р№Р»С‹ РіРѕС‚РѕРІС‹:\nclients.csv В· purchases.csv\nРЎРєР°С‡Р°Р№С‚Рµ С‡РµСЂРµР· WinSCP.",back())
def set_phone(uid,text):
    p=text.split()
    if len(p)<2: return rep(f"{PHONE} РЈРєР°Р¶РёС‚Рµ: /phone 79991234567",back())
    d=norm_phone(p[1])
    if not d: return rep(f"{PHONE} РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚",back())
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE phone=? AND max_user_id!=?",(d,uid)).fetchone(): return rep(f"{PHONE} РЈР¶Рµ РїСЂРёРІСЏР·Р°РЅ.",back())
        c.execute("UPDATE users SET phone=? WHERE max_user_id=?",(d,uid))
    return rep(f"{PHONE} РЎРѕС…СЂР°РЅРµРЅРѕ: {d}",back())
def parse_bday(s):
    try:
        dt=datetime.strptime(s,"%d.%m"); return dt.day,dt.month
    except ValueError:
        return None
def set_bday(uid,text):
    p=text.split()
    if len(p)<2: return rep(f"{CAKE} РЈРєР°Р¶РёС‚Рµ: /bday 15.05",back())
    r=parse_bday(p[1])
    if not r: return rep(f"{CAKE} РќРµРІРµСЂРЅР°СЏ РґР°С‚Р°. РџСЂРёРјРµСЂ: /bday 15.05",back())
    dd,mm=r
    with db() as c: c.execute("UPDATE users SET birthday=? WHERE max_user_id=?",(f"{dd:02d}.{mm:02d}",uid))
    return rep(f"{CAKE} РЎРѕС…СЂР°РЅРµРЅРѕ: {dd:02d}.{mm:02d}\nР’ Р”Р  РґР°СЂРёРј {BDAY_BONUS} Р±Р°Р»Р»РѕРІ (СЃРіРѕСЂСЏС‚ С‡РµСЂРµР· {BDAY_DAYS} РґРЅ.)!",back())
def clients(uid,page=0):
    if uid not in ADMINS: return rep(f"{NO} РўРѕР»СЊРєРѕ Р°РґРјРёРЅ.",back())
    rows,total=search("",page)
    if not rows: return rep(f"{USERS} РџРѕРєР° РїСѓСЃС‚Рѕ.",back())
    return rep(f"{USERS} РљР»РёРµРЅС‚С‹ В· СЃС‚СЂ. {page+1} В· РІСЃРµРіРѕ {total}\nР’С‹Р±РµСЂРёС‚Рµ:",pick_buttons(rows,"sel")+nav("cp",page,total)+back())
def do_search(uid,q,page=0):
    if not is_priv(uid): return rep(f"{NO} РўРѕР»СЊРєРѕ РїРµСЂСЃРѕРЅР°Р».",back())
    if not q: return rep(f"{SEARCH} /find РРІР°РЅ В· /find 7999 В· /find COFFEE",back())
    rows,total=search(q,page)
    if not rows: return rep(f"{SEARCH} В«{q}В» - РЅРµ РЅР°Р№РґРµРЅРѕ.",back())
    return rep(f"{SEARCH} В«{q}В» В· {total}\nР’С‹Р±РµСЂРёС‚Рµ РєР»РёРµРЅС‚Р°:",pick_buttons(rows,"sel")+nav("sp",page,total)+back())
def do_export(uid):
    if uid not in ADMINS: return rep(f"{NO} РўРѕР»СЊРєРѕ Р°РґРјРёРЅ.",back())
    l=export_csv().split("\n")[:21]
    t=f"{EXPORT} Р‘Р°Р·Р°:\n\n"+"\n".join(l)
    if len(l)>=21: t+="\n... (РїРµСЂРІС‹Рµ 20). РџРѕР»РЅС‹Р№ С„Р°Р№Р»: /files"
    return rep(t,back())
def do_top(uid):
    if not is_priv(uid): return rep(f"{NO} РўРѕР»СЊРєРѕ РїРµСЂСЃРѕРЅР°Р».",back())
    rows=top_items()
    if not rows: return rep(f"{BAG} РџРѕРєР° РЅРµС‚ РґР°РЅРЅС‹С….\nР”РѕР±Р°РІР»СЏР№С‚Рµ С‚РѕРІР°СЂС‹ РїСЂРё РєРµС€Р±СЌРєРµ: В«500 Р»Р°С‚С‚Рµ, РєСЂСѓР°СЃСЃР°РЅВ».",back())
    l=[f"{BAG} РўРѕРї С‚РѕРІР°СЂРѕРІ:",""]+[f"{i+1}. {r['item']} В· {r['cnt']} СЂР°Р· В· {r['rev']:.0f} СЂ." for i,r in enumerate(rows)]
    return rep("\n".join(l),back())
def do_insights(uid):
    if uid not in ADMINS: return rep(f"{NO} РўРѕР»СЊРєРѕ Р°РґРјРёРЅ.",back())
    now=datetime.now(); ma=now-timedelta(days=30)
    with db() as c:
        total=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active=c.execute("SELECT COUNT(*) FROM users WHERE last_visit>=?",(ma,)).fetchone()[0]
        dormant=c.execute("SELECT COUNT(*) FROM users WHERE last_visit<? AND last_visit IS NOT NULL",(ma,)).fetchone()[0]
        avg=c.execute("SELECT COALESCE(AVG(amount),0) FROM purchases").fetchone()[0]
    top=top_items(5)
    t=(f"{BULB} РРЅСЃР°Р№С‚С‹\n\n{USERS} Р’СЃРµРіРѕ: {total}\n{CHART} РђРєС‚РёРІ. Р·Р° 30 РґРЅ: {active}\n"
       f"{HOUR} РЈСЃРЅСѓРІС€РёС… (>30 РґРЅ): {dormant}\n{RECEIPT} РЎСЂРµРґРЅРёР№ С‡РµРє: {avg:.0f} СЂ.\n")
    if top: t+="\n"+BAG+" РўРѕРї: "+", ".join(r["item"] for r in top)+"\n"
    ideas=[]
    if dormant: ideas.append(f"Р’РµСЂРЅСѓС‚СЊ {dormant} СѓСЃРЅСѓРІС€РёС…: /broadcast sleep РїСЂРѕРјРѕ")
    if len(top)>=2: ideas.append(f"Р‘Р°РЅРґР»: В«{top[0]['item']} + {top[1]['item']}В» Р·Р° Р±Р°Р»Р»С‹")
    ideas.append("Р”РІРѕР№РЅРѕР№ РєРµС€Р±СЌРє РІ С‚РёС…РёРµ С‡Р°СЃС‹")
    t+="\n"+OK+" РРґРµРё:\n"+"\n".join("- "+i for i in ideas)
    return rep(t,back())
def admin_card(u):
    items=recent_items(u["id"])
    txt=fmt_client(u)
    if items: txt+=f"\n{BAG} РџРѕРєСѓРїР°РµС‚: {', '.join(items)}"
    b=[[cb(PLUS+"50",f"add_50_{u['card_number']}"),cb(PLUS+"100",f"add_100_{u['card_number']}"),cb(PLUS+"200",f"add_200_{u['card_number']}")],
       [cb(MINUS+"50",f"sub_50_{u['card_number']}"),cb(MINUS+"100",f"sub_100_{u['card_number']}"),cb(MINUS+"200",f"sub_200_{u['card_number']}")],
       [cb(MONEY+" РљРµС€Р±СЌРє",f"cash_{u['card_number']}"),cb(CARD+" РћРїР»Р°С‚Р°",f"pay_{u['card_number']}"),cb(BAG+" РџРѕРєСѓРїРєРё",f"buy_{u['card_number']}")]]+back()
    return rep(txt,b)
def apply_delta(uid,delta,target,comment=""):
    if delta>0: add_points(target["id"],delta,"manual",comment or f"{PLUS} {delta}")
    else:
        ok,nb=spend_points(target["id"],-delta,comment or f"{MINUS} {-delta}")
        if not ok: return rep(f"{WARN} РќРµР»СЊР·СЏ СЃРїРёСЃР°С‚СЊ {-delta}. Р‘Р°Р»Р°РЅСЃ: {nb}",back())
    PENDING.clear(uid)
    return rep(f"{OK} {PLUS if delta>0 else MINUS} {abs(delta)}\nРќРѕРІС‹Р№ Р±Р°Р»Р°РЅСЃ: {STAR} {balance(target['id'])}",back())
def apply_cashback(target,amount,items=None):
    pts=int(amount*pct(target["visits_count"])/100)
    rid=uuid.uuid4().hex[:8]
    inv_uid=None
    with db() as c:
        _batch(c,target["id"],pts,"cashback",f"{MONEY} РљРµС€Р±СЌРє Р·Р° С‡РµРє {amount:.0f} СЂ.")
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(target["id"],"accrual",pts,f"{MONEY} РљРµС€Р±СЌРє Р·Р° С‡РµРє {amount:.0f} СЂ."))
        c.execute("UPDATE users SET visits_count=visits_count+1,total_spent=total_spent+?,last_visit=? WHERE id=?",(amount,datetime.now(),target["id"]))
        if items: c.executemany("INSERT INTO purchases(user_id,amount,item,receipt_id) VALUES(?,?,?,?)",[(target["id"],amount,it,rid) for it in items])
        ref=c.execute("SELECT referred_by,ref_done FROM users WHERE id=?",(target["id"],)).fetchone()
        if ref and ref["referred_by"] and not ref["ref_done"]:
            inv=find_user(ref["referred_by"])
            if inv:
                _batch(c,inv["id"],REF_BONUS,"referral",HAND+" Р—Р° РґСЂСѓРіР°")
                c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(inv["id"],"accrual",REF_BONUS,HAND+" Р—Р° РґСЂСѓРіР°"))
                c.execute("UPDATE users SET ref_done=1 WHERE id=?",(target["id"],))
                inv_uid=inv["max_user_id"]
        u2=c.execute("SELECT visits_count,level FROM users WHERE id=?",(target["id"],)).fetchone()
        nl=max((i for i,(n,_,_) in enumerate(LEVELS) if u2["visits_count"]>=n),default=0)
        up=nl!=u2["level"]
        if up: c.execute("UPDATE users SET level=? WHERE id=?",(nl,target["id"]))
    if inv_uid:
        send_text(int(inv_uid),f"{PARTY} Р’Р°С€ РґСЂСѓРі СЃРѕРІРµСЂС€РёР» РїРµСЂРІС‹Р№ РІРёР·РёС‚! +{REF_BONUS} Р±Р°Р»Р»РѕРІ {HAND}")
    v=u2["visits_count"]
    msg=f"{OK} РљРµС€Р±СЌРє РЅР°С‡РёСЃР»РµРЅ!\n\n{RECEIPT} Р§РµРє: {amount:.0f} СЂ.\n{lvl_name(v)} В· +{pts} Р±Р°Р»Р»РѕРІ\n{STAR} Р‘Р°Р»Р°РЅСЃ: {balance(target['id'])}"
    if up: msg+=f"\n\n{PARTY} РќРѕРІС‹Р№ СѓСЂРѕРІРµРЅСЊ: {lvl_name(v)} В· {pct(v)}%!"
    return rep(msg,back())
def cash_amount_prompt(uid,cn,t):
    btn=chunk([cb("300",f"qa_300_{cn}"),cb("500",f"qa_500_{cn}"),cb("700",f"qa_700_{cn}"),cb("1000",f"qa_1000_{cn}")])
    return rep(f"{MONEY} {t['full_name'] if t else cn} В· РєРµС€Р±СЌРє {pct(t['visits_count']) if t else 0}%\nРЎСѓРјРјР° С‡РµРєР° (С‚РѕРІР°СЂС‹ С‡РµСЂРµР· Р·Р°РїСЏС‚СѓСЋ) РёР»Рё РєРЅРѕРїРєР°:",btn+cancel()+back())
def cashback_cmd(uid,text):
    p=text.split()
    if len(p)<3: return rep(f"{MONEY} Р¤РѕСЂРјР°С‚: /cashback 500 COFFEE... [С‚РѕРІР°СЂС‹,С‡РµСЂРµР·,Р·Р°РїСЏС‚СѓСЋ]",back())
    if not is_float(p[1]): return rep(f"{MONEY} РќРµРІРµСЂРЅР°СЏ СЃСѓРјРјР°",back())
    amount=float(p[1])
    if amount<=0: return rep(f"{MONEY} РЎСѓРјРјР° > 0",back())
    t=find_user(p[2])
    if not t: return rep(f"{SEARCH} РЅРµ РЅР°Р№РґРµРЅ",back())
    items=[x.strip().lower() for x in " ".join(p[3:]).split(",") if x.strip()]
    return apply_cashback(t,amount,items)

def handle_onboard(uid,text,name=""):
    ob=ONBOARD.get(uid); t=text.strip()
    if ob["step"]=="phone":
        if "РїСЂРѕРїСѓСЃС‚РёС‚СЊ" in t.lower() or t in ("-","РЅРµС‚"):
            ONBOARD.set(uid,{"step":"bday"}); return rep(f"{CAKE} РўРµРїРµСЂСЊ РґР°С‚Р° СЂРѕР¶РґРµРЅРёСЏ: 15.05 (РёР»Рё В«РїСЂРѕРїСѓСЃС‚РёС‚СЊВ»):",cancel())
        d=norm_phone(t)
        if d:
            with db() as c:
                if c.execute("SELECT 1 FROM users WHERE phone=? AND max_user_id!=?",(d,uid)).fetchone():
                    return rep(f"{WARN} РќРѕРјРµСЂ СѓР¶Рµ РїСЂРёРІСЏР·Р°РЅ Рє РґСЂСѓРіРѕР№ РєР°СЂС‚Рµ. Р”СЂСѓРіРѕР№ РёР»Рё В«РїСЂРѕРїСѓСЃС‚РёС‚СЊВ».",cancel())
                c.execute("UPDATE users SET phone=? WHERE max_user_id=?",(d,uid))
            ONBOARD.set(uid,{"step":"bday"}); return rep(f"{PHONE} РЎРѕС…СЂР°РЅРµРЅРѕ!\n{CAKE} Р”Р°С‚Р° СЂРѕР¶РґРµРЅРёСЏ: 15.05 (РёР»Рё В«РїСЂРѕРїСѓСЃС‚РёС‚СЊВ»):",cancel())
        return rep(f"{WARN} РџСЂРёРјРµСЂ: 79991234567 (РёР»Рё В«РїСЂРѕРїСѓСЃС‚РёС‚СЊВ»)",cancel())
    if ob["step"]=="bday":
        if "РїСЂРѕРїСѓСЃС‚РёС‚СЊ" in t.lower() or t in ("-","РЅРµС‚"):
            ONBOARD.clear(uid); return menu(uid,name)
        r=None
        for tok in t.split():
            r=parse_bday(tok)
            if r: break
        if not r: return rep(f"{WARN} Р¤РѕСЂРјР°С‚: 15.05 (РёР»Рё В«РїСЂРѕРїСѓСЃС‚РёС‚СЊВ»)",cancel())
        dd,mm=r
        with db() as c: c.execute("UPDATE users SET birthday=? WHERE max_user_id=?",(f"{dd:02d}.{mm:02d}",uid))
        ONBOARD.clear(uid); return menu(uid,name)
    ONBOARD.clear(uid); return menu(uid,name)

def handle_message(uid,text,name,payload=""):
    uid=str(uid); t=text.strip(); p=t.split(); cmd=t.lower()
    if name:
        with db() as c: c.execute("UPDATE users SET full_name=? WHERE max_user_id=? AND (full_name IS NULL OR full_name='')",(name,uid))
    if payload=="show_card": return card(ensure_user(uid,name,WELCOME if not is_priv(uid) else 0))
    if payload.startswith("ref_"):
        if not user_exists(uid): ensure_user(uid,name,WELCOME)
        return do_refer(uid,payload[4:])
    if cmd in ("/start","/help"):
        if cmd=="/start":
            for P in (PENDING,PENDING_CASH,PENDING_ID,PENDING_PAYID,PENDING_PAY): P.clear(uid)
        ONBOARD.clear(uid); return menu(uid,name)
    ob=ONBOARD.get(uid)
    if ob and not is_priv(uid):
        if t.lower() in ("РѕС‚РјРµРЅР°","cancel","/cancel"):
            ONBOARD.clear(uid); return rep(f"{CROSS} РћС‚РјРµРЅРµРЅРѕ.",back())
        return handle_onboard(uid,t,name)
    if is_priv(uid) and p:
        op=p[0]
        if t.lower() in ("РѕС‚РјРµРЅР°","cancel","/cancel","/menu"):
            for P in (PENDING,PENDING_CASH,PENDING_ID,PENDING_PAYID,PENDING_PAY): P.clear(uid)
            if t.lower()=="/menu": return menu(uid,name)
            return rep(f"{CROSS} Р”РµР№СЃС‚РІРёРµ РѕС‚РјРµРЅРµРЅРѕ.",back())
        if PENDING_ID.get(uid):
            target=find_user(op)
            if target:
                PENDING_ID.clear(uid); PENDING_CASH.set(uid,target["card_number"])
                return cash_amount_prompt(uid,target["card_number"],target)
            return rep(f"{SEARCH} В«{op}В» РЅРµ РЅР°Р№РґРµРЅ. РўРµР»РµС„РѕРЅ РёР»Рё РєР°СЂС‚Р°?",cancel()+back())
        if PENDING_PAYID.get(uid):
            target=find_user(op)
            if target:
                PENDING_PAYID.clear(uid); PENDING_PAY.set(uid,{"card":target["card_number"],"amount":None})
                return rep(f"{USER} {target['full_name'] or target['card_number']} В· {CARD} {target['card_number']} В· {STAR} {balance(target['id'])}\nРЎСѓРјРјР° РїРѕРєСѓРїРєРё:",cancel()+back())
            return rep(f"{SEARCH} РЅРµ РЅР°Р№РґРµРЅ. РўРµР»РµС„РѕРЅ РёР»Рё РєР°СЂС‚Р°?",cancel()+back())
        pay=PENDING_PAY.get(uid)
        if pay is not None:
            card_no=pay["card"]; amt=pay.get("amount")
            target=find_user(card_no)
            if not target:
                PENDING_PAY.clear(uid); return rep(f"{WARN} РљР»РёРµРЅС‚ РЅРµ РЅР°Р№РґРµРЅ.",back())
            bal=balance(target["id"])
            if amt is None:
                if is_float(op):
                    amount=float(op); maxpay=min(bal,int(amount*MAX_PAY/100))
                    PENDING_PAY.set(uid,{"card":card_no,"amount":amount})
                    btn=[[cb(f"{MINUS} {maxpay}",f"deduct_{maxpay}_{card_no}")]] if maxpay>0 else []
                    return rep(f"{RECEIPT} Р§РµРє: {amount:.0f} СЂ.\nРњРѕР¶РЅРѕ СЃРїРёСЃР°С‚СЊ РґРѕ {maxpay} Р±Р°Р»Р»РѕРІ ({MAX_PAY}%).\nР’РІРµРґРёС‚Рµ С‡РёСЃР»Рѕ РёР»Рё max:",btn+cancel()+back())
                return rep(f"{WARN} Р’РІРµРґРёС‚Рµ СЃСѓРјРјСѓ С‡РёСЃР»РѕРј.",cancel()+back())
            amount=float(amt); cap=min(bal,int(amount*MAX_PAY/100))
            if op.lower()=="max": deduct=cap
            elif op.isdigit(): deduct=int(op)
            else: return rep(f"{THINK} Р§РёСЃР»Рѕ РёР»Рё max.",cancel()+back())
            if deduct<=0 or deduct>cap: return rep(f"{WARN} РњРѕР¶РЅРѕ 1..{cap}",cancel()+back())
            ok,nb=spend_points(target["id"],deduct,f"{CARD} РћРїР»Р°С‚Р° Р±Р°Р»Р»Р°РјРё")
            PENDING_PAY.clear(uid)
            return rep(f"{OK} РЎРїРёСЃР°РЅРѕ {deduct}\nРћСЃС‚Р°С‚РѕРє: {STAR} {nb}",back()) if ok else rep(f"{WARN} РќРµ С…РІР°С‚РёР»Рѕ Р±Р°Р»Р»РѕРІ",back())
        if len(op)>1 and op[0] in "+-" and op[1:].isdigit():
            delta=int(op)
            if delta!=0:
                target=None
                if len(p)>=2:
                    target=find_user(p[1])
                    if not target: return rep(f"{SEARCH} В«{p[1]}В» РЅРµ РЅР°Р№РґРµРЅ.",back())
                else:
                    cn=PENDING.get(uid)
                    if cn: target=find_user(cn)
                if target: return apply_delta(uid,delta,target," ".join(p[2:]))
                return rep(f"{THINK} РЈРєР°Р¶РёС‚Рµ: {op} COFFEE... РёР»Рё РєРЅРѕРїРєР° РІ РєР°СЂС‚РѕС‡РєРµ",back())
        elif is_float(op):
            amount=float(op); cn=PENDING_CASH.get(uid)
            if cn:
                if amount<=0: return rep(f"{WARN} РЎСѓРјРјР° С‡РµРєР° РґРѕР»Р¶РЅР° Р±С‹С‚СЊ > 0.",cancel()+back())
                target=find_user(cn)
                if target:
                    PENDING_CASH.clear(uid)
                    items=[x.strip().lower() for x in " ".join(p[1:]).split(",") if x.strip()]
                    return apply_cashback(target,amount,items)
            return rep(f"{THINK} РЎРЅР°С‡Р°Р»Р° РІС‹Р±РµСЂРёС‚Рµ РєР»РёРµРЅС‚Р° (РєРЅРѕРїРєР° РљРµС€Р±СЌРє)",back())
        if op=="?" and len(p)>=2:
            target=find_user(p[1])
            return admin_card(target) if target else rep(f"{SEARCH} РЅРµ РЅР°Р№РґРµРЅ",back())
        if cmd.startswith("/cashback"): return cashback_cmd(uid,t)
        if cmd.startswith("/promo_stop") and len(p)>=2: return promo_stop(p[1])
        if cmd.startswith("/promo") and len(p)>=3 and p[2].isdigit():
            return promo_create(p[1],int(p[2]))
        if cmd=="/broadcast": return do_broadcast(t.split(maxsplit=1)[1] if len(p)>1 else "",uid)
        if cmd=="/files": return do_export_files()
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
        ex=expiring_soon(u["id"]); msg=f"{STAR} Р‘Р°Р»Р°РЅСЃ: {balance(u['id'])} Р±Р°Р»Р»РѕРІ."
        if ex: msg+=f"\n{WARN} {ex} СЃРіРѕСЂСЏС‚ Р·Р° {WARN_DAYS} РґРЅ.!"
        return rep(msg,back())
    if cmd=="/history": return hist(u)
    if cmd.startswith("/phone"): return set_phone(uid,t)
    if cmd.startswith("/bday"): return set_bday(uid,t)
    if cmd.startswith("/ref"): return do_refer(uid,p[1] if len(p)>1 else "")
    if cmd.startswith("/promo"): return promo_redeem(uid,p[1] if len(p)>1 else "")
    hint=f"{THINK} РќРµ РїРѕРЅСЏР». /help - РєРѕРјР°РЅРґС‹."
    if is_priv(uid): hint=f"{TOOLS} РџРµСЂСЃРѕРЅР°Р»:\n{MONEY} РљРµС€Р±СЌРє В· {CARD} РћРїР»Р°С‚Р° Р±Р°Р»Р»Р°РјРё\n/find 7999 В· /top В· ? COFFEE..."
    elif not u["phone"]: hint+=f"\n{PHONE} /phone В· {CAKE} /bday В· {TICKET} /promo В· {HAND} /ref"
    return rep(hint,back())

def handle_callback(uid,payload,name):
    uid=str(uid); u=ensure_user(uid,name)
    PRIV=("cashflow","payflow","show_search","show_top")
    if payload in PRIV or payload.startswith(("add_","sub_","input_","cash_","pay_","sp:","deduct_","rcc_","rcp_","qa_","sel_","buy_")):
        if not is_priv(uid): return rep(f"{NO} РўРѕР»СЊРєРѕ РїРµСЂСЃРѕРЅР°Р».",back())
    if payload in ("show_clients","export_csv","export_files","show_insights","show_broadcast") or payload.startswith("cp:"):
        if uid not in ADMINS: return rep(f"{NO} РўРѕР»СЊРєРѕ Р°РґРјРёРЅ.",back())
    if payload=="show_menu": return menu(uid,name)
    if payload=="show_help": return help_screen(u)
    if payload=="show_card": return card(u)
    if payload=="show_balance": return handle_message(uid,"/balance",name)
    if payload=="show_history": return hist(u)
    if payload=="show_badges": return badges_screen(u)
    if payload=="show_refer": return refer_screen(u)
    if payload=="show_clients": return clients(uid)
    if payload=="show_search": return do_search(uid,"")
    if payload=="show_top": return do_top(uid)
    if payload=="show_insights": return do_insights(uid)
    if payload=="show_broadcast": return rep(f"{MEGA} Р Р°СЃСЃС‹Р»РєР°\n/broadcast [all|active|sleep] С‚РµРєСЃС‚\n\nall - РІСЃРµРј\nactive - Р±С‹Р»Рё Р·Р° 30 РґРЅ\nsleep - СѓСЃРЅСѓРІС€РёРµ",back())
    if payload=="export_csv": return do_export(uid)
    if payload=="export_files": return do_export_files()
    if payload.startswith("sel_"):
        target=find_user(payload[4:])
        return admin_card(target) if target else rep(f"{WARN} РќРµ РЅР°Р№РґРµРЅ.",back())
    if payload.startswith("buy_"):
        target=find_user(payload[4:])
        if not target: return rep(f"{WARN} РќРµ РЅР°Р№РґРµРЅ.",back())
        buys=purchases_of(target["id"],10)
        if not buys: return rep(f"{BAG} РџРѕРєСѓРїРѕРє РїРѕРєР° РЅРµС‚.",back())
        return rep(f"{BAG} {target['full_name'] or target['card_number']}:\n"+"\n".join(f"В· {b['amount']:.0f} СЂ. - {b['items']}" for b in buys),back())
    if payload.startswith("cashflow"):
        PENDING_ID.set(uid,"1")
        return rep(f"{MONEY} РљРµС€Р±СЌРє\nР’С‹Р±РµСЂРёС‚Рµ РєР»РёРµРЅС‚Р° РёР»Рё РІРІРµРґРёС‚Рµ С‚РµР»РµС„РѕРЅ/РєР°СЂС‚Сѓ/РёРјСЏ:",recent_buttons("rcc")+cancel()+back())
    if payload.startswith("payflow"):
        PENDING_PAYID.set(uid,"1")
        return rep(f"{CARD} РћРїР»Р°С‚Р° Р±Р°Р»Р»Р°РјРё\nР’С‹Р±РµСЂРёС‚Рµ РєР»РёРµРЅС‚Р° РёР»Рё РІРІРµРґРёС‚Рµ С‚РµР»РµС„РѕРЅ/РєР°СЂС‚Сѓ/РёРјСЏ:",recent_buttons("rcp")+cancel()+back())
    if payload=="cancel_pending":
        for P in (PENDING,PENDING_CASH,PENDING_ID,PENDING_PAYID,PENDING_PAY,ONBOARD): P.clear(uid)
        return rep(f"{CROSS} РћС‚РјРµРЅРµРЅРѕ.",back())
    if payload.startswith("rcc_"):
        PENDING_ID.clear(uid); cn=payload[4:]; PENDING_CASH.set(uid,cn); return cash_amount_prompt(uid,cn,find_user(cn))
    if payload.startswith("rcp_"):
        PENDING_PAYID.clear(uid); cn=payload[4:]; PENDING_PAY.set(uid,{"card":cn,"amount":None}); t=find_user(cn)
        return rep(f"{USER} {(t['full_name'] or t['card_number']) if t else cn} В· {STAR} {balance(t['id']) if t else 0}\nРЎСѓРјРјР° РїРѕРєСѓРїРєРё:",cancel()+back())
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
        except ValueError: return rep(f"{WARN} РћС€РёР±РєР° СЃСѓРјРјС‹.",back())
        target=find_user(parts[2])
        if not target: return rep(f"{WARN} РљР»РёРµРЅС‚ РЅРµ РЅР°Р№РґРµРЅ.",back())
        ok,nb=spend_points(target["id"],amount,f"{CARD} РћРїР»Р°С‚Р° Р±Р°Р»Р»Р°РјРё")
        PENDING_PAY.clear(uid)
        return rep(f"{OK} РЎРїРёСЃР°РЅРѕ {amount}\nРћСЃС‚Р°С‚РѕРє: {STAR} {nb}",back()) if ok else rep(f"{WARN} РќРµ С…РІР°С‚РёР»Рѕ Р±Р°Р»Р»РѕРІ",back())
    if payload.startswith("add_") or payload.startswith("sub_"):
        parts=payload.split("_",2); target=find_user(parts[2])
        if target: return apply_delta(uid,int(parts[1]) if payload.startswith("add_") else -int(parts[1]),target)
    if payload.startswith("input_"):
        cn=payload[6:]; PENDING.set(uid,cn); return rep(f"{CARD} {cn}\nРќР°РїРёС€РёС‚Рµ: +50 РёР»Рё -100",cancel()+back())
    if payload.startswith("cash_"):
        PENDING_ID.clear(uid); cn=payload[5:]; PENDING_CASH.set(uid,cn); return cash_amount_prompt(uid,cn,find_user(cn))
    if payload.startswith("pay_"):
        PENDING_PAYID.clear(uid); cn=payload[5:]; PENDING_PAY.set(uid,{"card":cn,"amount":None}); t=find_user(cn)
        return rep(f"{USER} {(t['full_name'] or t['card_number']) if t else cn} В· {STAR} {balance(t['id']) if t else 0}\nРЎСѓРјРјР° РїРѕРєСѓРїРєРё:",cancel()+back())
    return rep(f"{THINK} РќРµРёР·РІРµСЃС‚РЅРѕ.",back())

def expire_loop():
    while True:
        try:
            now=datetime.now()
            with db() as c:
                for b in c.execute("SELECT id,user_id,points_left FROM points_batches WHERE expires_at<=? AND points_left>0",(now,)):
                    c.execute("UPDATE points_batches SET points_left=0 WHERE id=?",(b["id"],))
                    c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(b["user_id"],"expired",-b["points_left"],HOUR+" РЎРіРѕСЂР°РЅРёРµ"))
            with db() as c:
                users=c.execute("SELECT u.id,u.max_user_id,u.last_notify,u.birthday,u.bday_year,u.full_name FROM users u "
                                "WHERE u.birthday!='' OR EXISTS(SELECT 1 FROM points_batches b WHERE b.user_id=u.id AND b.points_left>0 AND b.expires_at<=?)",
                                (now+timedelta(days=WARN_DAYS),)).fetchall()
            for r in users:
                if r["birthday"]:
                    ddmm=parse_bday(r["birthday"])
                    if ddmm and ddmm[0]==now.day and ddmm[1]==now.month and r["bday_year"]!=now.year:
                        with db() as c:
                            _batch(c,r["id"],BDAY_BONUS,"birthday",GIFT+" Р‘РѕРЅСѓСЃ РєРѕ РґРЅСЋ СЂРѕР¶РґРµРЅРёСЏ",BDAY_DAYS)
                            c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(r["id"],"accrual",BDAY_BONUS,CAKE+" Р‘РѕРЅСѓСЃ РєРѕ РґРЅСЋ СЂРѕР¶РґРµРЅРёСЏ"))
                            c.execute("UPDATE users SET bday_year=? WHERE id=?",(now.year,r["id"]))
                        send_text(int(r["max_user_id"]),f"{PARTY} {r['full_name'] or 'Р”СЂСѓРі'}, СЃ РґРЅС‘Рј СЂРѕР¶РґРµРЅРёСЏ!\n{GIFT} Р”Р°СЂРёРј {BDAY_BONUS} Р±Р°Р»Р»РѕРІ - РїРѕС‚СЂР°С‚СЊС‚Рµ Р·Р° {BDAY_DAYS} РґРЅ. {CUP}")
                if r["last_notify"]:
                    try:
                        if (now-datetime.fromisoformat(r["last_notify"])).days<3: continue
                    except ValueError: pass
                ex=expiring_soon(r["id"])
                if ex>0:
                    if send_text(int(r["max_user_id"]),f"{WARN} {ex} Р±Р°Р»Р»РѕРІ СЃРіРѕСЂСЏС‚ Р·Р° {WARN_DAYS} РґРЅ. - Р·Р°РіР»СЏРЅРёС‚Рµ! {CUP}"):
                        with db() as c: c.execute("UPDATE users SET last_notify=? WHERE id=?",(now.isoformat(),r["id"]))
                    time.sleep(0.6)
            wb_cut=(now-timedelta(days=WINBACK_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            cd_cut=(now-timedelta(days=WINBACK_CD)).strftime("%Y-%m-%d %H:%M:%S")
            with db() as c:
                wb=c.execute("SELECT id,max_user_id,full_name FROM users WHERE (last_winback IS NULL OR last_winback='' OR last_winback<?) AND (last_visit IS NULL OR last_visit<?) AND created_at<?",(cd_cut,wb_cut,wb_cut)).fetchall()
            for r in wb:
                with db() as c:
                    _batch(c,r["id"],WINBACK_BONUS,"winback",HAND+" РњС‹ СЃРєСѓС‡Р°Р»Рё",7)
                    c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",(r["id"],"accrual",WINBACK_BONUS,HAND+" РњС‹ СЃРєСѓС‡Р°Р»Рё"))
                    c.execute("UPDATE users SET last_winback=? WHERE id=?",(now.strftime("%Y-%m-%d %H:%M:%S"),r["id"]))
                send_text(int(r["max_user_id"]),f"{HAND} {r['full_name'] or 'Р”СЂСѓРі'}, РјС‹ СЃРєСѓС‡Р°РµРј! Р’Р°СЃ РґР°РІРЅРѕ РЅРµ Р±С‹Р»Рѕ.\n{GIFT} Р”Р°СЂРёРј {WINBACK_BONUS} Р±Р°Р»Р»РѕРІ - СЃРіРѕСЂСЏС‚ С‡РµСЂРµР· 7 РґРЅ. Р—Р°РіР»СЏРЅРёС‚Рµ! {CUP}")
                time.sleep(0.6)
        except Exception as e: log.error("[expire] %s",e)
        time.sleep(3600)

def process_update(d):
    m=d.get("marker")
    key=m if m is not None else (d.get("update_type"),d.get("timestamp"),_sender(d).get("user_id"),((d.get("message") or {}).get("body") or {}).get("text",""))
    if DEDUP.seen(key): return
    if d.get("update_type")=="message_callback":
        u=_sender(d); uid=u.get("user_id") or ((d.get("message") or {}).get("recipient") or {}).get("user_id")
        payload=(d.get("callback") or {}).get("payload") or d.get("payload") or ""
        if uid and payload:
            log.info("[+] callback %s: %s",uid,payload)
            r=handle_callback(uid,payload,u.get("first_name",""))
            if r["buttons"]: send_buttons(int(uid),r["text"],r["buttons"])
            else: send_text(int(uid),r["text"])
        return
    inc=parse_incoming(d)
    if not inc: return
    log.info("[+] %s: %r",inc["uid"],inc["text"])
    r=handle_message(str(inc["uid"]),inc["text"],inc["name"],inc.get("payload",""))
    if r["buttons"]: send_buttons(inc["uid"],r["text"],r["buttons"])
    else: send_text(inc["uid"],r["text"])
def poller_loop():
    log.info("[main] Long Polling")
    while True:
        try:
            for d in get_updates(): process_update(d)
        except Exception as e: log.error("[poller] %s",e)
        time.sleep(2)

_started=False
@asynccontextmanager
async def lifespan(app):
    global _started
    init_db(); migrate()
    if not _started:
        _started=True
        if WEBHOOK_URL: setup_webhook()
        else: threading.Thread(target=poller_loop,daemon=True).start()
        threading.Thread(target=expire_loop,daemon=True).start()
    yield
app=FastAPI(lifespan=lifespan)
@app.get("/")
def health(): return {"status":"ok"}
@app.post("/max/webhook")
async def webhook(request:Request,x_max_bot_api_secret:str|None=Header(default=None)):
    if WEBHOOK_SEC and x_max_bot_api_secret!=WEBHOOK_SEC: raise HTTPException(401,"Bad signature")
    try: d=await request.json()
    except Exception: raise HTTPException(400,"Bad JSON")
    await asyncio.to_thread(process_update,d)
    return {"ok":True}

def make_table_qr():
    try: me=http.get(f"{API}/me",headers=H,timeout=10).json()
    except Exception as e: print("API /me РЅРµРґРѕСЃС‚СѓРїРµРЅ:",e); return
    uname=me.get("username") or str(me.get("user_id",""))
    qrcode.make(f"https://max.ru/{uname}?payload=show_card").save("table_qr.png")
    print("QR СЃРѕС…СЂР°РЅС‘РЅ: table_qr.png")
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="qr": make_table_qr()
    else: uvicorn.run(app,host="127.0.0.1",port=8000)
