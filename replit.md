# Steam Market Bot v2.0

Automated Steam Community Market trading bot for **TF2 (440)** and **Dota 2 (570)** built with FastAPI.

## Overview

The bot scans Steam Market for liquid items (600+ sales/week), compares buy order prices vs market prices (17%+ spread), verifies 1-week history shows sales at both price levels, detects price manipulation, and auto-lists purchased items at market price.

## Features

- **TF2 + Dota 2 focused** — presets for keys, cosmetics, weapons, arcana, immortals, etc.
- **Buy Order Analysis** — fetches `itemordershistogram` API for buy/sell order data
- **Spread Detection** — identifies items where market price is 17%+ above highest buy order
- **Liquidity Filter** — requires 600+ weekly sales from price history
- **History Level Verification** — checks that actual sales occurred at both buy order and sell order price levels
- **Anomaly Detection** — flags price manipulation (high volatility, volume spikes, extreme sales)
- **TEST mode** — virtual balance, simulated trades, real price data
- **LIVE mode** — real Steam balance, real buy/sell transactions (requires Steam Guard)
- **Real-time WebSocket logs** — live trading log stream to the dashboard
- **Telegram notifications** — buy/sell/error alerts in both TEST and LIVE modes
- **PostgreSQL persistence** — items, trades, logs, settings, balance history
- **Persistent Error Log** — errors/warnings stay visible for 15 seconds with close button + collapsible error log panel (bottom-left) with full history
- **API Logs** — all Steam API requests/responses logged to PostgreSQL

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
  config.py              # Constants: commission (15%), thresholds, URLs, app IDs (440, 570)
  database.py            # PostgreSQL helpers: settings, items, trades, logs, api_logs
  market.py              # Steam Market API: scan_market, buy orders, anomaly detection, history analysis
  trading.py             # Bot loop, buy/sell logic, WS broadcast, mode mgmt
  telegram_bot.py        # Telegram formatters + async sender
templates/
  dashboard.html         # Dashboard: stats, items, logs, trades
  scanner.html           # Scanner: TF2/Dota2 presets, buy orders, spread, anomalies, results
  settings.html          # Settings: 5 tabs (Items, Strategy, Mode, Steam, Telegram)
static/
  style.css              # Dark theme CSS
  app.js                 # WebSocket client, bot control, item search, settings, error log panel
```

## Key Business Logic

- **Target games**: TF2 (440), Dota 2 (570)
- **Minimum price**: $0.20 USD
- **Liquidity threshold**: 600+ sales/week
- **Spread threshold**: 17%+ between highest buy order and lowest sell order
- **Buy Order API**: `itemordershistogram?item_nameid={id}` — returns highest buy order, lowest sell order in USD cents
- **item_nameid extraction**: `Market_LoadOrderSpread(\d+)` regex on listing page HTML
- **History verification**: checks 7-day price history for sales at both buy order level and market level (±15% tolerance)
- **Anomaly detection**: coefficient of variation > 0.3, volume spikes > 3x average, extreme price outliers > 3 std devs
- **Profit formula**: `profit = (sell_price × 0.85) - buy_price` (Steam takes 15%)
- **Auto-list after purchase**: items listed at market price (must be ≥16% above buy price)
- **Rate limiting**: global asyncio.Semaphore(1), random 1.5–3s delay between requests, 429 retry with 35–50s wait
- **Caches**: price (300s), history/listing page (600s), orders (300s)
- **sell_price in Steam search API**: always USD cents regardless of currency param

## Scanner Result Fields

- `is_liquid` — weekly sales ≥ 600
- `has_good_spread` — spread between buy order and sell order ≥ threshold
- `both_levels_traded` — history has sales at both buy and sell price levels
- `is_manipulated` — anomaly score ≥ 50 (high volatility, volume spikes, extreme prices)
- `is_ideal` — liquid + good spread + both levels traded + not manipulated + profitable after commission

## Settings (stored in PostgreSQL)

| Key | Default | Description |
|-----|---------|-------------|
| `test_mode` | `1` | 1=TEST, 0=LIVE |
| `virtual_balance` | `1000` | Starting virtual balance for TEST |
| `current_virtual_balance` | `1000` | Current virtual balance |
| `buy_threshold` | `17` | Min spread % to trigger buy |
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
