import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.constants import ParseMode

from steam_bot import database as db

logger = logging.getLogger(__name__)

_tg_app = None
_allowed_chat_id = None
_restart_lock = None


def _get_lock():
    import asyncio
    global _restart_lock
    if _restart_lock is None:
        _restart_lock = asyncio.Lock()
    return _restart_lock


def _check_auth(chat_id: int) -> bool:
    if not _allowed_chat_id:
        return False
    return str(chat_id) == str(_allowed_chat_id)


async def _validate_start_bot():
    from steam_bot import trading
    if trading.is_running():
        return False, "🤖 Бот уже запущен!"
    items = db.get_items()
    if not items:
        return False, "❌ Нет предметов для мониторинга. Добавьте через веб-интерфейс."
    settings = db.get_all_settings()
    mode = "TEST" if settings.get("test_mode", "1") == "1" else "LIVE"
    if mode == "LIVE":
        if not settings.get("steam_api_key"):
            return False, "❌ LIVE: не указан Steam API Key."
        if not settings.get("steam_login") or not settings.get("steam_password"):
            return False, "❌ LIVE: не указаны Steam логин/пароль."
    if mode == "TEST":
        try:
            balance = float(settings.get("current_virtual_balance", "1000"))
        except (ValueError, TypeError):
            balance = 0
        if balance <= 0:
            return False, "❌ Виртуальный баланс = 0."
    ok = await trading.start_bot()
    if ok:
        return True, f"✅ Бот запущен в режиме <b>{mode}</b>!"
    return False, "❌ Ошибка запуска бота."


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        await update.message.reply_text("⛔ Доступ запрещён. Ваш Chat ID не совпадает с настройками бота.")
        return
    text = (
        "🤖 <b>Steam Market Bot</b>\n\n"
        "Доступные команды:\n\n"
        "📊 /status — Статус бота, баланс, статистика\n"
        "▶️ /start_bot — Запустить торгового бота\n"
        "⏹ /stop_bot — Остановить торгового бота\n"
        "⭐ /portfolio — Портфель (избранные предметы)\n"
        "📦 /items — Предметы на мониторинге\n"
        "📈 /trades — Последние сделки\n"
        "📋 /logs — Последние логи\n"
        "⚙️ /mode — Переключить TEST/LIVE режим\n"
        "❓ /help — Помощь"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    text = (
        "❓ <b>Справка по командам</b>\n\n"
        "/status — Текущий статус: режим, баланс, запущен ли бот, статистика сделок\n"
        "/start_bot — Запускает торгового бота (проверяет предметы и настройки)\n"
        "/stop_bot — Останавливает торгового бота\n"
        "/portfolio — Показывает все избранные предметы с ценами и прибылью\n"
        "/items — Список предметов на мониторинге\n"
        "/trades — Последние 10 сделок\n"
        "/logs — Последние 15 логов\n"
        "/mode — Переключить между TEST и LIVE\n\n"
        "💡 Бот работает с тем же аккаунтом и настройками что и веб-интерфейс."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    from steam_bot import trading
    settings = db.get_all_settings()
    mode = "TEST" if settings.get("test_mode", "1") == "1" else "LIVE"
    mode_emoji = "🧪" if mode == "TEST" else "🔴"
    running = trading.is_running()
    running_label = "✅ Запущен" if running else "⏹ Остановлен"

    if mode == "TEST":
        try:
            balance = float(settings.get("current_virtual_balance", "1000"))
        except (ValueError, TypeError):
            balance = 0
        balance_label = f"💰 Виртуальный: <b>${balance:.2f}</b>"
    else:
        balance = 0
        balance_label = "💰 Steam баланс (LIVE)"

    stats_test = db.get_statistics(test_mode=True)
    stats_live = db.get_statistics(test_mode=False)
    items = db.get_items()
    favs = db.get_favorites()

    text = (
        f"📊 <b>СТАТУС БОТА</b>\n\n"
        f"Состояние: {running_label}\n"
        f"Режим: {mode_emoji} <b>{mode}</b>\n"
        f"{balance_label}\n\n"
        f"📦 Предметов на мониторинге: <b>{len(items)}</b>\n"
        f"⭐ В портфеле: <b>{len(favs)}</b>\n\n"
        f"🧪 <b>TEST статистика:</b>\n"
        f"  Сделок: {stats_test.get('total_trades', 0)}\n"
        f"  Прибыль: ${(stats_test.get('total_profit', 0) or 0):.2f}\n"
        f"  Сегодня: ${(stats_test.get('daily_profit', 0) or 0):.2f}\n\n"
        f"🔴 <b>LIVE статистика:</b>\n"
        f"  Сделок: {stats_live.get('total_trades', 0)}\n"
        f"  Прибыль: ${(stats_live.get('total_profit', 0) or 0):.2f}\n"
        f"  Сегодня: ${(stats_live.get('daily_profit', 0) or 0):.2f}"
    )

    kb = []
    if running:
        kb.append([InlineKeyboardButton("⏹ Остановить бота", callback_data="stop_bot")])
    else:
        kb.append([InlineKeyboardButton("▶️ Запустить бота", callback_data="start_bot")])
    kb.append([
        InlineKeyboardButton("⭐ Портфель", callback_data="portfolio"),
        InlineKeyboardButton("📦 Предметы", callback_data="items"),
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=InlineKeyboardMarkup(kb))


async def cmd_start_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    try:
        ok, msg = await _validate_start_bot()
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"start_bot command error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {_esc(str(e))}", parse_mode=ParseMode.HTML)


async def cmd_stop_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    try:
        from steam_bot import trading
        if not trading.is_running():
            await update.message.reply_text("🤖 Бот не запущен.")
            return
        ok = await trading.stop_bot()
        if ok:
            await update.message.reply_text("⏹ Бот остановлен.")
        else:
            await update.message.reply_text("❌ Ошибка остановки.")
    except Exception as e:
        logger.error(f"stop_bot command error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {_esc(str(e))}", parse_mode=ParseMode.HTML)


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    favs = db.get_favorites()
    if not favs:
        await update.message.reply_text("⭐ Портфель пуст.\nДобавляйте предметы через веб-интерфейс → Арбитраж → кнопка ⭐")
        return
    stats = db.get_portfolio_stats()
    header = (
        f"⭐ <b>ПОРТФЕЛЬ</b> ({len(favs)} предметов)\n\n"
        f"💰 Потрачено: <b>${stats['total_spent']:.2f}</b>\n"
        f"📈 Потенц. прибыль: <b>${stats['potential_profit']:.2f}</b>\n"
        f"✅ Факт. прибыль: <b>${stats['actual_profit']:.2f}</b>\n"
        f"📦 Куплено: {stats['total_items_bought']} / Продано: {stats['total_items_sold']}\n"
        f"{'─' * 28}\n"
    )
    items_text = []
    for f in favs[:15]:
        buy_p = f.get("buy_price", 0) or 0
        sell_p = f.get("sell_price", 0) or 0
        bought = f.get("items_bought", 0) or 0
        sold = f.get("items_sold", 0) or 0
        spent = f.get("total_spent", 0) or 0
        remaining = bought - sold
        pot_profit = remaining * (sell_p * 0.85 - buy_p) if remaining > 0 else 0
        status_map = {"watching": "👁", "buying": "🛒", "selling": "📤", "done": "✅"}
        st = status_map.get(f.get("status", "watching"), "👁")
        name = _esc(f.get("name", "?"))
        line = (
            f"{st} <b>{name}</b>\n"
            f"   Бай: ${buy_p:.2f} → Продажа: ${sell_p:.2f}\n"
            f"   Куплено: {bought} | Остаток: {remaining}\n"
            f"   Потрачено: ${spent:.2f} | Потенц: ${pot_profit:.2f}"
        )
        items_text.append(line)

    text = header + "\n\n".join(items_text)
    if len(favs) > 15:
        text += f"\n\n... и ещё {len(favs) - 15} предметов (смотри в веб-интерфейсе)"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_items(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    items = db.get_items()
    if not items:
        await update.message.reply_text("📦 Нет предметов на мониторинге.\nДобавьте через веб-интерфейс → Настройки или Сканер.")
        return
    text = f"📦 <b>ПРЕДМЕТЫ НА МОНИТОРИНГЕ</b> ({len(items)})\n\n"
    app_names = {"440": "TF2", "570": "Dota2", "730": "CS2"}
    for i, item in enumerate(items[:20], 1):
        name = _esc(item.get("name", "?"))
        app_id = str(item.get("app_id", "?"))
        game = app_names.get(app_id, app_id)
        text += f"{i}. [{game}] <b>{name}</b>\n"
    if len(items) > 20:
        text += f"\n... и ещё {len(items) - 20}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    trades = db.get_trades(10)
    if not trades:
        await update.message.reply_text("📈 Сделок пока нет.")
        return
    text = "📈 <b>ПОСЛЕДНИЕ СДЕЛКИ</b>\n\n"
    for t in reversed(trades[-10:]):
        name = _esc(t.get("item_name", "?"))
        ttype = "🛒 BUY" if t.get("trade_type") == "buy" else "📤 SELL"
        mode = "🧪" if t.get("test_mode") == 1 else "🔴"
        price = t.get("buy_price") or t.get("sell_price") or 0
        profit = t.get("profit_after_fee")
        profit_str = f" | Прибыль: ${profit:.2f}" if profit else ""
        dt = ""
        if t.get("created_at"):
            try:
                dt = datetime.fromisoformat(t["created_at"]).strftime(" %H:%M %d.%m")
            except Exception:
                pass
        text += f"{mode} {ttype} <b>{name}</b> — ${price:.2f}{profit_str}{dt}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    logs = db.get_logs(15)
    if not logs:
        await update.message.reply_text("📋 Логов пока нет.")
        return
    text = "📋 <b>ПОСЛЕДНИЕ ЛОГИ</b>\n\n"
    level_emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "success": "✅"}
    for log in logs[-15:]:
        emoji = level_emoji.get(log.get("level", "info"), "ℹ️")
        msg = _esc(log.get("message", ""))[:100]
        dt = ""
        if log.get("created_at"):
            try:
                dt = datetime.fromisoformat(log["created_at"]).strftime("%H:%M ")
            except Exception:
                pass
        text += f"{dt}{emoji} {msg}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _check_auth(update.effective_chat.id):
        return
    from steam_bot import trading
    if trading.is_running():
        await update.message.reply_text("⚠️ Остановите бота перед сменой режима.\n/stop_bot")
        return
    settings = db.get_all_settings()
    current = "TEST" if settings.get("test_mode", "1") == "1" else "LIVE"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 TEST" + (" ✓" if current == "TEST" else ""), callback_data="set_mode_test"),
            InlineKeyboardButton("🔴 LIVE" + (" ✓" if current == "LIVE" else ""), callback_data="set_mode_live"),
        ]
    ])
    await update.message.reply_text(
        f"⚙️ Текущий режим: <b>{current}</b>\nВыберите режим:",
        parse_mode=ParseMode.HTML, reply_markup=kb
    )


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _check_auth(query.message.chat.id):
        await query.answer("⛔ Доступ запрещён")
        return
    await query.answer()
    data = query.data

    try:
        if data == "start_bot":
            ok, msg = await _validate_start_bot()
            await query.message.reply_text(msg, parse_mode=ParseMode.HTML)

        elif data == "stop_bot":
            from steam_bot import trading
            if not trading.is_running():
                await query.message.reply_text("🤖 Бот не запущен.")
                return
            ok = await trading.stop_bot()
            if ok:
                await query.message.reply_text("⏹ Бот остановлен.")
            else:
                await query.message.reply_text("❌ Ошибка остановки.")

        elif data == "portfolio":
            favs = db.get_favorites()
            if not favs:
                await query.message.reply_text("⭐ Портфель пуст.")
                return
            stats = db.get_portfolio_stats()
            text = (
                f"⭐ <b>ПОРТФЕЛЬ</b> ({len(favs)})\n\n"
                f"💰 Потрачено: ${stats['total_spent']:.2f}\n"
                f"📈 Потенц: ${stats['potential_profit']:.2f}\n"
                f"✅ Факт: ${stats['actual_profit']:.2f}\n\n"
            )
            for f in favs[:10]:
                name = _esc(f.get("name", "?"))
                buy_p = f.get("buy_price", 0) or 0
                sell_p = f.get("sell_price", 0) or 0
                text += f"• <b>{name}</b>: ${buy_p:.2f} → ${sell_p:.2f}\n"
            await query.message.reply_text(text, parse_mode=ParseMode.HTML)

        elif data == "items":
            items = db.get_items()
            if not items:
                await query.message.reply_text("📦 Нет предметов.")
                return
            text = f"📦 <b>Предметы</b> ({len(items)})\n\n"
            for i, item in enumerate(items[:15], 1):
                text += f"{i}. {_esc(item.get('name', '?'))}\n"
            await query.message.reply_text(text, parse_mode=ParseMode.HTML)

        elif data == "set_mode_test":
            from steam_bot import trading
            if trading.is_running():
                await query.message.reply_text("⚠️ Остановите бота сначала.")
                return
            db.set_setting("test_mode", "1")
            await query.message.reply_text("🧪 Режим переключён на <b>TEST</b>", parse_mode=ParseMode.HTML)

        elif data == "set_mode_live":
            from steam_bot import trading
            if trading.is_running():
                await query.message.reply_text("⚠️ Остановите бота сначала.")
                return
            db.set_setting("test_mode", "0")
            await query.message.reply_text("🔴 Режим переключён на <b>LIVE</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"callback error ({data}): {e}")
        await query.message.reply_text(f"❌ Ошибка: {_esc(str(e))}", parse_mode=ParseMode.HTML)


def _esc(text: str) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def start_telegram_bot():
    global _tg_app, _allowed_chat_id
    token = db.get_setting("telegram_bot_token", "")
    chat_id = db.get_setting("telegram_chat_id", "")
    if not token:
        logger.info("Telegram bot token not set — bot commands disabled")
        return
    _allowed_chat_id = chat_id
    try:
        _tg_app = Application.builder().token(token).build()
        _tg_app.add_handler(CommandHandler("start", cmd_start))
        _tg_app.add_handler(CommandHandler("help", cmd_help))
        _tg_app.add_handler(CommandHandler("status", cmd_status))
        _tg_app.add_handler(CommandHandler("start_bot", cmd_start_bot))
        _tg_app.add_handler(CommandHandler("stop_bot", cmd_stop_bot))
        _tg_app.add_handler(CommandHandler("portfolio", cmd_portfolio))
        _tg_app.add_handler(CommandHandler("items", cmd_items))
        _tg_app.add_handler(CommandHandler("trades", cmd_trades))
        _tg_app.add_handler(CommandHandler("logs", cmd_logs))
        _tg_app.add_handler(CommandHandler("mode", cmd_mode))
        _tg_app.add_handler(CallbackQueryHandler(callback_handler))

        commands = [
            BotCommand("status", "📊 Статус бота и статистика"),
            BotCommand("start_bot", "▶️ Запустить торгового бота"),
            BotCommand("stop_bot", "⏹ Остановить бота"),
            BotCommand("portfolio", "⭐ Портфель избранных"),
            BotCommand("items", "📦 Предметы на мониторинге"),
            BotCommand("trades", "📈 Последние сделки"),
            BotCommand("logs", "📋 Последние логи"),
            BotCommand("mode", "⚙️ Переключить TEST/LIVE"),
            BotCommand("help", "❓ Справка по командам"),
        ]

        await _tg_app.initialize()
        await _tg_app.bot.set_my_commands(commands)
        await _tg_app.start()
        await _tg_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot commands started (polling)")
    except Exception as e:
        logger.error(f"Failed to start Telegram bot: {e}")
        _tg_app = None


async def stop_telegram_bot():
    global _tg_app
    if _tg_app:
        try:
            await _tg_app.updater.stop()
            await _tg_app.stop()
            await _tg_app.shutdown()
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")
        _tg_app = None
