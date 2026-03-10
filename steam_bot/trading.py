import asyncio
import aiohttp
import json
from datetime import datetime
from steam_bot import database as db
from steam_bot import market
from steam_bot import telegram_bot as tg
from steam_bot.config import STEAM_COMMISSION, get_currency_symbol

_bot_running = False
_bot_task = None
_ws_clients = set()
_buys_this_hour = []

def register_ws_client(ws):
    _ws_clients.add(ws)

def unregister_ws_client(ws):
    _ws_clients.discard(ws)

async def broadcast_log(log_entry: dict):
    """Отправка лога всем подключённым WebSocket клиентам"""
    if not _ws_clients:
        return
    dead = set()
    msg = json.dumps({"type": "log", "data": log_entry})
    for ws in list(_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)

async def broadcast_status(status: dict):
    if not _ws_clients:
        return
    dead = set()
    msg = json.dumps({"type": "status", "data": status})
    for ws in list(_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)

async def log(message: str, level: str = "info", item_name: str = None,
              mode: str = "TEST", stage: str = None):
    """Логирование в БД и броадкаст по WebSocket"""
    db.add_log(message, level, item_name, mode, stage)
    now = datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": now,
        "level": level,
        "message": message,
        "item_name": item_name,
        "mode": mode,
        "stage": stage,
        "created_at": datetime.now().isoformat(),
    }
    await broadcast_log(entry)

def is_running() -> bool:
    return _bot_running

def get_current_mode() -> str:
    test_mode = db.get_setting("test_mode", "1")
    return "TEST" if test_mode == "1" else "LIVE"

async def get_balance() -> float:
    """Получение баланса в зависимости от режима"""
    mode = get_current_mode()
    if mode == "TEST":
        return float(db.get_setting("current_virtual_balance", "1000"))
    else:
        return await get_real_steam_balance()

async def get_real_steam_balance() -> float:
    """Получение реального баланса Steam через веб-запрос"""
    api_key = db.get_setting("steam_api_key", "")
    steam_login = db.get_setting("steam_login", "")
    if not api_key or not steam_login:
        return 0.0
    try:
        url = "https://store.steampowered.com/api/appdetails"
        return 0.0
    except Exception:
        return 0.0

async def deduct_balance(amount: float):
    """Вычитание из баланса (тестовый или реальный)"""
    mode = get_current_mode()
    curr_sym = get_currency_symbol(db.get_setting("steam_currency", "5"))
    if mode == "TEST":
        current = float(db.get_setting("current_virtual_balance", "1000"))
        new_balance = max(0, current - amount)
        db.set_setting("current_virtual_balance", str(round(new_balance, 2)))
        tg_msg = tg.format_balance_change(current, new_balance, mode, curr_sym)
        await send_tg(tg_msg)
        return new_balance
    return await get_real_steam_balance()

async def add_balance(amount: float):
    """Добавление к балансу (только тестовый режим)"""
    mode = get_current_mode()
    curr_sym = get_currency_symbol(db.get_setting("steam_currency", "5"))
    if mode == "TEST":
        current = float(db.get_setting("current_virtual_balance", "1000"))
        new_balance = current + amount
        db.set_setting("current_virtual_balance", str(round(new_balance, 2)))
        tg_msg = tg.format_balance_change(current, new_balance, mode, curr_sym)
        await send_tg(tg_msg)
        return new_balance
    return await get_real_steam_balance()

def check_hourly_limit() -> bool:
    """Проверка лимита покупок в час"""
    max_buys = int(db.get_setting("max_buys_per_hour", "10"))
    now = datetime.now()
    global _buys_this_hour
    _buys_this_hour = [t for t in _buys_this_hour
                       if (now - t).total_seconds() < 3600]
    return len(_buys_this_hour) < max_buys

async def send_tg(message: str):
    """Отправка сообщения в Telegram"""
    token = db.get_setting("telegram_bot_token", "")
    chat_id = db.get_setting("telegram_chat_id", "")
    if token and chat_id:
        ok, _ = await tg.send_telegram_message(token, chat_id, message)

