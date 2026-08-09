"""Одноразовый скрипт: вносит улучшения в main.py (v26).
Запуск: ./venv/bin/python upgrade.py
"""
import re, os, shutil
P = "main.py"
shutil.copy(P, P + ".bak25")
src = open(P, encoding="utf-8").read()

# 1. Импорты
src = src.replace(
    "from collections import OrderedDict",
    "from collections import OrderedDict, defaultdict"
)
src = src.replace(
    "from fastapi import FastAPI, Header, HTTPException, Request",
    "from fastapi import FastAPI, Header, HTTPException, Request, Query\nfrom fastapi.middleware.cors import CORSMiddleware\nfrom pydantic import BaseModel\ntry:\n    import openpyxl\nexcept ImportError:\n    openpyxl=None\nBASE=os.path.dirname(os.path.abspath(__file__))"
)

# 2. load_dotenv с путём
src = src.replace(
    "load_dotenv()",
    "load_dotenv(os.path.join(BASE,\".env\"),override=True)"
)

# 3. Read-only коннектор (вставить после def db())
db_block = """@contextmanager
def db():
    c=_conn()
    try:
        yield c; c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()"""
db_ro = """
@contextmanager
def db_ro():
    c=sqlite3.connect(f"file:{DB}?mode=ro",uri=True,timeout=30); c.row_factory=sqlite3.Row
    try: yield c
    finally: c.close()"""
src = src.replace(db_block, db_block + db_ro)

# 4. Индекс i_pbe
if "i_pbe" not in src:
    src = src.replace(
        "CREATE INDEX IF NOT EXISTS i_be ON points_batches(expires_at);",
        "CREATE INDEX IF NOT EXISTS i_be ON points_batches(expires_at);CREATE INDEX IF NOT EXISTS i_pbe ON points_batches(expires_at,points_left);"
    )

# 5. TTLCache + rate-limit + bump (вставить перед class Dedup)
cache_code = """
class TTLCache:
    def __init__(s,ttl=5): s.ttl,s.d=ttl,{}
    def get(s,k):
        e=s.d.get(k)
        if e and time.time()-e[1]<s.ttl: return e[0]
        return None
    def set(s,k,v): s.d[k]=(v,time.time())
    def drop(s,k): s.d.pop(k,None)
BAL=TTLCache(5); RATE=defaultdict(list)
def bump(key,n=1):
    k=f"cnt_{datetime.now():%Y%m%d}_{key}"
    with db() as c: c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+?",(k,n,n))

"""
if "class TTLCache" not in src:
    src = src.replace("class Dedup:", cache_code + "class Dedup:")

# 6. Кэш в _batch и spend_points
if "BAL.drop(uid)" not in src:
    src = src.replace(
        "c.execute(\"INSERT INTO points_batches(user_id,points_left,original_points,source,comment,expires_at) VALUES(?,?,?,?,?,?)\",",
        "c.execute(\"INSERT INTO points_batches(user_id,points_left,original_points,source,comment,expires_at) VALUES(?,?,?,?,?,?)\","
    )
    src = src.replace(
        "datetime.now()+timedelta(days=days or EXPIRE_DAYS)))\n",
        "datetime.now()+timedelta(days=days or EXPIRE_DAYS)))\n    BAL.drop(uid)\n",
        1
    )
    src = src.replace(
        "c.execute(\"INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)\",(uid,\"writeoff\",-points,comment or CARD+\" Списание\"))\n        return True,bal-points",
        "c.execute(\"INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)\",(uid,\"writeoff\",-points,comment or CARD+\" Списание\"))\n        BAL.drop(uid)\n        return True,bal-points"
    )

# 7. Кэш в balance()
old_bal = "def balance(uid):\n    with db() as c: return int(c.execute"
new_bal = "def balance(uid):\n    v0=BAL.get(uid)\n    if v0 is not None: return v0\n    with db() as c: v=int(c.execute"
src = src.replace(old_bal, new_bal)
src = src.replace(
    "(uid,datetime.now())).fetchone()[\"b\"])",
    "(uid,datetime.now())).fetchone()[\"b\"])\n    BAL.set(uid,v); return v",
    1
)

# 8. Read-only для аналитики
for fn in ["def top_items", "def abc_analysis", "def rfm_analysis", "def export_csv"]:
    src = src.replace(f"{fn}(limit=10):\n    with db() as c:", f"{fn}(limit=10):\n    with db_ro() as c:", 1) if "def top" in fn else src
src = src.replace("def abc_analysis():\n    with db() as c:", "def abc_analysis():\n    with db_ro() as c:")
src = src.replace("def rfm_analysis():\n    now=datetime.now()\n    with db() as c:", "def rfm_analysis():\n    now=datetime.now()\n    with db_ro() as c:")
src = src.replace("def export_csv():\n    with db() as c:", "def export_csv():\n    with db_ro() as c:")

