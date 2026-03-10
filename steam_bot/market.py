import aiohttp
import asyncio
import json
import time
from steam_bot.config import STEAM_PRICE_API, STEAM_SEARCH_API, STEAM_COMMISSION

_price_cache = {}
CACHE_TTL = 30

async def get_item_price(market_hash_name: str, app_id: int = 730, currency: int = 5) -> dict:
    """
    Получение цены предмета с Steam Market API.
    currency: 1=USD, 3=EUR, 5=RUB, 18=UAH
    Возвращает dict с lowest_price, median_price, volume
    """
    cache_key = f"{app_id}:{market_hash_name}"
    now = time.time()
    if cache_key in _price_cache:
        cached_at, cached_data = _price_cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return cached_data

    params = {
        "appid": app_id,
        "market_hash_name": market_hash_name,
        "currency": currency,
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://steamcommunity.com/market/",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(STEAM_PRICE_API, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success"):
                        result = {
                            "success": True,
                            "lowest_price_raw": data.get("lowest_price", ""),
                            "median_price_raw": data.get("median_price", ""),
                            "volume": data.get("volume", "0"),
                            "lowest_price": parse_price(data.get("lowest_price", "")),
                            "median_price": parse_price(data.get("median_price", "")),
                        }
                        _price_cache[cache_key] = (now, result)
                        return result
                    else:
                        return {"success": False, "error": "Steam API вернул success=false"}
                elif resp.status == 429:
                    return {"success": False, "error": "Лимит запросов Steam API (429). Подождите..."}
                else:
                    return {"success": False, "error": f"Ошибка Steam API: HTTP {resp.status}"}
    except asyncio.TimeoutError:
        return {"success": False, "error": "Таймаут запроса к Steam API"}
    except Exception as e:
        return {"success": False, "error": f"Ошибка запроса: {str(e)}"}


def parse_price(price_str: str) -> float:
    """Парсинг цены из строки Steam (например '0,82 pуб.' или '$1.23' или '1.23€')"""
    if not price_str:
        return 0.0
    cleaned = ""
    for ch in price_str:
        if ch.isdigit() or ch in ".,":
            cleaned += ch
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(",", ".")
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def calculate_profit(buy_price: float, market_price: float) -> dict:
    """
    Расчёт прибыли с учётом комиссии Steam (15%).
    Продавец получает: sell_price * (1 - 0.15)
    Чтобы получить market_price на руки, нужно выставить цену выше.
    Прибыль = (sell_price_net) - buy_price
    """
    sell_net = market_price * (1 - STEAM_COMMISSION)
    profit = sell_net - buy_price
    profit_percent = ((market_price - buy_price) / buy_price * 100) if buy_price > 0 else 0
    net_profit_percent = (profit / buy_price * 100) if buy_price > 0 else 0

    return {
        "buy_price": buy_price,
        "market_price": market_price,
        "sell_net": round(sell_net, 2),
        "profit": round(profit, 2),
        "profit_percent": round(profit_percent, 2),
        "net_profit_percent": round(net_profit_percent, 2),
        "commission_amount": round(market_price * STEAM_COMMISSION, 2),
        "is_profitable": profit > 0,
    }


def should_buy(lowest_price: float, median_price: float, threshold_percent: float) -> tuple:
    """
    Проверяет, стоит ли покупать предмет.
    Возвращает (bool, discount_percent, reason)
    threshold_percent — минимальный процент скидки относительно медианы
    """
    if lowest_price <= 0 or median_price <= 0:
        return False, 0, "Некорректные цены"

    discount = ((median_price - lowest_price) / median_price) * 100

    profit_info = calculate_profit(lowest_price, median_price)
    net_profit_pct = profit_info["net_profit_percent"]

    if discount >= threshold_percent and net_profit_pct > 0:
        reason = f"Скидка {discount:.1f}% (порог {threshold_percent}%), чистая прибыль {net_profit_pct:.1f}% после комиссии Steam"
        return True, discount, reason
    elif discount >= threshold_percent and net_profit_pct <= 0:
        reason = f"Скидка {discount:.1f}% достаточная, но после комиссии Steam {STEAM_COMMISSION*100:.0f}% прибыли нет ({net_profit_pct:.1f}%)"
        return False, discount, reason
    else:
        reason = f"Скидка {discount:.1f}% недостаточна (порог {threshold_percent}%)"
        return False, discount, reason


async def search_item(query: str, app_id: int = 730) -> list:
    """Поиск предметов на Steam Market по названию"""
    params = {
        "appid": app_id,
        "query": query,
        "start": 0,
        "count": 10,
        "search_descriptions": 0,
        "sort_column": "popular",
        "sort_dir": "desc",
        "norender": 1,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(STEAM_SEARCH_API, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = []
                    for result in data.get("results", []):
                        name = result.get("name", "")
                        hash_name = result.get("hash_name", name)
                        sell_listings = result.get("sell_listings", 0)
                        sell_price_text = result.get("sell_price_text", "")
                        icon_url = ""
                        asset_desc = result.get("asset_description", {})
                        if asset_desc.get("icon_url"):
                            icon_url = f"https://community.akamai.steamstatic.com/economy/image/{asset_desc['icon_url']}/128x128"
                        items.append({
                            "name": name,
                            "hash_name": hash_name,
                            "sell_listings": sell_listings,
                            "price_text": sell_price_text,
                            "icon_url": icon_url,
                            "app_id": app_id,
                            "steam_url": f"https://steamcommunity.com/market/listings/{app_id}/{hash_name.replace(' ', '%20')}",
                        })
                    return items
    except Exception:
        pass
    return []
