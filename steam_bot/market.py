import aiohttp
import asyncio
import time
from steam_bot.config import STEAM_PRICE_API, STEAM_SEARCH_API, STEAM_COMMISSION

_price_cache = {}
CACHE_TTL = 30

STEAM_PRICE_HISTORY_API = "https://steamcommunity.com/market/pricehistory/"


def _log_api(endpoint: str, params: dict, status: int, response: dict = None, error: str = None):
    try:
        from steam_bot import database as db
        db.add_api_log(endpoint, params, status, response, error)
    except Exception:
        pass


async def get_item_price(market_hash_name: str, app_id: int = 730, currency: int = 5) -> dict:
    cache_key = f"{app_id}:{market_hash_name}:{currency}"
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
            async with session.get(STEAM_PRICE_API, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
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
                        _log_api("priceoverview", params, resp.status, data)
                        return result
                    else:
                        _log_api("priceoverview", params, resp.status, data, "success=false")
                        return {"success": False, "error": "Steam API вернул success=false"}
                elif resp.status == 429:
                    _log_api("priceoverview", params, 429, None, "Rate limit")
                    return {"success": False, "error": "Лимит запросов Steam API (429). Подождите..."}
                else:
                    _log_api("priceoverview", params, resp.status, None, f"HTTP {resp.status}")
                    return {"success": False, "error": f"Ошибка Steam API: HTTP {resp.status}"}
    except asyncio.TimeoutError:
        _log_api("priceoverview", params, 0, None, "Timeout")
        return {"success": False, "error": "Таймаут запроса к Steam API"}
    except Exception as e:
        _log_api("priceoverview", params, 0, None, str(e))
        return {"success": False, "error": f"Ошибка запроса: {str(e)}"}


async def get_price_history(market_hash_name: str, app_id: int = 730, currency: int = 1) -> dict:
    """Получение истории цен предмета за последние 30 дней (требует авторизации Steam)."""
    params = {
        "appid": app_id,
        "market_hash_name": market_hash_name,
        "currency": currency,
        "country": "US",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": f"https://steamcommunity.com/market/listings/{app_id}/{market_hash_name}",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(STEAM_PRICE_HISTORY_API, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _log_api("pricehistory", params, resp.status, {"prices_count": len(data.get("prices", []))})
                    if data.get("success") and data.get("prices"):
                        return {"success": True, "prices": data["prices"]}
                    return {"success": False, "error": "Нет данных истории"}
                _log_api("pricehistory", params, resp.status, None, f"HTTP {resp.status}")
                return {"success": False, "error": f"HTTP {resp.status} (требует авторизации Steam)"}
    except Exception as e:
        _log_api("pricehistory", params, 0, None, str(e))
        return {"success": False, "error": str(e)}


def analyze_price_history(prices: list, threshold_pct: float = 17.0) -> dict:
    """
    Анализ истории цен: считает сделки за 7 дней.
    prices — список [[date_str, price, count], ...]
    Возвращает статистику по продажам выше/ниже медианы.
    """
    if not prices:
        return {}

    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)

    week_prices = []
    for entry in prices:
        try:
            date_str = entry[0]
            price = float(entry[1])
            count = int(entry[2]) if len(entry) > 2 else 1
            dt = datetime.strptime(date_str[:10], "%b %d %Y")
            if dt >= cutoff:
                week_prices.extend([price] * count)
        except Exception:
            continue

    if not week_prices:
        return {"week_total": 0, "week_median": 0, "at_discount": 0, "at_median_or_above": 0}

    week_prices.sort()
    mid = len(week_prices) // 2
    median = (week_prices[mid] + week_prices[~mid]) / 2

    discount_threshold = median * (1 - threshold_pct / 100)
    at_discount = sum(1 for p in week_prices if p <= discount_threshold)
    at_median_or_above = sum(1 for p in week_prices if p >= median * 0.95)

    return {
        "week_total": len(week_prices),
        "week_median": round(median, 4),
        "at_discount": at_discount,
        "at_median_or_above": at_median_or_above,
        "discount_pct": round(at_discount / len(week_prices) * 100, 1) if week_prices else 0,
    }


def parse_price(price_str: str) -> float:
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
    if lowest_price <= 0 or median_price <= 0:
        return False, 0, "Некорректные цены"
    discount = ((median_price - lowest_price) / median_price) * 100
    profit_info = calculate_profit(lowest_price, median_price)
    net_profit_pct = profit_info["net_profit_percent"]
    if discount >= threshold_percent and net_profit_pct > 0:
        reason = f"Скидка {discount:.1f}% (порог {threshold_percent}%), чистая прибыль {net_profit_pct:.1f}%"
        return True, discount, reason
    elif discount >= threshold_percent and net_profit_pct <= 0:
        reason = f"Скидка {discount:.1f}% достаточная, но после комиссии прибыли нет ({net_profit_pct:.1f}%)"
        return False, discount, reason
    else:
        reason = f"Скидка {discount:.1f}% недостаточна (порог {threshold_percent}%)"
        return False, discount, reason


async def search_item(query: str, app_id: int = 730) -> list:
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
            async with session.get(STEAM_SEARCH_API, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _log_api("search", {"query": query, "appid": app_id}, resp.status,
                             {"total": data.get("total_count", 0)})
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
                _log_api("search", params, resp.status, None, f"HTTP {resp.status}")
    except Exception as e:
        _log_api("search", {"query": query, "appid": app_id}, 0, None, str(e))
    return []


async def scan_market(query: str, app_id: int = 730, currency: int = 5,
                      min_price_usd: float = 1.0, threshold_pct: float = 17.0,
                      count: int = 20) -> list:
    """
    Сканирует рынок Steam, находит предметы с хорошим потенциалом.
    Возвращает список предметов с ценами, скидкой, историей.
    """
    search_params = {
        "appid": app_id,
        "query": query,
        "start": 0,
        "count": count,
        "search_descriptions": 0,
        "sort_column": "popular",
        "sort_dir": "desc",
        "norender": 1,
        "currency": currency,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://steamcommunity.com/market/",
    }

    search_results = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(STEAM_SEARCH_API, params=search_params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _log_api("scanner/search", {"query": query, "appid": app_id, "count": count},
                             resp.status, {"total": data.get("total_count", 0),
                                           "results": len(data.get("results", []))})
                    for result in data.get("results", []):
                        hash_name = result.get("hash_name", result.get("name", ""))
                        sell_price = result.get("sell_price", 0)
                        sell_price_usd = sell_price / 100.0
                        asset_desc = result.get("asset_description", {})
                        icon_url = ""
                        if asset_desc.get("icon_url"):
                            icon_url = f"https://community.akamai.steamstatic.com/economy/image/{asset_desc['icon_url']}/128x128"
                        search_results.append({
                            "name": result.get("name", ""),
                            "hash_name": hash_name,
                            "app_id": app_id,
                            "sell_listings": result.get("sell_listings", 0),
                            "sell_price_usd": sell_price_usd,
                            "icon_url": icon_url,
                            "steam_url": f"https://steamcommunity.com/market/listings/{app_id}/{hash_name.replace(' ', '%20')}",
                        })
                else:
                    _log_api("scanner/search", search_params, resp.status, None, f"HTTP {resp.status}")
    except Exception as e:
        _log_api("scanner/search", search_params, 0, None, str(e))
        return []

    results = []
    for item in search_results:
        if item["sell_price_usd"] < min_price_usd:
            continue

        price_data = await get_item_price(item["hash_name"], app_id, currency)
        await asyncio.sleep(0.5)

        if not price_data.get("success"):
            continue

        lowest = price_data["lowest_price"]
        median = price_data["median_price"]
        volume_str = price_data.get("volume", "0").replace(",", "")
        try:
            volume = int(volume_str)
        except Exception:
            volume = 0

        if lowest <= 0 or median <= 0:
            continue

        discount = ((median - lowest) / median) * 100
        profit_info = calculate_profit(lowest, median)

        history_stats = {}
        history_data = await get_price_history(item["hash_name"], app_id, 1)
        await asyncio.sleep(0.3)
        if history_data.get("success"):
            history_stats = analyze_price_history(history_data["prices"], threshold_pct)

        results.append({
            "name": item["name"],
            "hash_name": item["hash_name"],
            "app_id": app_id,
            "icon_url": item["icon_url"],
            "steam_url": item["steam_url"],
            "sell_listings": item["sell_listings"],
            "lowest_price": lowest,
            "lowest_price_raw": price_data["lowest_price_raw"],
            "median_price": median,
            "median_price_raw": price_data["median_price_raw"],
            "volume": volume,
            "volume_raw": price_data.get("volume", "0"),
            "discount_pct": round(discount, 1),
            "net_profit_pct": profit_info["net_profit_percent"],
            "profit": profit_info["profit"],
            "has_discount": discount >= threshold_pct,
            "is_profitable": profit_info["is_profitable"] and discount >= threshold_pct,
            "history": history_stats,
        })

    results.sort(key=lambda x: (not x["is_profitable"], -x["discount_pct"], -x["volume"]))
    return results
