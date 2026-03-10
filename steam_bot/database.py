import sqlite3
import os
from datetime import datetime

DB_PATH = "steam_bot.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            market_hash_name TEXT NOT NULL UNIQUE,
            app_id INTEGER DEFAULT 730,
            enabled INTEGER DEFAULT 1,
            steam_url TEXT,
            image_url TEXT,
            added_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            market_hash_name TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            buy_price REAL,
            sell_price REAL,
            market_price REAL,
            profit REAL,
            profit_after_fee REAL,
            status TEXT DEFAULT 'pending',
            test_mode INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT DEFAULT 'info',
            message TEXT NOT NULL,
            item_name TEXT,
            mode TEXT DEFAULT 'TEST',
            stage TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS balance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance REAL NOT NULL,
            mode TEXT DEFAULT 'TEST',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    defaults = {
        "steam_api_key": "",
        "steam_login": "",
        "steam_password": "",
        "steam_shared_secret": "",
        "steam_identity_secret": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "buy_threshold": "17",
        "check_interval": "15",
        "max_buys_per_hour": "10",
        "sell_strategy": "market",
        "sell_discount": "1",
        "test_mode": "1",
        "virtual_balance": "1000",
        "current_virtual_balance": "1000",
        "bot_running": "0",
        "steam_currency": "5",
    }

    for key, value in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def get_items():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM items WHERE enabled = 1 ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_item(name, market_hash_name, app_id=730, steam_url=None, image_url=None):
    conn = get_connection()
    c = conn.cursor()
    url = steam_url or f"https://steamcommunity.com/market/listings/{app_id}/{market_hash_name.replace(' ', '%20')}"
    try:
        c.execute(
            "INSERT INTO items (name, market_hash_name, app_id, steam_url, image_url) VALUES (?, ?, ?, ?, ?)",
            (name, market_hash_name, app_id, url, image_url)
        )
        conn.commit()
        return True, "Предмет добавлен"
    except sqlite3.IntegrityError:
        c.execute("UPDATE items SET enabled=1 WHERE market_hash_name=?", (market_hash_name,))
        conn.commit()
        return True, "Предмет уже существует, активирован"
    finally:
        conn.close()

def remove_item(item_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE items SET enabled=0 WHERE id=?", (item_id,))
    conn.commit()
    conn.close()

def add_log(message, level="info", item_name=None, mode="TEST", stage=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO logs (level, message, item_name, mode, stage) VALUES (?, ?, ?, ?, ?)",
        (level, message, item_name, mode, stage)
    )
    conn.commit()
    conn.close()

def get_logs(limit=100):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in reversed(rows)]

def add_trade(item_name, market_hash_name, trade_type, buy_price=None, sell_price=None,
              market_price=None, profit=None, profit_after_fee=None, status="completed", test_mode=True):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO trades
           (item_name, market_hash_name, trade_type, buy_price, sell_price,
            market_price, profit, profit_after_fee, status, test_mode, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_name, market_hash_name, trade_type, buy_price, sell_price,
         market_price, profit, profit_after_fee, status, 1 if test_mode else 0,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_trades(limit=50, test_mode=None):
    conn = get_connection()
    c = conn.cursor()
    if test_mode is None:
        c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
    else:
        c.execute("SELECT * FROM trades WHERE test_mode=? ORDER BY id DESC LIMIT ?",
                  (1 if test_mode else 0, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_statistics(test_mode=None):
    conn = get_connection()
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    if test_mode is None:
        filter_clause = ""
        params_all = ()
        params_today = (today + "%",)
    else:
        tm_val = 1 if test_mode else 0
        filter_clause = f"AND test_mode={tm_val}"
        params_all = ()
        params_today = (today + "%",)

    c.execute(f"""SELECT
        COUNT(*) as total_trades,
        SUM(CASE WHEN trade_type='buy' THEN 1 ELSE 0 END) as total_buys,
        SUM(CASE WHEN trade_type='sell' THEN 1 ELSE 0 END) as total_sells,
        SUM(CASE WHEN trade_type='sell' THEN profit_after_fee ELSE 0 END) as total_profit,
        SUM(CASE WHEN trade_type='sell' AND created_at LIKE ? THEN profit_after_fee ELSE 0 END) as daily_profit
        FROM trades WHERE status='completed' {filter_clause}""",
        params_today
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}

def add_balance_history(balance, mode):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO balance_history (balance, mode) VALUES (?, ?)", (balance, mode))
    conn.commit()
    conn.close()
