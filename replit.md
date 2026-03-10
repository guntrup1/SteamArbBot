# Steam Market Bot

Automated Steam Community Market trading bot built with FastAPI.

## Overview

The bot monitors selected Steam Market items every 10–300 seconds, buys when the price drops ≥17% below median (accounting for Steam's 15% commission), and auto-lists items for sale.

## Features

- **TEST mode** — virtual balance, simulated trades, real price data
- **LIVE mode** — real Steam balance, real buy/sell transactions
- **Real-time WebSocket logs** — live trading log stream to the dashboard
- **Telegram notifications** — buy/sell/error alerts with item details, prices, profit
- **PostgreSQL persistence** — items, trades, logs, settings, balance history (survives restarts and redeployments)
- **Market Scanner** — scan Steam market for profitable items with discount filter, volume stats, 7-day price history analysis, add to watchlist
- **API Logs** — all Steam API requests/responses logged to PostgreSQL and visible on scanner page
- **Step-by-step settings page** — instructions for Steam API, Telegram, strategy

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Uvicorn, aiohttp
- **Frontend**: Vanilla JS, WebSocket, dark theme CSS
- **Database**: PostgreSQL via `psycopg2-binary` (DATABASE_URL env var)
- **Notifications**: python-telegram-bot / aiohttp direct API
- **Port**: 5000

## Project Structure

```
main.py                  # FastAPI app, all routes, WebSocket endpoint
steam_bot/
  __init__.py
  config.py              # Constants: commission (15%), thresholds, URLs
  database.py            # PostgreSQL helpers: settings, items, trades, logs
  market.py              # Steam Market price API, search, buy analysis
  trading.py             # Bot loop, buy/sell logic, WS broadcast, mode mgmt
  telegram_bot.py        # Telegram message formatters + async sender (started/stopped/buy/sell/balance/error)
templates/
  dashboard.html         # Main dashboard: stats, items, logs, trades
  settings.html          # Settings page: instructions, item search, all fields
static/
  style.css              # Dark theme CSS
  app.js                 # WebSocket client, bot control, item search, settings
```

## Key Business Logic

- **Buy threshold**: minimum 17% discount from median price (enforced in both UI and server)
- **Profit formula**: `profit = (sell_price × 0.85) - buy_price` (Steam takes 15%)
- **Currencies**: 5=RUB, 1=USD, 3=EUR, 18=UAH
- **Price cache**: 30 seconds per item to avoid Steam API rate limits
- **Hourly buy limit**: configurable, default 10 buys/hour

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
| `steam_currency` | `5` | Currency code |
| `telegram_bot_token` | `` | Telegram bot token |
| `telegram_chat_id` | `` | Telegram chat ID |

## Running

```bash
python main.py
```

App runs on `http://0.0.0.0:5000`
