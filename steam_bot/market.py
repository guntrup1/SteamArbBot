import aiohttp
import asyncio
import time
import random
from steam_bot.config import STEAM_PRICE_API, STEAM_SEARCH_API, STEAM_COMMISSION

_price_cache = {}
CACHE_TTL = 300

STEAM_PRICE_HISTORY_API = "https://steamcommunity.com/market/pricehistory/"

_STEAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://steamcommunity.com/market/",
    "X-Requested-With": "XMLHttpRequest",
}

_steam_sem = asyncio.Semaphore(1)

RATE_DELAY_MIN = 1.5
RATE_DELAY_MAX = 3.0
RETRY_429_WAIT = 35


def _log_api(endpoint: str, params: dict, status: int, response: dict = None, error: str = None):
    try:
        from steam_bot import database as db
        db.add_api_log(endpoint, params, status, response, error)
    except Exception:
        pass


async def _steam_get(session: aiohttp.ClientSession, url: str, params: dict,
                     endpoint_label: str, retries: int = 3) -> tuple:
    """
    Безопасный GET-запрос к Steam с:
    - Семафором (1 одновременный запрос) + задержкой ВНУТРИ него
    - Случайным джиттером между запросами (1.5–3 сек)
    - Повтором при 429 с ожиданием ~35–50 сек
    Возвращает (status_code, data_or_None)
    """
    for attempt in range(retries):
        async with _steam_sem:
            result_status = 0
            result_data = None
            do_retry = False
            retry_wait = 0
            try:
                async with session.get(url, params=params, headers=_STEAM_HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    result_status = resp.status
                    if resp.status == 200:
                        try:
                            result_data = await resp.json(content_type=None)
                        except Exception:
                            result_data = None
                    elif resp.status == 429:
                        _log_api(endpoint_label, params, 429, None,
                                 f"Rate limit (attempt {attempt+1}/{retries})")
                        if attempt < retries - 1:
                            do_retry = True
                            retry_wait = RETRY_429_WAIT + random.uniform(5, 15)
                    else:
                        pass
            except asyncio.TimeoutError:
                _log_api(endpoint_label, params, 0, None, f"Timeout (attempt {attempt+1})")
                if attempt < retries - 1:
                    do_retry = True
                    retry_wait = 3
            except Exception as e:
                _log_api(endpoint_label, params, 0, None, str(e))
                return 0, None

            if not do_retry:
                await asyncio.sleep(random.uniform(RATE_DELAY_MIN, RATE_DELAY_MAX))
                return result_status, result_data

            await asyncio.sleep(retry_wait)

    return 0, None


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
    async with aiohttp.ClientSession() as session:
        status, data = await _steam_get(session, STEAM_PRICE_API, params, "priceoverview")

    if status == 200 and data:
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
            _log_api("priceoverview", params, status, data)
            return result
        else:
            _log_api("priceoverview", params, status, data, "success=false")
            return {"success": False, "error": "Steam API вернул success=false"}
    elif status == 429:
        return {"success": False, "error": "Rate limit 429 — исчерпаны все попытки"}
    else:
        _log_api("priceoverview", params, status, None, f"HTTP {status}")
        return {"success": False, "error": f"HTTP {status}"}


async def get_price_history(market_hash_name: str, app_id: int = 730, currency: int = 1) -> dict:
    """Получение истории цен предмета (требует авторизации Steam, без cookies возвращает 400)."""
    params = {
        "appid": app_id,
        "market_hash_name": market_hash_name,
        "currency": currency,
        "country": "US",
    }
    async with aiohttp.ClientSession() as session:
        status, data = await _steam_get(session, STEAM_PRICE_HISTORY_API, params, "pricehistory")

    if status == 200 and data:
        _log_api("pricehistory", params, status, {"prices_count": len(data.get("prices", []))})
        if data.get("success") and data.get("prices"):
            return {"success": True, "prices": data["prices"]}
        return {"success": False, "error": "Нет данных истории"}
    _log_api("pricehistory", params, status, None, f"HTTP {status}")
    return {"success": False, "error": f"HTTP {status} (требует авторизации Steam)"}


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


async def _fetch_search_page(session, app_id: int, query: str, start: int, page_size: int = 50) -> tuple:
    """Запрос одной страницы Steam Market Search через _steam_get (с rate-limit защитой)."""
    params = {
        "appid": app_id,
        "query": query,
        "start": start,
        "count": page_size,
        "search_descriptions": 0,
        "sort_column": "popular",
        "sort_dir": "desc",
        "norender": 1,
    }
    label = f"scanner/search"
    status, data = await _steam_get(session, STEAM_SEARCH_API, params, label)
    if status == 200 and data:
        _log_api(label, {"query": query, "appid": app_id, "start": start},
                 status, {"total": data.get("total_count", 0),
                          "results": len(data.get("results", []))})
        return data.get("results", []), data.get("total_count", 0)
    return [], 0


async def scan_market(query: str, app_id: int = 730, currency: int = 5,
                      min_price_usd: float = 1.0, threshold_pct: float = 17.0,
                      max_results: int = 30) -> list:
    """
    Сканирует рынок Steam с пагинацией.
    
    Логика:
    - sell_price в поиске Steam = центы USD (всегда)
    - Медианная цена (median_price) из priceoverview = средняя рыночная за последние дни
    - Скидка = (median - lowest) / median — это разница между текущей ценой и средним уровнем
    - Если скидка >= threshold_pct, предмет подходит для слежки
    
    НЕ использует pricehistory (требует auth cookies, всегда возвращает 400).
    Возвращает ВСЕ найденные предметы отсортированные по скидке.
    """
    PAGE_SIZE = 50
    MAX_PAGES = 3
    min_price_cents = int(min_price_usd * 100)

    raw_candidates = []
    consecutive_429 = 0
    async with aiohttp.ClientSession() as session:
        for page in range(MAX_PAGES):
            start = page * PAGE_SIZE
            results, total = await _fetch_search_page(session, app_id, query, start, PAGE_SIZE)
            if not results:
                consecutive_429 += 1
                if consecutive_429 >= 2:
                    break
                continue
            consecutive_429 = 0
            for r in results:
                sell_price = r.get("sell_price", 0)
                if sell_price < min_price_cents:
                    continue
                hash_name = r.get("hash_name", r.get("name", ""))
                asset_desc = r.get("asset_description", {})
                icon_url = ""
                if asset_desc.get("icon_url"):
                    icon_url = f"https://community.akamai.steamstatic.com/economy/image/{asset_desc['icon_url']}/128x128"
                raw_candidates.append({
                    "name": r.get("name", ""),
                    "hash_name": hash_name,
                    "app_id": app_id,
                    "sell_listings": r.get("sell_listings", 0),
                    "sell_price_usd": sell_price / 100.0,
                    "icon_url": icon_url,
                    "steam_url": f"https://steamcommunity.com/market/listings/{app_id}/{hash_name.replace(' ', '%20')}",
                })

            if len(raw_candidates) >= max_results * 2 or start + PAGE_SIZE >= total:
                break

    seen = set()
    unique_candidates = []
    for item in raw_candidates:
        if item["hash_name"] not in seen:
            seen.add(item["hash_name"])
            unique_candidates.append(item)

    unique_candidates = unique_candidates[:max_results * 2]

    results = []
    fail_count = 0
    MAX_CONSECUTIVE_FAILS = 5
    for item in unique_candidates:
        price_data = await get_item_price(item["hash_name"], app_id, currency)

        if not price_data.get("success"):
            fail_count += 1
            if fail_count >= MAX_CONSECUTIVE_FAILS:
                break
            continue
        fail_count = 0

        lowest = price_data["lowest_price"]
        median = price_data["median_price"]

        if lowest <= 0 or median <= 0:
            continue

        volume_str = str(price_data.get("volume", "0")).replace(",", "").replace(" ", "")
        try:
            volume = int(volume_str)
        except Exception:
            volume = 0

        discount = ((median - lowest) / median) * 100
        profit_info = calculate_profit(lowest, median)

        results.append({
            "name": item["name"],
            "hash_name": item["hash_name"],
            "app_id": app_id,
            "icon_url": item["icon_url"],
            "steam_url": item["steam_url"],
            "sell_listings": item["sell_listings"],
            "sell_price_usd": round(item["sell_price_usd"], 2),
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
        })

        if len(results) >= max_results:
            break

    results.sort(key=lambda x: (-x["discount_pct"], -x["volume"]))
    return results
