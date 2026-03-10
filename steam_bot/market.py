import aiohttp
import asyncio
import time
import random
import re
import json
from datetime import datetime, timedelta
from urllib.parse import quote
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


_history_cache = {}
HISTORY_CACHE_TTL = 600


async def get_price_history_from_page(session: aiohttp.ClientSession, app_id: int,
                                       hash_name: str) -> list:
    cache_key = f"{app_id}:{hash_name}"
    now = time.time()
    if cache_key in _history_cache:
        cached_at, cached_data = _history_cache[cache_key]
        if now - cached_at < HISTORY_CACHE_TTL:
            return cached_data

    url = f"https://steamcommunity.com/market/listings/{app_id}/{quote(hash_name, safe='')}"
    try:
        async with _steam_sem:
            async with session.get(url, headers={
                "User-Agent": _STEAM_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
            }, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    m = re.search(r'var line1\s*=\s*(\[.+?\]);', html, re.DOTALL)
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            _history_cache[cache_key] = (now, data)
                            _log_api("listing_page/history", {"app_id": app_id, "hash_name": hash_name},
                                     200, {"entries": len(data)})
                            return data
                        except json.JSONDecodeError:
                            pass
                    _log_api("listing_page/history", {"app_id": app_id, "hash_name": hash_name},
                             200, None, "var line1 not found in HTML")
                elif resp.status == 429:
                    _log_api("listing_page/history", {"app_id": app_id, "hash_name": hash_name},
                             429, None, "Rate limited")
                else:
                    _log_api("listing_page/history", {"app_id": app_id, "hash_name": hash_name},
                             resp.status, None, f"HTTP {resp.status}")
            await asyncio.sleep(random.uniform(RATE_DELAY_MIN, RATE_DELAY_MAX))
    except Exception as e:
        _log_api("listing_page/history", {"app_id": app_id, "hash_name": hash_name},
                 0, None, str(e))
    return []


def analyze_price_history(prices: list, median_price: float, threshold_pct: float = 17.0,
                           days: int = 14) -> dict:
    if not prices:
        return {"has_history": False}

    cutoff = datetime.utcnow() - timedelta(days=days)

    recent_prices = []
    for entry in prices:
        try:
            date_str = entry[0]
            price = float(entry[1])
            count_str = entry[2] if len(entry) > 2 else "1"
            count = int(str(count_str).replace(",", ""))
            dt = datetime.strptime(date_str[:11].strip(), "%b %d %Y")
            if dt >= cutoff:
                recent_prices.append({"price": price, "count": count, "date": dt})
        except Exception:
            continue

    if not recent_prices:
        return {"has_history": True, "total_sales": 0, "discount_sales": 0,
                "had_recent_discounts": False, "period_days": days}

    weighted_pairs = [(s["price"], s["count"]) for s in recent_prices]
    weighted_pairs.sort(key=lambda x: x[0])
    total_volume = sum(c for _, c in weighted_pairs)

    cumulative = 0
    history_median = weighted_pairs[0][0]
    mid = total_volume / 2
    for price, count in weighted_pairs:
        cumulative += count
        if cumulative >= mid:
            history_median = price
            break

    if history_median <= 0:
        return {"has_history": True, "total_sales": total_volume, "discount_sales": 0,
                "had_recent_discounts": False, "period_days": days}

    discount_threshold = history_median * (1 - threshold_pct / 100)

    discounted_sales = []
    min_price_seen = float('inf')
    max_discount_seen = 0

    for s in recent_prices:
        if s["price"] <= discount_threshold:
            disc_pct = ((history_median - s["price"]) / history_median) * 100
            discounted_sales.append({"price": s["price"], "count": s["count"],
                                     "date": s["date"], "discount_pct": disc_pct})
            if s["price"] < min_price_seen:
                min_price_seen = s["price"]
            if disc_pct > max_discount_seen:
                max_discount_seen = disc_pct

    discount_volume = sum(s["count"] for s in discounted_sales)

    last_discount_date = None
    if discounted_sales:
        discounted_sales.sort(key=lambda x: x["date"], reverse=True)
        last_discount_date = discounted_sales[0]["date"].strftime("%d.%m")

    return {
        "has_history": True,
        "period_days": days,
        "total_sales": total_volume,
        "discount_sales": discount_volume,
        "discount_entries": len(discounted_sales),
        "had_recent_discounts": len(discounted_sales) > 0,
        "history_median": round(history_median, 2),
        "min_price_seen": round(min_price_seen, 2) if min_price_seen != float('inf') else 0,
        "max_discount_pct": round(max_discount_seen, 1),
        "last_discount_date": last_discount_date,
        "discount_frequency_pct": round(discount_volume / total_volume * 100, 1) if total_volume > 0 else 0,
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
    session = aiohttp.ClientSession()
    try:
        for page in range(MAX_PAGES):
            start = page * PAGE_SIZE
            search_results, total = await _fetch_search_page(session, app_id, query, start, PAGE_SIZE)
            if not search_results:
                consecutive_429 += 1
                if consecutive_429 >= 2:
                    break
                continue
            consecutive_429 = 0
            for r in search_results:
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
        history_fail_count = 0
        MAX_CONSECUTIVE_FAILS = 5
        MAX_HISTORY_FAILS = 3
        fetch_history = True

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

            history_info = {"has_history": False}
            if fetch_history:
                history_data = await get_price_history_from_page(session, app_id, item["hash_name"])
                if history_data:
                    history_info = analyze_price_history(history_data, median, threshold_pct, days=14)
                    history_fail_count = 0
                else:
                    history_fail_count += 1
                    if history_fail_count >= MAX_HISTORY_FAILS:
                        fetch_history = False

            is_currently_profitable = profit_info["is_profitable"] and discount >= threshold_pct
            had_recent_discounts = history_info.get("had_recent_discounts", False)
            worth_tracking = is_currently_profitable or had_recent_discounts

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
                "is_profitable": is_currently_profitable,
                "history": history_info,
                "had_recent_discounts": had_recent_discounts,
                "worth_tracking": worth_tracking,
            })

            if len(results) >= max_results:
                break

        def sort_key(x):
            if x["is_profitable"]:
                return (0, -x["discount_pct"], -x["volume"])
            elif x["had_recent_discounts"]:
                return (1, -x["history"].get("max_discount_pct", 0), -x["volume"])
            else:
                return (2, -x["discount_pct"], -x["volume"])

        results.sort(key=sort_key)
        return results
    finally:
        await session.close()