async def process_item(item: dict, mode: str):
    """Обработка одного предмета: проверка цены и принятие решения о покупке"""
    item_name = item["name"]
    hash_name = item["market_hash_name"]
    app_id = item.get("app_id", 440)
    steam_url = item.get("steam_url", "")
    currency_setting = db.get_setting("steam_currency", "5")
    currency = int(currency_setting)
    curr_sym = get_currency_symbol(currency_setting)
    threshold = float(db.get_setting("buy_threshold", "17"))

    await log(f"🔍 Проверка цены: {item_name}", "info", item_name, mode, "check_price")

    price_data = await market.get_item_price(hash_name, app_id, currency)

    if not price_data.get("success"):
        err = price_data.get("error", "Неизвестная ошибка")
        await log(f"❌ Ошибка получения цены {item_name}: {err}", "error", item_name, mode, "price_error")
        return

    lowest = price_data["lowest_price"]
    median = price_data["median_price"]
    lowest_raw = price_data["lowest_price_raw"]
    median_raw = price_data["median_price_raw"]

    await log(f"📊 {item_name} | Мин. цена: {lowest_raw} | Средняя: {median_raw}", "info", item_name, mode, "price_info")

    if lowest <= 0 or median <= 0:
        await log(f"⚠️ {item_name}: цены недоступны", "warning", item_name, mode, "price_unavailable")
        return

    buy_decision, discount, reason = market.should_buy(lowest, median, threshold)

    profit_info = market.calculate_profit(lowest, median)
    await log(
        f"💹 {item_name} | Скидка: {discount:.1f}% | Чистая прибыль: {profit_info['net_profit_percent']:.1f}% | Порог: {threshold}%",
        "info", item_name, mode, "profit_calc"
    )

    if not buy_decision:
        await log(f"⏭️ {item_name}: {reason}", "info", item_name, mode, "skip")
        return

    if not check_hourly_limit():
        max_h = db.get_setting("max_buys_per_hour", "10")
        await log(f"⏰ {item_name}: достигнут лимит покупок ({max_h}/час)", "warning", item_name, mode, "limit_reached")
        return

    balance = await get_balance()
    await log(f"💰 Баланс: {balance:.2f}{curr_sym} | Нужно: {lowest:.2f}{curr_sym}", "info", item_name, mode, "balance_check")

    if balance < lowest:
        msg = f"❌ {item_name}: недостаточно средств (баланс: {balance:.2f}{curr_sym}, нужно: {lowest:.2f}{curr_sym})"
        await log(msg, "error", item_name, mode, "insufficient_funds")
        tg_msg = tg.format_error(f"Недостаточно средств для покупки {item_name}\nБаланс: {balance:.2f}{curr_sym}, нужно: {lowest:.2f}{curr_sym}", item_name, mode)
        await send_tg(tg_msg)
        return

    await log(f"✅ {item_name}: УСЛОВИЕ ВЫПОЛНЕНО — {reason}", "success", item_name, mode, "buy_decision")
    await log(f"🛒 {item_name}: начинаем {'симуляцию ' if mode == 'TEST' else ''}покупки за {lowest_raw}", "trade", item_name, mode, "buying")

    sell_strategy = db.get_setting("sell_strategy", "market")
    sell_discount = float(db.get_setting("sell_discount", "1"))

    if sell_strategy == "market_minus":
        sell_price = median * (1 - sell_discount / 100)
    else:
        sell_price = median

    sell_net = sell_price * (1 - STEAM_COMMISSION)
    actual_profit = sell_net - lowest

    if mode == "TEST":
        await asyncio.sleep(0.5)
        new_balance = await deduct_balance(lowest)
        await log(f"✅ [ТЕСТ] Покупка {item_name} симулирована за {lowest_raw}", "success", item_name, mode, "buy_success")
        await log(f"💰 [ТЕСТ] Новый виртуальный баланс: {new_balance:.2f}{curr_sym}", "info", item_name, mode, "balance_update")

        db.add_trade(
            item_name=item_name, market_hash_name=hash_name,
            trade_type="buy", buy_price=lowest, market_price=median,
            profit=None, profit_after_fee=None, status="completed", test_mode=True
        )
        _buys_this_hour.append(datetime.now())

        tg_msg = tg.format_purchase(item_name, lowest, median, actual_profit, new_balance, mode, steam_url, curr_sym)
        await send_tg(tg_msg)

        await asyncio.sleep(1)
        await log(f"📤 [ТЕСТ] Выставляем {item_name} на продажу за {sell_price:.2f}{curr_sym}", "info", item_name, mode, "listing")
        await asyncio.sleep(0.5)

        db.add_trade(
            item_name=item_name, market_hash_name=hash_name,
            trade_type="sell", buy_price=lowest, sell_price=sell_price,
            market_price=median, profit=actual_profit, profit_after_fee=actual_profit,
            status="completed", test_mode=True
        )

        final_balance = await add_balance(sell_net)
        await log(f"✅ [ТЕСТ] {item_name} выставлен на продажу за {sell_price:.2f}{curr_sym}. Прибыль: {actual_profit:.2f}{curr_sym}", "success", item_name, mode, "listed")
        await log(f"💰 [ТЕСТ] Итоговый виртуальный баланс: {final_balance:.2f}{curr_sym}", "info", item_name, mode, "balance_update")

        tg_sell = tg.format_sale(item_name, sell_price, lowest, actual_profit, final_balance, mode, curr_sym)
        await send_tg(tg_sell)

    else:
        await log(f"🔴 [LIVE] Выполняем РЕАЛЬНУЮ покупку {item_name} за {lowest_raw}...", "trade", item_name, mode, "real_buy")
        success, error_msg = await execute_real_buy(item, lowest, median)

        if success:
            new_balance = await get_real_steam_balance()
            await log(f"✅ [LIVE] Покупка {item_name} ВЫПОЛНЕНА за {lowest_raw}", "success", item_name, mode, "buy_success")
            await log(f"💰 [LIVE] Реальный баланс: {new_balance:.2f}{curr_sym}", "info", item_name, mode, "balance_update")

            db.add_trade(
                item_name=item_name, market_hash_name=hash_name,
                trade_type="buy", buy_price=lowest, market_price=median,
                status="completed", test_mode=False
            )
            _buys_this_hour.append(datetime.now())

            tg_msg = tg.format_purchase(item_name, lowest, median, actual_profit, new_balance, mode, steam_url, curr_sym)
            await send_tg(tg_msg)

            await asyncio.sleep(2)
            await log(f"📤 [LIVE] Выставляем {item_name} на продажу за {sell_price:.2f}{curr_sym}...", "info", item_name, mode, "listing")
            sell_ok, sell_err = await execute_real_sell(item, sell_price)

            if sell_ok:
                final_balance = await get_real_steam_balance()
                db.add_trade(
                    item_name=item_name, market_hash_name=hash_name,
                    trade_type="sell", buy_price=lowest, sell_price=sell_price,
                    market_price=median, profit=actual_profit, profit_after_fee=actual_profit,
                    status="listed", test_mode=False
                )
                await log(f"✅ [LIVE] {item_name} выставлен на продажу за {sell_price:.2f}{curr_sym}", "success", item_name, mode, "listed")
                tg_sell = tg.format_sale(item_name, sell_price, lowest, actual_profit, final_balance, mode, curr_sym)
                await send_tg(tg_sell)
            else:
                await log(f"❌ [LIVE] Ошибка выставления на продажу {item_name}: {sell_err}", "error", item_name, mode, "list_error")
                await send_tg(tg.format_error(f"Ошибка выставления {item_name} на продажу: {sell_err}", item_name, mode))
        else:
            await log(f"❌ [LIVE] Ошибка покупки {item_name}: {error_msg}", "error", item_name, mode, "buy_error")
            await send_tg(tg.format_error(f"Ошибка покупки {item_name}: {error_msg}", item_name, mode))


