import os
import psycopg2
import psycopg2.extras
from datetime import datetime, date

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_connection():
    url = DATABASE_URL
    if url and "sslmode" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}sslmode=require"
    conn = psycopg2.connect(url)
    return conn


def _serialize(row: dict) -> dict:
    """Convert datetime/date objects to ISO strings so templates can slice them."""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, date):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            market_hash_name TEXT NOT NULL,
            app_id INTEGER DEFAULT 440,
            enabled INTEGER DEFAULT 1,
            steam_url TEXT,
            image_url TEXT,
            added_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(app_id, market_hash_name)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
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
            created_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            level TEXT DEFAULT 'info',
            message TEXT NOT NULL,
            item_name TEXT,
            mode TEXT DEFAULT 'TEST',
            stage TEXT,
            created_at TIMESTAMP DEFAULT NOW()
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
            id SERIAL PRIMARY KEY,
            balance REAL NOT NULL,
            mode TEXT DEFAULT 'TEST',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS api_logs (
            id SERIAL PRIMARY KEY,
            endpoint TEXT NOT NULL,
            params TEXT,
            status_code INTEGER,
            response TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT NOW()
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
        c.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}


def get_items():
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM items WHERE enabled = 1 ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return [_serialize(dict(row)) for row in rows]


def add_item(name, market_hash_name, app_id=440, steam_url=None, image_url=None):
    conn = get_connection()
    c = conn.cursor()
    url = steam_url or f"https://steamcommunity.com/market/listings/{app_id}/{market_hash_name.replace(' ', '%20')}"
    try:
        c.execute(
            "INSERT INTO items (name, market_hash_name, app_id, steam_url, image_url) VALUES (%s, %s, %s, %s, %s)",
            (name, market_hash_name, app_id, url, image_url)
        )
        conn.commit()
        return True, "Предмет добавлен"
    except psycopg2.IntegrityError:
        conn.rollback()
        c.execute("UPDATE items SET enabled=1 WHERE market_hash_name=%s AND app_id=%s", (market_hash_name, app_id))
        conn.commit()
        return True, "Предмет уже существует, активирован"
    finally:
        conn.close()


def remove_item(item_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE items SET enabled=0 WHERE id=%s", (item_id,))
    conn.commit()
    conn.close()


def add_log(message, level="info", item_name=None, mode="TEST", stage=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO logs (level, message, item_name, mode, stage) VALUES (%s, %s, %s, %s, %s)",
        (level, message, item_name, mode, stage)
    )
    conn.commit()
    conn.close()


def get_logs(limit=100):
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM (SELECT * FROM logs ORDER BY id DESC LIMIT %s) sub ORDER BY id ASC", (limit,))
    rows = c.fetchall()
    conn.close()
    return [_serialize(dict(row)) for row in rows]


def add_trade(item_name, market_hash_name, trade_type, buy_price=None, sell_price=None,
              market_price=None, profit=None, profit_after_fee=None, status="completed", test_mode=True):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO trades
           (item_name, market_hash_name, trade_type, buy_price, sell_price,
            market_price, profit, profit_after_fee, status, test_mode, completed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (item_name, market_hash_name, trade_type, buy_price, sell_price,
         market_price, profit, profit_after_fee, status, 1 if test_mode else 0,
         datetime.now())
    )
    conn.commit()
    conn.close()


def get_trades(limit=50, test_mode=None):
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if test_mode is None:
        c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT %s", (limit,))
    else:
        c.execute("SELECT * FROM trades WHERE test_mode=%s ORDER BY id DESC LIMIT %s",
                  (1 if test_mode else 0, limit))
    rows = c.fetchall()
    conn.close()
    return [_serialize(dict(row)) for row in rows]


def get_statistics(test_mode=None):
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    today = datetime.now().date()

    if test_mode is None:
        c.execute("""SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN trade_type='buy' THEN 1 ELSE 0 END) as total_buys,
            SUM(CASE WHEN trade_type='sell' THEN 1 ELSE 0 END) as total_sells,
            SUM(CASE WHEN trade_type='sell' THEN profit_after_fee ELSE 0 END) as total_profit,
            SUM(CASE WHEN trade_type='sell' AND DATE(created_at) = %s THEN profit_after_fee ELSE 0 END) as daily_profit
            FROM trades WHERE status='completed'""",
            (today,)
        )
    else:
        c.execute("""SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN trade_type='buy' THEN 1 ELSE 0 END) as total_buys,
            SUM(CASE WHEN trade_type='sell' THEN 1 ELSE 0 END) as total_sells,
            SUM(CASE WHEN trade_type='sell' THEN profit_after_fee ELSE 0 END) as total_profit,
            SUM(CASE WHEN trade_type='sell' AND DATE(created_at) = %s THEN profit_after_fee ELSE 0 END) as daily_profit
            FROM trades WHERE status='completed' AND test_mode=%s""",
            (today, 1 if test_mode else 0)
        )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


def add_balance_history(balance, mode):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO balance_history (balance, mode) VALUES (%s, %s)", (balance, mode))
    conn.commit()
    conn.close()


def add_api_log(endpoint: str, params: dict, status: int, response: dict, error: str = None):
    conn = get_connection()
    c = conn.cursor()
    import json as _json
    c.execute(
        "INSERT INTO api_logs (endpoint, params, status_code, response, error) VALUES (%s, %s, %s, %s, %s)",
        (endpoint, _json.dumps(params, ensure_ascii=False), status,
         _json.dumps(response, ensure_ascii=False) if response else None, error)
    )
    conn.commit()
    conn.close()


def get_api_logs(limit=200):
    conn = get_connection()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM (SELECT * FROM api_logs ORDER BY id DESC LIMIT %s) sub ORDER BY id ASC", (limit,))
    rows = c.fetchall()
    conn.close()
    return [_serialize(dict(row)) for row in rows]
