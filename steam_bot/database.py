import os
import json
from datetime import datetime, date, timedelta
from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING

MONGO_URL = os.environ.get("MONGO_URL", "")
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "steam_bot")

_client = None
_db = None


def _get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URL)
        _db = _client[MONGO_DB_NAME]
    return _db


def _serialize(doc: dict) -> dict:
    result = {}
    for k, v in doc.items():
        if k == "_id":
            result["id"] = str(v)
        elif isinstance(v, ObjectId):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, date):
            result[k] = v.isoformat()
        else:
            result[k] = v
    if "id" not in result and "_id" not in doc:
        result["id"] = ""
    return result


def _next_id(collection_name: str) -> int:
    db = _get_db()
    counter = db.counters.find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return counter["seq"]


def init_db():
    db = _get_db()

    db.items.create_index([("app_id", ASCENDING), ("market_hash_name", ASCENDING)], unique=True)
    db.items.create_index([("enabled", ASCENDING), ("name", ASCENDING)])
    db.trades.create_index([("created_at", DESCENDING)])
    db.trades.create_index([("test_mode", ASCENDING), ("status", ASCENDING)])
    db.logs.create_index([("created_at", DESCENDING)])
    db.api_logs.create_index([("created_at", DESCENDING)])
    db.settings.create_index([("key", ASCENDING)], unique=True)

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
        db.settings.update_one(
            {"key": key},
            {"$setOnInsert": {"key": key, "value": value}},
            upsert=True
        )


def get_setting(key, default=None):
    db = _get_db()
    doc = db.settings.find_one({"key": key})
    return doc["value"] if doc else default


def set_setting(key, value):
    db = _get_db()
    db.settings.update_one(
        {"key": key},
        {"$set": {"key": key, "value": str(value)}},
        upsert=True
    )


def get_all_settings():
    db = _get_db()
    docs = db.settings.find()
    return {doc["key"]: doc["value"] for doc in docs}


def get_items():
    db = _get_db()
    docs = db.items.find({"enabled": 1}).sort("name", ASCENDING)
    results = []
    for doc in docs:
        item = _serialize(doc)
        item["id"] = doc.get("item_id", 0)
        results.append(item)
    return results


def add_item(name, market_hash_name, app_id=440, steam_url=None, image_url=None):
    db = _get_db()
    url = steam_url or f"https://steamcommunity.com/market/listings/{app_id}/{market_hash_name.replace(' ', '%20')}"
    existing = db.items.find_one({"app_id": app_id, "market_hash_name": market_hash_name})
    if existing:
        db.items.update_one(
            {"_id": existing["_id"]},
            {"$set": {"enabled": 1}}
        )
        return True, "Предмет уже существует, активирован"
    item_id = _next_id("items")
    db.items.insert_one({
        "item_id": item_id,
        "name": name,
        "market_hash_name": market_hash_name,
        "app_id": app_id,
        "enabled": 1,
        "steam_url": url,
        "image_url": image_url,
        "added_at": datetime.now(),
    })
    return True, "Предмет добавлен"


def remove_item(item_id):
    db = _get_db()
    try:
        numeric_id = int(item_id)
        result = db.items.update_one({"item_id": numeric_id}, {"$set": {"enabled": 0}})
        if result.modified_count == 0:
            db.items.update_one({"_id": ObjectId(str(item_id))}, {"$set": {"enabled": 0}})
    except (ValueError, TypeError):
        db.items.update_one({"_id": ObjectId(str(item_id))}, {"$set": {"enabled": 0}})


def add_log(message, level="info", item_name=None, mode="TEST", stage=None):
    db = _get_db()
    db.logs.insert_one({
        "level": level,
        "message": message,
        "item_name": item_name,
        "mode": mode,
        "stage": stage,
        "created_at": datetime.now(),
    })


def get_logs(limit=100):
    db = _get_db()
    docs = list(db.logs.find().sort("_id", DESCENDING).limit(limit))
    docs.reverse()
    return [_serialize(doc) for doc in docs]


def add_trade(item_name, market_hash_name, trade_type, buy_price=None, sell_price=None,
              market_price=None, profit=None, profit_after_fee=None, status="completed", test_mode=True):
    db = _get_db()
    db.trades.insert_one({
        "item_name": item_name,
        "market_hash_name": market_hash_name,
        "trade_type": trade_type,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "market_price": market_price,
        "profit": profit,
        "profit_after_fee": profit_after_fee,
        "status": status,
        "test_mode": 1 if test_mode else 0,
        "created_at": datetime.now(),
        "completed_at": datetime.now() if status == "completed" else None,
    })


def get_trades(limit=50, test_mode=None):
    db = _get_db()
    query = {}
    if test_mode is not None:
        query["test_mode"] = 1 if test_mode else 0
    docs = db.trades.find(query).sort("_id", DESCENDING).limit(limit)
    return [_serialize(doc) for doc in docs]


def get_statistics(test_mode=None):
    db = _get_db()
    match = {"status": "completed"}
    if test_mode is not None:
        match["test_mode"] = 1 if test_mode else 0

    today_start = datetime.combine(datetime.now().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "total_trades": {"$sum": 1},
            "total_buys": {"$sum": {"$cond": [{"$eq": ["$trade_type", "buy"]}, 1, 0]}},
            "total_sells": {"$sum": {"$cond": [{"$eq": ["$trade_type", "sell"]}, 1, 0]}},
            "total_profit": {"$sum": {
                "$cond": [{"$eq": ["$trade_type", "sell"]}, {"$ifNull": ["$profit_after_fee", 0]}, 0]
            }},
            "daily_profit": {"$sum": {
                "$cond": [
                    {"$and": [
                        {"$eq": ["$trade_type", "sell"]},
                        {"$gte": ["$created_at", today_start]},
                        {"$lt": ["$created_at", today_end]},
                    ]},
                    {"$ifNull": ["$profit_after_fee", 0]},
                    0
                ]
            }},
        }}
    ]

    result = list(db.trades.aggregate(pipeline))
    if result:
        r = result[0]
        del r["_id"]
        return r
    return {
        "total_trades": 0,
        "total_buys": 0,
        "total_sells": 0,
        "total_profit": 0,
        "daily_profit": 0,
    }


def add_balance_history(balance, mode):
    db = _get_db()
    db.balance_history.insert_one({
        "balance": balance,
        "mode": mode,
        "created_at": datetime.now(),
    })


def add_api_log(endpoint: str, params: dict, status: int, response: dict, error: str = None):
    db = _get_db()
    db.api_logs.insert_one({
        "endpoint": endpoint,
        "params": json.dumps(params, ensure_ascii=False) if params else "{}",
        "status_code": status,
        "response": json.dumps(response, ensure_ascii=False) if response else None,
        "error": error,
        "created_at": datetime.now(),
    })


def get_api_logs(limit=200):
    db = _get_db()
    docs = list(db.api_logs.find().sort("_id", DESCENDING).limit(limit))
    docs.reverse()
    return [_serialize(doc) for doc in docs]
