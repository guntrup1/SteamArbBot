import os
from dotenv import load_dotenv

load_dotenv()

SESSION_SECRET = os.getenv("SESSION_SECRET", "steam_bot_secret_key_2024")

HOST = "0.0.0.0"
PORT = 5000

STEAM_COMMISSION = 0.15

MIN_BUY_THRESHOLD = 17.0
MAX_BUY_THRESHOLD = 50.0

DEFAULT_CHECK_INTERVAL = 15
MIN_CHECK_INTERVAL = 10
MAX_CHECK_INTERVAL = 60

DEFAULT_MAX_BUYS_PER_HOUR = 10

DEFAULT_MIN_PRICE_USD = 0.20

MIN_WEEKLY_SALES = 600

APP_ID_TF2 = 440
APP_ID_DOTA2 = 570

SUPPORTED_APPS = {
    "440": "Team Fortress 2",
    "570": "Dota 2",
}

STEAM_MARKET_BASE = "https://steamcommunity.com/market"
STEAM_PRICE_API = "https://steamcommunity.com/market/priceoverview/"
STEAM_LISTINGS_API = "https://steamcommunity.com/market/listings/"
STEAM_SEARCH_API = "https://steamcommunity.com/market/search/render/"
STEAM_BUY_API = "https://steamcommunity.com/market/buylisting/"
STEAM_ORDERS_HISTOGRAM_API = "https://steamcommunity.com/market/itemordershistogram"

CURRENCY_INFO = {
    "1":  {"symbol": "$",  "code": "USD", "name": "Доллар США"},
    "3":  {"symbol": "€",  "code": "EUR", "name": "Евро"},
    "5":  {"symbol": "₽",  "code": "RUB", "name": "Рубль"},
    "18": {"symbol": "₴",  "code": "UAH", "name": "Гривна"},
    "2":  {"symbol": "£",  "code": "GBP", "name": "Фунт стерлингов"},
}

def get_currency_symbol(currency_code: str) -> str:
    return CURRENCY_INFO.get(str(currency_code), {}).get("symbol", "₽")

def get_currency_code(currency_code: str) -> str:
    return CURRENCY_INFO.get(str(currency_code), {}).get("code", "RUB")

LOG_LEVELS = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "trade": "💰",
}

VERSION = "2.0.0"
