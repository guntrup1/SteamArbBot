import asyncio
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from steam_bot import database as db
from steam_bot import market as mkt
from steam_bot import trading
from steam_bot.config import SESSION_SECRET, HOST, PORT, get_currency_symbol, CURRENCY_INFO

db.init_db()

app = FastAPI(title="Steam Market Bot")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    settings = db.get_all_settings()
    items = db.get_items()
    logs = db.get_logs(50)
    trades = db.get_trades(20)
    mode = "TEST" if settings.get("test_mode", "1") == "1" else "LIVE"
    is_running = trading.is_running()
    if mode == "TEST":
        balance = float(settings.get("current_virtual_balance", "1000"))
    else:
        balance = await trading.get_real_steam_balance()
    stats_test = db.get_statistics(test_mode=True)
    stats_live = db.get_statistics(test_mode=False)
    currency_code = settings.get("steam_currency", "5")
    currency_symbol = get_currency_symbol(currency_code)
    currency_info = CURRENCY_INFO.get(currency_code, CURRENCY_INFO["5"])
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "settings": settings,
        "items": items,
        "logs": logs,
        "trades": trades,
        "mode": mode,
        "is_running": is_running,
        "balance": balance,
        "stats_test": stats_test,
        "stats_live": stats_live,
        "currency_symbol": currency_symbol,
        "currency_info": currency_info,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    settings = db.get_all_settings()
    items = db.get_items()
    mode = "TEST" if settings.get("test_mode", "1") == "1" else "LIVE"
    currency_code = settings.get("steam_currency", "5")
    currency_symbol = get_currency_symbol(currency_code)
    currency_info = CURRENCY_INFO.get(currency_code, CURRENCY_INFO["5"])
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "items": items,
        "mode": mode,
        "currency_symbol": currency_symbol,
        "currency_info": currency_info,
        "currency_info_all": CURRENCY_INFO,
    })


@app.post("/api/bot/start")
async def start_bot():
    if trading.is_running():
        return JSONResponse({"success": False, "message": "Бот уже запущен"})
    ok = await trading.start_bot()
    return JSONResponse({"success": ok, "message": "Бот запущен" if ok else "Ошибка запуска"})


@app.post("/api/bot/stop")
async def stop_bot():
    if not trading.is_running():
        return JSONResponse({"success": False, "message": "Бот не запущен"})
    ok = await trading.stop_bot()
    return JSONResponse({"success": ok, "message": "Бот остановлен" if ok else "Ошибка остановки"})


@app.get("/api/bot/status")
async def bot_status():
    settings = db.get_all_settings()
    mode = "TEST" if settings.get("test_mode", "1") == "1" else "LIVE"
    is_running = trading.is_running()
    if mode == "TEST":
        balance = float(settings.get("current_virtual_balance", "1000"))
    else:
        balance = await trading.get_real_steam_balance()
    stats = db.get_statistics()
    return JSONResponse({
        "running": is_running,
        "mode": mode,
        "balance": round(balance, 2),
        "stats": {
            "total_trades": stats.get("total_trades") or 0,
            "total_profit": round(stats.get("total_profit") or 0, 2),
            "daily_profit": round(stats.get("daily_profit") or 0, 2),
        }
    })


@app.post("/api/settings/save")
async def save_settings(request: Request):
    data = await request.json()
    allowed_keys = [
        "steam_api_key", "steam_login", "steam_password",
        "steam_shared_secret", "steam_identity_secret",
        "telegram_bot_token", "telegram_chat_id",
        "buy_threshold", "check_interval", "max_buys_per_hour",
        "sell_strategy", "sell_discount", "test_mode",
        "virtual_balance", "steam_currency",
    ]
    for key in allowed_keys:
        if key in data:
            db.set_setting(key, str(data[key]))
    if "virtual_balance" in data and not trading.is_running():
        db.set_setting("current_virtual_balance", str(data["virtual_balance"]))
    return JSONResponse({"success": True, "message": "Настройки сохранены"})


@app.post("/api/settings/mode")
async def set_mode(request: Request):
    data = await request.json()
    mode = data.get("mode", "TEST")
    db.set_setting("test_mode", "1" if mode == "TEST" else "0")
    return JSONResponse({"success": True, "mode": mode})


@app.post("/api/items/add")
async def add_item(request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    hash_name = data.get("hash_name", name).strip()
    app_id = int(data.get("app_id", 730))
    steam_url = data.get("steam_url", "").strip()
    image_url = data.get("image_url", "").strip()
    if not name:
        return JSONResponse({"success": False, "message": "Укажите название предмета"})
    ok, msg = db.add_item(name, hash_name, app_id, steam_url or None, image_url or None)
    return JSONResponse({"success": ok, "message": msg})


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: int):
    db.remove_item(item_id)
    return JSONResponse({"success": True, "message": "Предмет удалён"})


