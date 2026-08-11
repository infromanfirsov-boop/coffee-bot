"""Тесты для кофейного бота. Запуск: ./venv/bin/python -m pytest test_bot.py -v"""
import os, tempfile, sys
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["MAX_BOT_TOKEN"] = "test"
import main

def test_norm_phone():
    assert main.norm_phone("+7 999 123-45-67") == "79991234567"
    assert main.norm_phone("89991234567") == "79991234567"
    assert main.norm_phone("9991234567") == "79991234567"
    assert main.norm_phone("123") is None

def test_pct():
    assert main.pct(0) == 3
    assert main.pct(10) == 5
    assert main.pct(30) == 7
    assert main.pct(60) == 10

def test_lvl_name():
    assert "Новичок" in main.lvl_name(0)
    assert "VIP" in main.lvl_name(60)

def test_progress_bar():
    bar = main.progress_bar(5)
    assert "5/10" in bar

def test_cashback():
    main.init_db()
    u = main.ensure_user("test_user_1", "Тест Тестов", 0)
    r = main.apply_cashback(u, 1000, ["латте"])
    bal = main.balance(u["id"])
    assert bal >= 30  # 3% от 1000
    assert u["id"] > 0

def test_spend_points():
    main.init_db()
    u = main.ensure_user("test_user_2", "Тест2", 0)
    # Начислим 100 баллов
    with main.db() as c:
        main._batch(c, u["id"], 100, "test", "тест")
        c.execute("INSERT INTO transactions(user_id,type,points,comment) VALUES(?,?,?,?)",
                  (u["id"], "accrual", 100, "тест"))
    ok, new_bal = main.spend_points(u["id"], 50, "списание")
    assert ok is True
    assert new_bal == 50

def test_find_user():
    main.init_db()
    u = main.ensure_user("test_user_3", "Алексей Тестов", 0)
    with main.db() as c:
        c.execute("UPDATE users SET phone=? WHERE id=?", ("79991112233", u["id"]))
    found = main.find_user("алексей")
    assert found is not None
    assert found["max_user_id"] == "test_user_3"
    found2 = main.find_user("1112233")
    assert found2 is not None