# 9. CORS middleware (вставить после app=FastAPI(lifespan=lifespan))
src = src.replace(
    "app=FastAPI(lifespan=lifespan)",
    "app=FastAPI(lifespan=lifespan)\napp.add_middleware(CORSMiddleware,allow_origins=[\"https://утро-кофе.рф\",\"https://xn----jtboocinhp.xn--p1ai\",\"http://127.0.0.1:8000\"],allow_methods=[\"GET\",\"POST\"],allow_headers=[])"
)

# 10. Pydantic + rate-limit для /api/card
old_api = """@app.get("/api/card")
def api_card(phone:str=""):
    d="".join(ch for ch in phone if ch.isdigit())
    if len(d)<4: return {"ok":False}
    with db() as c:
        r=c.execute("SELECT id,visits_count FROM users WHERE phone LIKE ?",(f"%{d[-10:]}",)).fetchone()
        if not r: return {"ok":False}
        bal=balance(r["id"]); v=r["visits_count"]
    return {"ok":True,"points":bal,"visits":v,"level":lvl_name(v),"pct":pct(v)}"""
new_api = """class CardResponse(BaseModel):
    ok:bool; points:int=0; visits:int=0; level:str=""; pct:int=0
@app.get("/api/card",response_model=CardResponse)
def api_card(request:Request,phone:str=Query(default="",max_length=20)):
    ip=request.client.host or ""
    now=time.time()
    RATE[ip]=[t for t in RATE[ip] if now-t<60]
    if len(RATE[ip])>20: return CardResponse(ok=False)
    RATE[ip].append(now)
    d="".join(ch for ch in phone if ch.isdigit())
    if len(d)<4: return CardResponse(ok=False)
    with db() as c:
        r=c.execute("SELECT id,visits_count FROM users WHERE phone LIKE ?",(f"%{d[-10:]}",)).fetchone()
        if not r: return CardResponse(ok=False)
        bal=balance(r["id"]); v=r["visits_count"]
    return CardResponse(ok=True,points=bal,visits=v,level=lvl_name(v),pct=pct(v))"""
src = src.replace(old_api, new_api)

# 11. PWA роуты (перед @app.get("/health"))
pwa_routes = """@app.get("/sw.js")
def sw(): return FileResponse(os.path.join(BASE,"site","sw.js"),media_type="text/javascript")
@app.get("/manifest.webmanifest")
def manifest(): return FileResponse(os.path.join(BASE,"site","manifest.webmanifest"),media_type="application/manifest+json")
"""
if "/sw.js" not in src:
    src = src.replace('@app.get("/health")', pwa_routes + '@app.get("/health")')

# 12. Excel в do_export_files
if "openpyxl" not in src:
    src = src.replace(
        '    return rep(f"{EXPORT} Файлы готовы:',
        '    if openpyxl:\n        try:\n            wb=openpyxl.Workbook(); ws=wb.active; ws.title="Клиенты"\n            ws.append(["ID","Имя","Телефон","Карта","Посещений","Потрачено","Баллы","ДР"])\n            for r in users: ws.append([r["id"],r["full_name"] or "",r["phone"] or "",r["card_number"],r["visits_count"],round(r["total_spent"]),int(r["bal"]),r["birthday"]])\n            wb.save(f"clients_{ts}.xlsx")\n        except Exception as e: log.error("[xlsx] %s",e)\n    return rep(f"{EXPORT} Файлы готовы:'
    )

# 13. Метрики в /status
old_status = 'f"{CHART} Режим: {\'webhook\' if WEBHOOK_URL else \'polling\'}")\n    return rep(t,back())'
new_status = 'f"{CHART} Режим: {\'webhook\' if WEBHOOK_URL else \'polling\'}"\n    td=datetime.now().strftime("%Y%m%d")\n    t+=f"\\n{CHART} Сегодня: сообщений {kv_get(f\'cnt_{td}_msg\',\'0\')} · кнопок {kv_get(f\'cnt_{td}_cb\',\'0\')}")\n    return rep(t,back())'
if "cnt_" not in src:
    src = src.replace(old_status, new_status)

# 14. bump() в process_update
if 'bump("cb")' not in src:
    src = src.replace(
        'log.info("[+] callback %s: %s",uid,payload)',
        'log.info("[+] callback %s: %s",uid,payload); bump("cb")'
    )
    src = src.replace(
        'log.info("[+] %s: %r",inc["uid"],inc["text"])',
        'log.info("[+] %s: %r",inc["uid"],inc["text"]); bump("msg")'
    )

open(P, "w", encoding="utf-8").write(src)
print("OK. Бекап:", P + ".bak25")
print("Проверка: ./venv/bin/python main.py test")
