import os, tempfile
os.environ["DB_PATH"]=tempfile.mktemp(suffix=".db")
os.environ["MAX_BOT_TOKEN"]="x"
import main

def setup_module():
    main.init_db(); main.migrate()

def test_phone():
    assert main.norm_phone("89991234567")=="79991234567"
    assert main.norm_phone("+7 999 123-45-67")=="79991234567"
    assert main.norm_phone("9991234567")=="79991234567"

def test_pct():
    assert main.pct(0)==3 and main.pct(10)==5 and main.pct(30)==7 and main.pct(60)==10

def test_search_name_lc():
    u=main.ensure_user("t1","Тест Тестович",0)
    assert main.find_user("тест")["id"]==u["id"]
    assert main.find_user("ТЕСТ")["id"]==u["id"]

def test_cashback_balance():
    u=main.ensure_user("t2","Иван",0)
    main.apply_cashback(u,1000)
    assert main.balance(u["id"])>=30

def test_spend():
    u=main.ensure_user("t3","Пётр",0)
    main.apply_cashback(u,2000)
    b=main.balance(u["id"])
    ok,nb=main.spend_points(u["id"],10)
    assert ok and nb==b-10
