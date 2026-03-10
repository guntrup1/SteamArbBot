import aiohttp
import asyncio
import time
import random
import re
import json
import math
from datetime import datetime, timedelta
from urllib.parse import quote
from steam_bot.config import (
    STEAM_PRICE_API, STEAM_SEARCH_API, STEAM_COMMISSION,
    STEAM_ORDERS_HISTOGRAM_API, MIN_WEEKLY_SALES
)

_price_cache = {}
CACHE_TTL = 300

_history_cache = {}
HISTORY_CACHE_TTL = 600

_orders_cache = {}
ORDERS_CACHE_TTL = 300

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


async def get_item_price(market_hash_name: str, app_id: int = 440, currency: int = 5) -> dict:
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
            return {"success": False, "error": "Steam API success=false"}
    elif status == 429:
        return {"success": False, "error": "Rate limit 429"}
    else:
        _log_api("priceoverview", params, status, None, f"HTTP {status}")
        return {"success": False, "error": f"HTTP {status}"}


async def get_listing_page_data(session: aiohttp.ClientSession, app_id: int,
                                 hash_name: str) -> dict:
    cache_key = f"page:{app_id}:{hash_name}"
    now = time.time()
    if cache_key in _history_cache:
        cached_at, cached_data = _history_cache[cache_key]
        if now - cached_at < HISTORY_CACHE_TTL:
            return cached_data

    url = f"https://steamcommunity.com/market/listings/{app_id}/{quote(hash_name, safe='')}"
    result = {"history": [], "item_nameid": None}
    try:
        async with _steam_sem:
            async with session.get(url, headers={
                "User-Agent": _STEAM_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
            }, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    m_hist = re.search(r'var line1\s*=\s*(\[.+?\]);', html, re.DOTALL)
                    if m_hist:
                        try:
                            result["history"] = json.loads(m_hist.group(1))
                        except json.JSONDecodeError:
                            pass
                    m_id = re.search(r'Market_LoadOrderSpread\(\s*(\d+)', html)
                    if m_id:
                        result["item_nameid"] = m_id.group(1)
                    _log_api("listing_page", {"app_id": app_id, "hash_name": hash_name},
                             200, {"history_entries": len(result["history"]),
                                   "nameid": result["item_nameid"]})
                else:
                    _log_api("listing_page", {"app_id": app_id, "hash_name": hash_name},
                             resp.status, None, f"HTTP {resp.status}")
            await asyncio.sleep(random.uniform(RATE_DELAY_MIN, RATE_DELAY_MAX))
    except Exception as e:
        _log_api("listing_page", {"app_id": app_id, "hash_name": hash_name},
                 0, None, str(e))

    if result["history"] or result["item_nameid"]:
        _history_cache[cache_key] = (now, result)
    return result


async def get_buy_orders(session: aiohttp.ClientSession, item_nameid: str,
                          currency: int = 1) -> dict:
    cache_key = f"orders:{item_nameid}:{currency}"
    now = time.time()
    if cache_key in _orders_cache:
        cached_at, cached_data = _orders_cache[cache_key]
        if now - cached_at < ORDERS_CACHE_TTL:
            return cached_data

    params = {
        "country": "US",
        "language": "english",
        "currency": currency,
        "item_nameid": item_nameid,
    }
    try:
        status, data = await _steam_get(session, STEAM_ORDERS_HISTOGRAM_API, params, "orders_histogram")
        if status == 200 and data and data.get("success") == 1:
            highest_buy = int(data.get("highest_buy_order", 0))
            lowest_sell = int(data.get("lowest_sell_order", 0))
            buy_graph = data.get("buy_order_graph", [])
            sell_graph = data.get("sell_order_graph", [])
            result = {
                "success": True,
                "highest_buy_order": highest_buy / 100.0,
                "lowest_sell_order": lowest_sell / 100.0,
                "buy_order_count": buy_graph[0][1] if buy_graph else 0,
                "sell_order_count": sell_graph[-1][1] if sell_graph else 0,
                "buy_graph": buy_graph[:10],
                "sell_graph": sell_graph[:10],
                "spread_pct": round(((lowest_sell - highest_buy) / highest_buy * 100), 1) if highest_buy > 0 else 0,
            }
            _orders_cache[cache_key] = (now, result)
            _log_api("orders_histogram", {"nameid": item_nameid}, status,
                     {"highest_buy": result["highest_buy_order"],
                      "lowest_sell": result["lowest_sell_order"],
                      "spread": result["spread_pct"]})
            return result
        _log_api("orders_histogram", {"nameid": item_nameid}, status, None,
                 f"success={data.get('success') if data else 'null'}")
    except Exception as e:
        _log_api("orders_histogram", {"nameid": item_nameid}, 0, None, str(e))

    return {"success": False}


def analyze_price_history(prices: list, threshold_pct: float = 17.0,
                           days: int = 7) -> dict:
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
        return {"has_history": True, "total_sales": 0, "weekly_sales": 0,
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
        return {"has_history": True, "total_sales": total_volume, "weekly_sales": total_volume,
                "had_recent_discounts": False, "period_days": days}

    all_sale_prices = [s["price"] for s in recent_prices for _ in range(min(s["count"], 100))]
    min_price = min(p for p, _ in weighted_pairs)
    max_price = max(p for p, _ in weighted_pairs)

    return {
        "has_history": True,
        "period_days": days,
        "total_sales": total_volume,
        "weekly_sales": total_volume,
        "history_median": round(history_median, 2),
        "min_price": round(min_price, 2),
        "max_price": round(max_price, 2),
        "price_range_pct": round((max_price - min_price) / history_median * 100, 1) if history_median > 0 else 0,
        "all_prices": weighted_pairs,
    }


def check_history_has_sales_at_levels(prices: list, buy_level: float, sell_level: float,
                                       tolerance_pct: float = 10.0, days: int = 7) -> dict:
    if not prices:
        return {"has_buy_level_sales": False, "has_sell_level_sales": False}

    cutoff = datetime.utcnow() - timedelta(days=days)
    buy_tol = buy_level * tolerance_pct / 100
    sell_tol = sell_level * tolerance_pct / 100

    buy_level_sales = 0
    sell_level_sales = 0
    total_sales = 0

    for entry in prices:
        try:
            date_str = entry[0]
            price = float(entry[1])
            count_str = entry[2] if len(entry) > 2 else "1"
            count = int(str(count_str).replace(",", ""))
            dt = datetime.strptime(date_str[:11].strip(), "%b %d %Y")
            if dt >= cutoff:
                total_sales += count
                if abs(price - buy_level) <= buy_tol:
                    buy_level_sales += count
                if abs(price - sell_level) <= sell_tol:
                    sell_level_sales += count
        except Exception:
            continue

    return {
        "has_buy_level_sales": buy_level_sales > 0,
        "has_sell_level_sales": sell_level_sales > 0,
        "buy_level_sales": buy_level_sales,
        "sell_level_sales": sell_level_sales,
        "total_sales": total_sales,
    }


def detect_anomalies(prices: list, days: int = 14) -> dict:
    if not prices:
        return {"is_manipulated": False, "anomaly_score": 0}

    cutoff = datetime.utcnow() - timedelta(days=days)

    daily_volumes = {}
    daily_prices = {}
    all_prices_weighted = []

    for entry in prices:
        try:
            date_str = entry[0]
            price = float(entry[1])
            count_str = entry[2] if len(entry) > 2 else "1"
            count = int(str(count_str).replace(",", ""))
            dt = datetime.strptime(date_str[:11].strip(), "%b %d %Y")
            if dt >= cutoff:
                day_key = dt.strftime("%Y-%m-%d")
                daily_volumes[day_key] = daily_volumes.get(day_key, 0) + count
                if day_key not in daily_prices:
                    daily_prices[day_key] = []
                daily_prices[day_key].append(price)
                all_prices_weighted.append((price, count))
        except Exception:
            continue

    if not all_prices_weighted or len(daily_volumes) < 3:
        return {"is_manipulated": False, "anomaly_score": 0, "reason": "Недостаточно данных"}

    all_p = [p for p, _ in all_prices_weighted]
    total_count = sum(c for _, c in all_prices_weighted)
    mean_price = sum(p * c for p, c in all_prices_weighted) / total_count if total_count > 0 else 0
    variance = sum(c * (p - mean_price) ** 2 for p, c in all_prices_weighted) / total_count if total_count > 0 else 0
    std_dev = math.sqrt(variance) if variance > 0 else 0

    anomaly_score = 0
    reasons = []

    if std_dev > 0 and mean_price > 0:
        cv = std_dev / mean_price
        if cv > 0.5:
            anomaly_score += 40
            reasons.append(f"Высокая волатильность (CV={cv:.2f})")
        elif cv > 0.3:
            anomaly_score += 20
            reasons.append(f"Повышенная волатильность (CV={cv:.2f})")

    volumes = list(daily_volumes.values())
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    if avg_vol > 0:
        max_vol = max(volumes)
        if max_vol > avg_vol * 5:
            anomaly_score += 30
            reasons.append(f"Резкий скачок объёма ({max_vol} vs avg {avg_vol:.0f})")
        elif max_vol > avg_vol * 3:
            anomaly_score += 15
            reasons.append(f"Скачок объёма ({max_vol} vs avg {avg_vol:.0f})")

    if std_dev > 0:
        extreme_sales = 0
        for p, c in all_prices_weighted:
            if abs(p - mean_price) > 3 * std_dev:
                extreme_sales += c
        extreme_ratio = extreme_sales / total_count if total_count > 0 else 0
        if extreme_ratio > 0.05:
            anomaly_score += 30
            reasons.append(f"Много аномальных продаж ({extreme_ratio:.1%})")
        elif extreme_ratio > 0.02:
            anomaly_score += 15
            reasons.append(f"Есть аномальные продажи ({extreme_ratio:.1%})")

    return {
        "is_manipulated": anomaly_score >= 50,
        "anomaly_score": min(anomaly_score, 100),
        "reasons": reasons,
        "mean_price": round(mean_price, 2),
        "std_dev": round(std_dev, 4),
        "cv": round(std_dev / mean_price, 3) if mean_price > 0 else 0,
        "days_analyzed": len(daily_volumes),
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


async def search_item(query: str, app_id: int = 440) -> list:
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(STEAM_SEARCH_API, params=params, headers=_STEAM_HEADERS,
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


async def scan_market(query: str, app_id: int = 440, currency: int = 1,
                      min_price_usd: float = 0.20, threshold_pct: float = 17.0,
                      max_results: int = 30, min_weekly_sales: int = 600) -> list:
    """
    Сканер рынка TF2/Dota 2 с ордерами и историей.

    Логика:
    1. Поиск предметов, фильтрация по мин. цене
    2. Получение истории цен + item_nameid со страницы листинга
    3. Проверка ликвидности (600+ продаж/неделю)
    4. Получение ордеров на покупку
    5. Проверка: рыночная цена >= buy_order * 1.17 (спред 17%+)
    6. Проверка истории: были продажи и по цене ордера, и по рыночной
    7. Детекция аномалий/манипуляций
    8. Результат: предметы подходящие для ордеров
    """
    PAGE_SIZE = 50
    MAX_PAGES = 5
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
                    "steam_url": f"https://steamcommunity.com/market/listings/{app_id}/{quote(hash_name, safe='')}",
                })

            if len(raw_candidates) >= max_results * 3 or start + PAGE_SIZE >= total:
                break

        seen = set()
        unique_candidates = []
        for item in raw_candidates:
            if item["hash_name"] not in seen:
                seen.add(item["hash_name"])
                unique_candidates.append(item)

        unique_candidates = unique_candidates[:max_results * 3]

        results = []
        fail_count = 0
        MAX_CONSECUTIVE_FAILS = 5

        for item in unique_candidates:
            if len(results) >= max_results:
                break

            page_data = await get_listing_page_data(session, app_id, item["hash_name"])
            history = page_data.get("history", [])
            item_nameid = page_data.get("item_nameid")

            if not history:
                fail_count += 1
                if fail_count >= MAX_CONSECUTIVE_FAILS:
                    break
                continue
            fail_count = 0

            hist_info = analyze_price_history(history, threshold_pct, days=7)
            weekly_sales = hist_info.get("weekly_sales", 0)

            is_liquid = weekly_sales >= min_weekly_sales

            orders_info = {"success": False}
            if item_nameid:
                orders_info = await get_buy_orders(session, item_nameid, currency=1)

            highest_buy = orders_info.get("highest_buy_order", 0) if orders_info.get("success") else 0
            lowest_sell = orders_info.get("lowest_sell_order", 0) if orders_info.get("success") else 0
            spread_pct = orders_info.get("spread_pct", 0) if orders_info.get("success") else 0

            has_good_spread = spread_pct >= threshold_pct if highest_buy > 0 else False

            level_check = {"has_buy_level_sales": False, "has_sell_level_sales": False}
            if highest_buy > 0 and lowest_sell > 0 and history:
                level_check = check_history_has_sales_at_levels(
                    history, highest_buy, lowest_sell, tolerance_pct=15.0, days=7
                )

            both_levels_traded = (level_check["has_buy_level_sales"] and
                                  level_check["has_sell_level_sales"])

            anomaly = detect_anomalies(history, days=14)
            is_manipulated = anomaly.get("is_manipulated", False)

            profit_if_buy_at_order = calculate_profit(highest_buy, lowest_sell) if highest_buy > 0 and lowest_sell > 0 else {"net_profit_percent": 0, "profit": 0, "is_profitable": False}

            is_ideal = (is_liquid and has_good_spread and both_levels_traded
                        and not is_manipulated and profit_if_buy_at_order["is_profitable"])

            results.append({
                "name": item["name"],
                "hash_name": item["hash_name"],
                "app_id": app_id,
                "icon_url": item["icon_url"],
                "steam_url": item["steam_url"],
                "sell_listings": item["sell_listings"],
                "sell_price_usd": round(item["sell_price_usd"], 2),
                "highest_buy_order": highest_buy,
                "lowest_sell_order": lowest_sell,
                "spread_pct": spread_pct,
                "weekly_sales": weekly_sales,
                "is_liquid": is_liquid,
                "has_good_spread": has_good_spread,
                "both_levels_traded": both_levels_traded,
                "buy_level_sales": level_check.get("buy_level_sales", 0),
                "sell_level_sales": level_check.get("sell_level_sales", 0),
                "is_manipulated": is_manipulated,
                "anomaly_score": anomaly.get("anomaly_score", 0),
                "anomaly_reasons": anomaly.get("reasons", []),
                "profit_if_ordered": profit_if_buy_at_order.get("profit", 0),
                "profit_pct_if_ordered": profit_if_buy_at_order.get("net_profit_percent", 0),
                "is_ideal": is_ideal,
                "history_info": {
                    "median": hist_info.get("history_median", 0),
                    "min": hist_info.get("min_price", 0),
                    "max": hist_info.get("max_price", 0),
                    "range_pct": hist_info.get("price_range_pct", 0),
                },
                "orders_info": {
                    "buy_count": orders_info.get("buy_order_count", 0),
                    "sell_count": orders_info.get("sell_order_count", 0),
                },
            })

        def sort_key(x):
            if x["is_ideal"]:
                return (0, -x["spread_pct"], -x["weekly_sales"])
            elif x["is_liquid"] and x["has_good_spread"] and not x["is_manipulated"]:
                return (1, -x["spread_pct"], -x["weekly_sales"])
            elif x["is_liquid"]:
                return (2, -x["weekly_sales"])
            else:
                return (3, -x["weekly_sales"])

        results.sort(key=sort_key)
        return results
    finally:
        await session.close()
