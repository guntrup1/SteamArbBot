import asyncio
import aiohttp
from datetime import datetime

async def send_telegram_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Отправка сообщения в Telegram. Возвращает (успех, описание_ошибки)"""
    if not token or not chat_id:
        return False, "Токен или Chat ID не указаны"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return True, ""
                description = data.get("description", "Неизвестная ошибка")
                error_code = data.get("error_code", "")
                return False, f"Telegram: {description} (код {error_code})"
    except aiohttp.ClientConnectorError:
        return False, "Нет соединения с Telegram API"
    except asyncio.TimeoutError:
        return False, "Превышено время ожидания ответа от Telegram"
    except Exception as e:
        return False, f"Ошибка: {str(e)}"


def format_bot_started(mode: str, balance: float, currency_symbol: str = "₽") -> str:
    now = datetime.now().strftime("%H:%M:%S %d.%m.%Y")
    mode_label = "🧪 ТЕСТОВЫЙ" if mode == "TEST" else "🔴 РЕАЛЬНЫЙ"
    return (
        f"🤖 <b>БОТ ЗАПУЩЕН</b>\n\n"
        f"Режим: {mode_label}\n"
        f"Баланс: <b>{balance:.2f}{currency_symbol}</b>\n"
        f"Время: {now}"
    )


def format_bot_stopped(mode: str, stats: dict, currency_symbol: str = "₽") -> str:
    now = datetime.now().strftime("%H:%M:%S %d.%m.%Y")
    mode_label = "🧪 ТЕСТОВЫЙ" if mode == "TEST" else "🔴 РЕАЛЬНЫЙ"
    profit = stats.get("total_profit") or 0
    trades = stats.get("total_trades") or 0
    return (
        f"🛑 <b>БОТ ОСТАНОВЛЕН</b>\n\n"
        f"Режим: {mode_label}\n"
        f"Сделок в сессии: {trades}\n"
        f"Прибыль сессии: <b>{profit:.2f}{currency_symbol}</b>\n"
        f"Время: {now}"
    )


def format_purchase(item_name: str, buy_price: float, market_price: float,
                    profit: float, balance: float, mode: str,
                    steam_url: str = "", currency_symbol: str = "₽") -> str:
    mode_label = "🧪 ТЕСТ" if mode == "TEST" else "💵 РЕАЛЬНАЯ"
    url_line = f"\n🔗 <a href='{steam_url}'>Посмотреть на Steam</a>" if steam_url else ""
    discount = ((market_price - buy_price) / market_price * 100) if market_price > 0 else 0
    return (
        f"🛒 <b>ПОКУПКА [{mode_label}]</b>\n\n"
        f"Предмет: <b>{item_name}</b>\n"
        f"Цена покупки: <b>{buy_price:.2f}{currency_symbol}</b>\n"
        f"Рыночная цена: {market_price:.2f}{currency_symbol}\n"
        f"Скидка: {discount:.1f}%\n"
        f"Ожидаемая прибыль: <b>{profit:.2f}{currency_symbol}</b>\n"
        f"Баланс: {balance:.2f}{currency_symbol}"
        f"{url_line}"
    )


def format_sale(item_name: str, sell_price: float, buy_price: float,
                profit: float, balance: float, mode: str,
                currency_symbol: str = "₽") -> str:
    mode_label = "🧪 ТЕСТ" if mode == "TEST" else "💵 РЕАЛЬНАЯ"
    emoji = "✅" if profit > 0 else "❌"
    return (
        f"{emoji} <b>ПРОДАЖА [{mode_label}]</b>\n\n"
        f"Предмет: <b>{item_name}</b>\n"
        f"Цена продажи: <b>{sell_price:.2f}{currency_symbol}</b>\n"
        f"Цена покупки: {buy_price:.2f}{currency_symbol}\n"
        f"Прибыль: <b>{profit:.2f}{currency_symbol}</b>\n"
        f"Баланс: {balance:.2f}{currency_symbol}"
    )


def format_balance_change(old_balance: float, new_balance: float, mode: str, currency_symbol: str = "₽") -> str:
    diff = new_balance - old_balance
    emoji = "📈" if diff >= 0 else "📉"
    mode_label = "🧪 ТЕСТ" if mode == "TEST" else "💵 РЕАЛЬНЫЙ"
    return (
        f"{emoji} <b>ИЗМЕНЕНИЕ БАЛАНСА [{mode_label}]</b>\n\n"
        f"Было: {old_balance:.2f}{currency_symbol}\n"
        f"Стало: <b>{new_balance:.2f}{currency_symbol}</b>\n"
        f"Изменение: {'+' if diff >= 0 else ''}{diff:.2f}{currency_symbol}"
    )


def format_error(error_msg: str, item_name: str = None, mode: str = "TEST") -> str:
    mode_label = "🧪 ТЕСТ" if mode == "TEST" else "💵 РЕАЛЬНЫЙ"
    item_line = f"\nПредмет: {item_name}" if item_name else ""
    return (
        f"⚠️ <b>ОШИБКА [{mode_label}]</b>"
        f"{item_line}\n\n"
        f"{error_msg}"
    )