@app.get("/api/items/price/{item_id}")
async def get_item_price(item_id: int):
    items = db.get_items()
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        return JSONResponse({"success": False, "error": "Предмет не найден"})
    settings = db.get_all_settings()
    currency = int(settings.get("steam_currency", "5"))
    threshold = float(settings.get("buy_threshold", "17"))
    data = await mkt.get_item_price(item["market_hash_name"], item.get("app_id", 730), currency)
    if data.get("success"):
        lowest = data["lowest_price"]
        median = data["median_price"]
        buy_ok, discount, reason = mkt.should_buy(lowest, median, threshold)
        profit_info = mkt.calculate_profit(lowest, median)
        return JSONResponse({
            "success": True,
            "lowest_price": lowest,
            "median_price": median,
            "lowest_price_raw": data["lowest_price_raw"],
            "median_price_raw": data["median_price_raw"],
            "volume": data["volume"],
            "should_buy": buy_ok,
            "discount": round(discount, 1),
            "reason": reason,
            "profit_info": profit_info,
        })
    return JSONResponse({"success": False, "error": data.get("error", "Ошибка")})


@app.get("/api/items/search")
async def search_items(q: str, app_id: int = 730):
    results = await mkt.search_item(q, app_id)
    return JSONResponse({"success": True, "results": results})


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    logs = db.get_logs(limit)
    return JSONResponse({"success": True, "logs": logs})


@app.get("/api/trades")
async def get_trades(limit: int = 50, mode: str = None):
    if mode == "TEST":
        trades = db.get_trades(limit, test_mode=True)
    elif mode == "LIVE":
        trades = db.get_trades(limit, test_mode=False)
    else:
        trades = db.get_trades(limit)
    return JSONResponse({"success": True, "trades": trades})


@app.get("/api/stats")
async def get_stats():
    stats_test = db.get_statistics(test_mode=True)
    stats_live = db.get_statistics(test_mode=False)
    return JSONResponse({
        "test": {k: (round(v, 2) if isinstance(v, float) else (v or 0)) for k, v in (stats_test or {}).items()},
        "live": {k: (round(v, 2) if isinstance(v, float) else (v or 0)) for k, v in (stats_live or {}).items()},
    })


@app.post("/api/telegram/test")
async def test_telegram(request: Request):
    from steam_bot import telegram_bot as tg
    data = await request.json()
    token = data.get("token") or db.get_setting("telegram_bot_token", "")
    chat_id = data.get("chat_id") or db.get_setting("telegram_chat_id", "")
    if not token or not chat_id:
        return JSONResponse({"success": False, "message": "Укажите токен и Chat ID"})
    ok, err = await tg.send_telegram_message(token, chat_id,
        "✅ <b>Тест подключения Steam Market Bot</b>\n\nTelegram уведомления работают корректно!")
    if ok:
        return JSONResponse({"success": True, "message": "Сообщение отправлено успешно"})
    return JSONResponse({"success": False, "message": err or "Ошибка — проверьте токен и Chat ID"})


@app.post("/api/virtual_balance/reset")
async def reset_virtual_balance():
    vb = db.get_setting("virtual_balance", "1000")
    db.set_setting("current_virtual_balance", vb)
    return JSONResponse({"success": True, "balance": float(vb), "message": f"Баланс сброшен до {vb}"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    trading.register_ws_client(websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "heartbeat"}))
    except WebSocketDisconnect:
        pass
    finally:
        trading.unregister_ws_client(websocket)


@app.get("/scanner", response_class=HTMLResponse)
async def scanner_page(request: Request):
    settings = db.get_all_settings()
    currency_code = settings.get("steam_currency", "5")
    currency_symbol = get_currency_symbol(currency_code)
    return templates.TemplateResponse("scanner.html", {
        "request": request,
        "settings": settings,
        "currency_symbol": currency_symbol,
    })


@app.post("/api/scanner/scan")
async def scanner_scan(request: Request):
    data = await request.json()
    query = data.get("query", "").strip()
    app_id = int(data.get("app_id", 730))
    min_price_usd = float(data.get("min_price_usd", 1.0))
    threshold_pct = float(data.get("threshold_pct", 17.0))
    max_results = min(int(data.get("max_results", 30)), 60)
    settings = db.get_all_settings()
    currency = int(settings.get("steam_currency", "5"))
    results = await mkt.scan_market(
        query=query, app_id=app_id, currency=currency,
        min_price_usd=min_price_usd, threshold_pct=threshold_pct,
        max_results=max_results
    )
    return JSONResponse({"success": True, "results": results, "count": len(results)})


@app.get("/api/logs/api")
async def get_api_logs_endpoint(limit: int = 200):
    logs = db.get_api_logs(limit)
    return JSONResponse({"success": True, "logs": logs})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
