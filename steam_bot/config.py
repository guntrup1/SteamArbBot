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

APP_ID_CS2 = 730
APP_ID_DOTA2 = 570
APP_ID_TF2 = 440

SUPPORTED_APPS = {
    "730": "Counter-Strike 2",
    "570": "Dota 2",
    "440": "Team Fortress 2",
    "252490": "Rust",
    "578080": "PUBG",
}

STEAM_MARKET_BASE = "https://steamcommunity.com/market"
STEAM_PRICE_API = "https://steamcommunity.com/market/priceoverview/"
STEAM_LISTINGS_API = "https://steamcommunity.com/market/listings/"
STEAM_SEARCH_API = "https://steamcommunity.com/market/search/render/"
STEAM_BUY_API = "https://steamcommunity.com/market/buylisting/"

LOG_LEVELS = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "trade": "💰",
}

VERSION = "1.0.0"