async def execute_real_buy(item: dict, price: float, market_price: float) -> tuple:
    """
    Выполнение реальной покупки через Steam Market.
    Требует корректной сессии steampy.
    Возвращает (success: bool, error_msg: str)
    """
    try:
        return False, "Для реальной торговли необходимо настроить steampy и Steam Guard. Проверьте настройки."
    except Exception as e:
        return False, str(e)


async def execute_real_sell(item: dict, price: float) -> tuple:
    """
    Выполнение реальной продажи через Steam Market.
    Возвращает (success: bool, error_msg: str)
    """
    try:
        return False, "Для реальной торговли необходимо настроить steampy и Steam Guard. Проверьте настройки."
    except Exception as e:
        return False, str(e)


async def bot_loop():
    """Основной цикл бота"""
    global _bot_running
    mode = get_current_mode()
    interval = int(db.get_setting("check_interval", "15"))
    balance = await get_balance()
    curr_sym = get_currency_symbol(db.get_setting("steam_currency", "5"))

    await log(f"🚀 Бот запущен в режиме {mode} | Баланс: {balance:.2f}{curr_sym}", "success", mode=mode, stage="start")

    token = db.get_setting("telegram_bot_token", "")
    chat_id = db.get_setting("telegram_chat_id", "")
    stats = db.get_statistics()
    if token and chat_id:
        await send_tg(tg.format_bot_started(mode, balance, curr_sym))

    db.add_balance_history(balance, mode)
    cycle = 0

    while _bot_running:
        cycle += 1
        items = db.get_items()
        curr_sym = get_currency_symbol(db.get_setting("steam_currency", "5"))

        if not items:
            await log("⚠️ Нет предметов для мониторинга. Добавьте предметы в настройках.", "warning", mode=mode, stage="no_items")
            await asyncio.sleep(interval)
            continue

        await log(f"🔄 Цикл #{cycle} | Режим: {mode} | Предметов: {len(items)} | Интервал: {interval}с", "info", mode=mode, stage="cycle_start")

        for item in items:
            if not _bot_running:
                break
            try:
                await process_item(item, mode)
                await asyncio.sleep(2)
            except Exception as e:
                err_msg = f"❌ Критическая ошибка обработки {item['name']}: {str(e)}"
                await log(err_msg, "error", item["name"], mode, "item_error")
                await send_tg(tg.format_error(str(e), item["name"], mode))

        if _bot_running:
            await log(f"⏱️ Ожидание {interval} секунд до следующей проверки...", "info", mode=mode, stage="waiting")
            await asyncio.sleep(interval)

    mode = get_current_mode()
    balance = await get_balance()
    stats = db.get_statistics()
    curr_sym = get_currency_symbol(db.get_setting("steam_currency", "5"))
    await log(f"🛑 Бот остановлен | Баланс: {balance:.2f}{curr_sym}", "warning", mode=mode, stage="stopped")
    if token and chat_id:
        await send_tg(tg.format_bot_stopped(mode, stats, curr_sym))


async def start_bot() -> bool:
    global _bot_running, _bot_task
    if _bot_running:
        return False
    _bot_running = True
    _bot_task = asyncio.create_task(bot_loop())
    return True


async def stop_bot() -> bool:
    global _bot_running, _bot_task
    if not _bot_running:
        return False
    _bot_running = False
    if _bot_task:
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            pass
        _bot_task = None
    return True
