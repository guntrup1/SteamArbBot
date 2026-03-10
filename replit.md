# Steam Market Bot

Automated Steam Community Market trading bot built with FastAPI.

## Overview

The bot monitors selected Steam Market items every 10–300 seconds, buys when the price drops ≥17% below median (accounting for Steam's 15% commission), and auto-lists items for sale.

## Features

- **TEST mode** — virtual balance, simulated trades, real price data
- **LIVE mode** — real Steam balance, real buy/sell transactions (requires Steam Guard)
- **Real-time WebSocket logs** — live trading log stream to the dashboard
- **Telegram notifications** — buy/sell/error alerts in both TEST and LIVE modes
- **PostgreSQL persistence** — items, trades, logs, settings, balance history
- **Market Scanner** — weapon type presets, paginated search (3 pages × 50), 14-day price history from listing pages, rate-limit protection
- **Price History Analysis** — parses `var line1` from Steam listing pages (public, no auth needed), computes own median from 14-day data, identifies items with recent discount sales
- **Persistent Error Log** — errors/warnings stay visible for 15 seconds with close button + collapsible error log panel (bottom-left) with full history
- **API Logs** — all Steam API requests/responses logged to PostgreSQL
- **Settings with tabs** — Предметы, Стратегия, Режим, Steam, Telegram — each with status indicators and guides

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Uvicorn, aiohttp
- **Frontend**: Vanilla JS, WebSocket, dark theme CSS
- **Database**: PostgreSQL via `psycopg2-binary` (DATABASE_URL env var)
- **Notifications**: aiohttp direct Telegram Bot API
- **Port**: 5000

## Project Structure

```
main.py                  # FastAPI app, all routes, WebSocket, bot start validation
steam_bot/
  __init__.py
  config.py              # Constants: commission (15%), thresholds, URLs, currencies
  database.py            # PostgreSQL helpers: settings, items, trades, logs, api_logs
  market.py              # Steam Market API: _steam_get, scan_market with history, price analysis
  trading.py             # Bot loop, buy/sell logic, WS broadcast, mode mgmt
  telegram_bot.py        # Telegram formatters + async sender
templates/
  dashboard.html         # Dashboard: stats, items, logs, trades
  scanner.html           # Scanner: weapon presets, scan params, results with history, API logs
  settings.html          # Settings: 5 tabs (Items, Strategy, Mode, Steam, Telegram)
static/
  style.css              # Dark theme CSS
  app.js                 # WebSocket client, bot control, item search, settings, error log panel
```

## Key Business Logic

- **Buy threshold**: minimum 17% discount from median price AND positive net profit after 15% commission
- **Profit formula**: `profit = (sell_price × 0.85) - buy_price` (Steam takes 15%)
- **sell_price in Steam search API**: always USD cents regardless of currency param
- **Price cache**: 300 seconds per item (avoids rate limits)
- **Price history**: fetched from listing page HTML (`var line1=`), 14-day window, own median computed (avoids currency mismatch with priceoverview)
- **Scanner result fields**: `is_profitable` (current discount ≥ threshold + net profit > 0), `had_recent_discounts` (14-day history has sales ≥ threshold below median), `worth_tracking` (either profitable or recent discount history)
- **Rate limiting**: global asyncio.Semaphore(1), random 1.5–3s delay between requests, 429 retry with 35–50s wait
- **History cache**: 600 seconds per listing page
- **Error log panel**: errors/warnings stored in JS array (max 50), shown in collapsible panel bottom-left, toasts stay 15s for errors (4s for info/success)

## Settings (stored in PostgreSQL)

| Key | Default | Description |
|-----|---------|-------------|
| `test_mode` | `1` | 1=TEST, 0=LIVE |
| `virtual_balance` | `1000` | Starting virtual balance for TEST |
| `current_virtual_balance` | `1000` | Current virtual balance |
| `buy_threshold` | `17` | Min discount % to trigger buy |
| `check_interval` | `15` | Seconds between price checks |
| `max_buys_per_hour` | `10` | Hourly buy limit |
| `sell_strategy` | `market` | `market` or `market_minus` |
| `sell_discount` | `1` | % below market for market_minus strategy |
| `steam_currency` | `5` | Currency code (5=RUB, 1=USD, 3=EUR, 18=UAH) |
| `telegram_bot_token` | `` | Telegram bot token |
| `telegram_chat_id` | `` | Telegram chat ID |

## Running

```bash
python main.py
```

App runs on `http://0.0.0.0:5000`
