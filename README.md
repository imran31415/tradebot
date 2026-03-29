# Tradebot

Automated trading bot for [Polymarket](https://polymarket.com) Bitcoin prediction markets. Identifies near-certain outcomes approaching resolution and captures the final penny spread by buying at $0.99 for shares that resolve at $1.00.

## Table of Contents

- [Strategy Overview](#strategy-overview)
- [Architecture](#architecture)
- [File Structure](#file-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Dry Run Mode](#dry-run-mode)
  - [Live Trading](#live-trading)
  - [Backtesting](#backtesting)
- [Module Reference](#module-reference)
  - [bot.py](#botpy---main-orchestrator)
  - [scanner.py](#scannerpy---market-discovery)
  - [trader.py](#traderpy---order-execution)
  - [positions.py](#positionspy---position-tracking)
  - [backtest.py](#backtestpy---historical-backtesting)
  - [config.py](#configpy---configuration)
- [How the Strategy Works](#how-the-strategy-works)
- [Risk Management](#risk-management)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)

---

## Strategy Overview

Polymarket binary outcome markets resolve to either $1.00 (YES wins) or $0.00 (YES loses). When an outcome is near-certain (95%+ probability) and the market is close to resolution (within 24 hours), there is a narrow but reliable spread between the current price (~$0.95-$0.99) and the $1.00 resolution price.

This bot exploits that spread:

1. **Scan** for Bitcoin markets where one side has 95%+ probability
2. **Filter** to markets resolving within 0.5-24 hours
3. **Buy** the dominant side at $0.99 via a Good-Till-Cancel limit order
4. **Collect** $0.01 per share when the market resolves at $1.00

With $124 per trade, each winning trade earns ~$1.25 profit (125.25 shares x $0.01).

## Architecture

```
                    ┌──────────────┐
                    │   bot.py     │  Main loop (48s cycle)
                    │ Orchestrator │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼───────┐ ┌──▼──────────┐ ┌▼─────────────┐
     │  scanner.py    │ │ trader.py   │ │ positions.py  │
     │ Market         │ │ Order       │ │ Position      │
     │ Discovery      │ │ Execution   │ │ Tracking      │
     └────────┬───────┘ └──┬──────────┘ └┬──────────────┘
              │            │             │
     ┌────────▼───────┐ ┌──▼──────────┐ ┌▼──────────────┐
     │ Gamma API      │ │ CLOB API    │ │ positions.json│
     │ (discovery)    │ │ (trading)   │ │ (persistence) │
     └────────────────┘ └─────────────┘ └───────────────┘
```

**Data Flow:**
1. `scanner.py` queries the Gamma API for active Bitcoin markets
2. `bot.py` filters opportunities based on probability and time-to-resolution
3. `trader.py` checks orderbook liquidity and places limit buy orders via the CLOB API
4. `positions.py` tracks all orders and persists state to `positions.json`
5. On shutdown, open orders are cancelled and state is saved

## File Structure

```
polymarket-bot/
├── bot.py              # Main entry point and orchestration loop
├── scanner.py          # Gamma API client and market filtering
├── trader.py           # CLOB API trading client and order management
├── positions.py        # Position tracking with JSON persistence
├── backtest.py         # Historical strategy backtesting
├── config.py           # All configuration and constants
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

## Prerequisites

- **Python 3.10+**
- **Polygon (MATIC) wallet** with:
  - A funded private key
  - USDC.e balance for trading
  - Token approvals set for the Polymarket CTF Exchange contracts
- **Polymarket account** with API access enabled

## Installation

```bash
# Clone the repository
git clone https://github.com/imran31415/tradebot.git
cd tradebot

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials (see Configuration section)
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `py-clob-client` | >=0.29.0 | Polymarket CLOB API client for order placement |
| `requests` | >=2.31.0 | HTTP client for Gamma API market discovery |
| `python-dotenv` | >=1.0.0 | Environment variable loading from `.env` |
| `web3` | >=6.14.0 | Ethereum/Polygon wallet interaction |

## Configuration

### Environment Variables (`.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PRIVATE_KEY` | Yes (live) | `""` | Polygon wallet private key. Not needed for dry run mode. |
| `SIGNATURE_TYPE` | No | `0` | Order signing scheme (`0` = EIP-712, `1` = EIP-1271). |
| `FUNDER_ADDRESS` | No | `""` | Optional funder/proxy address for order sponsorship. |
| `DRY_RUN` | No | `true` | Set to `false` for live trading. |

### Strategy Parameters (`config.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BUY_PRICE` | `0.99` | Limit buy price per share. The bot places orders at this price. |
| `MIN_PROBABILITY` | `0.95` | Minimum outcome probability (95%) to consider a market. |
| `TRADE_SIZE_USDC` | `124.0` | Dollar amount per trade. At $0.99, this buys ~125.25 shares. |
| `MAX_HOURS_TO_RESOLUTION` | `24` | Maximum hours until market end date. |
| `MIN_HOURS_TO_RESOLUTION` | `0.5` | Minimum hours until market end date (avoids last-second risk). |
| `SCAN_INTERVAL_SECONDS` | `48` | Seconds between scan cycles. |
| `MAX_OPEN_ORDERS` | `50` | Maximum number of concurrent open orders. |
| `MAX_TOTAL_EXPOSURE_USDC` | `10000.0` | Maximum total capital at risk across all positions. |

### Network Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `CHAIN_ID` | `137` | Polygon mainnet chain ID. |
| `GAMMA_API_URL` | `https://gamma-api.polymarket.com` | Market discovery endpoint. |
| `CLOB_API_URL` | `https://clob.polymarket.com` | Order placement endpoint. |
| `CRYPTO_TAG_ID` | `21` | Polymarket tag ID for cryptocurrency markets. |
| `NEG_RISK_CTF_EXCHANGE` | `0xC5d5...` | Neg-risk CTF exchange contract address. |
| `CTF_EXCHANGE` | `0x2791...` | Standard CTF exchange contract address. |

## Usage

### Dry Run Mode

Dry run mode simulates all trading without a wallet. No orders are placed, no funds are at risk. This is the default.

```bash
# Start in dry run mode (default)
python3 bot.py

# Explicitly enable dry run
DRY_RUN=true python3 bot.py
```

Dry run output is prefixed with `[DRY RUN]` for all simulated actions.

### Live Trading

**Warning:** Live trading uses real funds. Ensure you understand the risks before proceeding.

```bash
# Configure credentials
echo 'PRIVATE_KEY=your_polygon_private_key_here' > .env
echo 'DRY_RUN=false' >> .env

# Start live trading
python3 bot.py
```

The bot will:
1. Validate your wallet connection and display your balance
2. Begin scanning for Bitcoin markets every 48 seconds
3. Place GTC limit buy orders at $0.99 for qualifying opportunities
4. Monitor and update order statuses each cycle
5. Save positions to `positions.json` after each cycle

**Graceful shutdown:** Press `Ctrl+C` or send `SIGTERM`. The bot will:
- Cancel all open orders (live mode only)
- Save position state to disk
- Exit cleanly

### Backtesting

The backtester validates the sniper strategy against historical resolved Bitcoin markets from the Gamma API.

```bash
# Run with default parameters (from config.py)
python3 backtest.py

# Show individual trade details
python3 backtest.py --verbose

# Force fresh API fetch (ignore cached data)
python3 backtest.py --no-cache

# Filter to high-volume markets only
python3 backtest.py --min-volume 1000

# Custom strategy parameters
python3 backtest.py --buy-price 0.98 --min-prob 0.90 --trade-size 50

# Combine options
python3 backtest.py --min-volume 5000 --verbose --trade-size 200
```

#### Backtest CLI Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--buy-price` | float | `0.99` | Simulated limit buy price |
| `--min-prob` | float | `0.95` | Minimum probability threshold |
| `--trade-size` | float | `124.0` | Simulated trade size in USDC |
| `--min-volume` | float | `0` | Minimum market volume in USD |
| `--no-cache` | flag | off | Force fresh API fetch |
| `--verbose` | flag | off | Print individual trade details |

#### Sample Backtest Output

```
============================================================
  BACKTEST REPORT — BTC Sniper Strategy
============================================================

  Parameters:
    Buy Price:      $0.99
    Min Probability: 95%
    Trade Size:     $124.00
    Min Volume:     $0

  Results (6039 trades):
    Wins:           6039
    Losses:         0
    Win Rate:       100.0%
    Net P&L:        $+7563.85
    ROI:            +1.01%
    Capital Used:   $748,836.00
    Max Drawdown:   $0.00
    Profit Factor:  inf
    Avg Win:        $1.25
    Avg Loss:       $0.00
    Best Streak:    6039 wins
    Worst Streak:   0 losses

============================================================
```

#### Backtest Caching

The first run fetches all resolved BTC markets from the Gamma API (paginates through ~20,000 API pages) and caches results to `backtest_cache.json`. Subsequent runs load from cache instantly. Use `--no-cache` to refresh.

The cache file is excluded from version control via `.gitignore`.

---

## Module Reference

### `bot.py` - Main Orchestrator

The entry point that ties all components together in a continuous scan-trade loop.

**Key Functions:**

| Function | Description |
|----------|-------------|
| `main()` | Initializes all components, enters the main loop, handles shutdown. |
| `run_scan_cycle(gamma, trader, tracker)` | Executes one full scan-filter-trade-monitor-save cycle. |
| `update_existing_orders(trader, tracker)` | Checks open orders against the CLOB API and marks filled ones. |
| `shutdown_handler(signum, frame)` | Signal handler for `SIGINT`/`SIGTERM`. Cancels orders and saves state. |
| `print_config()` | Logs the active configuration at startup. |

**Main Loop Flow (every 48 seconds):**

```
1. Scan      → GammaClient.find_bitcoin_markets()
2. Filter    → filter_opportunities(markets)
3. Limits    → Check MAX_OPEN_ORDERS and MAX_TOTAL_EXPOSURE_USDC
4. Validate  → Skip duplicate tokens, check orderbook liquidity
5. Trade     → TradingClient.place_limit_buy()
6. Monitor   → Update status of existing orders
7. Persist   → PositionTracker.save()
8. Log       → Print cycle summary
```

---

### `scanner.py` - Market Discovery

Interfaces with the Polymarket Gamma API to find and filter Bitcoin markets.

**Classes:**

#### `GammaClient`

| Method | Description |
|--------|-------------|
| `__init__()` | Creates an HTTP session with JSON headers for the Gamma API. |
| `_get(endpoint, params)` | Internal GET request with 15s timeout and error handling. |
| `find_bitcoin_markets()` | Paginates through all active crypto markets (tag_id=21), filters by BTC/Bitcoin keywords in question or slug. Returns a list of market dicts. Rate-limited at 0.3s between pages. |

**Functions:**

#### `filter_opportunities(markets)`

Filters raw markets to actionable trading opportunities:

1. Validates market has an active order book
2. Parses `outcomePrices` JSON → `[yes_price, no_price]`
3. Identifies dominant side (YES or NO with price >= `MIN_PROBABILITY`)
4. Validates end date within resolution window (0.5-24 hours)
5. Extracts the correct `clobTokenIds` entry for the dominant side
6. Scores opportunities: `score = probability * (1.0 / hours_to_resolution)`
7. Sorts by score descending (highest probability + soonest resolution first)

Returns list of opportunity dicts:
```python
{
    "question": "Will BTC be above $100k on March 30?",
    "token_id": "0x1234...",
    "side": "YES",
    "current_price": 0.97,
    "end_date": "2026-03-30T12:00:00+00:00",
    "hours_to_resolution": 3.5,
    "condition_id": "0xabcd...",
    "neg_risk": False,
    "score": 0.277,
    "market_slug": "will-btc-be-above-100k-march-30",
}
```

#### `get_tick_size(condition_id)`

Queries the CLOB API for a market's minimum tick size (price increment). Falls back to `0.01` on failure.

---

### `trader.py` - Order Execution

Manages order placement, cancellation, and orderbook queries via the Polymarket CLOB API.

**Classes:**

#### `TradingClient`

The live trading client that wraps `py-clob-client`.

| Method | Description |
|--------|-------------|
| `__init__()` | Initializes the CLOB client with wallet credentials, derives API keys. |
| `place_limit_buy(token_id, price, size_usdc, neg_risk, tick_size)` | Places a GTC limit buy order. Rounds price to tick size, calculates share size from USDC amount. Rate-limited to 1 order per 0.5s. Returns order details dict or `None` on failure. |
| `get_open_orders()` | Lists all currently open orders. |
| `cancel_order(order_id)` | Cancels a single order by ID. |
| `cancel_all()` | Emergency cancellation of all open orders. |
| `get_balance()` | Checks USDC.e balance and allowance on Polygon. |
| `check_orderbook(token_id, price)` | Queries the orderbook and checks for asks at or below the target price. Returns `{has_liquidity, total_size, asks}`. |

**Price Rounding:**
```python
# Rounds to the market's tick size (e.g., 0.01, 0.001)
decimals = max(0, -int(math.floor(math.log10(tick_size))))
price = round(round(price / tick_size) * tick_size, decimals)
```

**Share Size Calculation:**
```python
# $124 at $0.99 = 125.25 shares
size = round(size_usdc / price, 2)
```

#### `DryRunClient`

Stub client used when no private key is configured. All methods are no-ops that log `[DRY RUN]` messages. `place_limit_buy()` returns a synthetic order with a UUID-based `order_id`.

---

### `positions.py` - Position Tracking

In-memory position tracker with JSON file persistence.

#### `PositionTracker`

| Method | Description |
|--------|-------------|
| `add_order(order_id, details)` | Records a new order with status `"open"` and UTC timestamp. |
| `update_order(order_id, status)` | Updates order status. Valid statuses: `open`, `filled`, `cancelled`, `resolved`. Sets `filled_at` timestamp when transitioning to `"filled"`. |
| `get_total_exposure()` | Sum of `size_usdc` for all `open` + `filled` orders. |
| `get_open_count()` | Count of orders with status `"open"`. |
| `get_filled_positions()` | List of orders with status `"filled"` (awaiting resolution). |
| `get_stats()` | Returns summary dict: total orders, counts by status, fill rate, total exposure, expected profit. |
| `save(filepath)` | Writes all orders to `positions.json` with indented formatting. |
| `load(filepath)` | Loads orders from `positions.json`. Starts fresh if file doesn't exist. |

**Order Lifecycle:**
```
open → filled → resolved
  └──→ cancelled
```

**Expected Profit Calculation:**
```python
# For each filled/resolved order:
profit = shares * (1.0 - buy_price)
# e.g., 125.25 shares * $0.01 = $1.25 per trade
```

---

### `backtest.py` - Historical Backtesting

Validates the sniper strategy against all historically resolved Bitcoin markets.

**Functions:**

| Function | Description |
|----------|-------------|
| `fetch_resolved_btc_markets(use_cache)` | Paginates the Gamma API for closed crypto markets (tag_id=21, closed=true). Filters for BTC keywords and `umaResolutionStatus == "resolved"`. Caches results to `backtest_cache.json`. |
| `determine_resolution(market)` | Parses final `outcomePrices` to determine the winner. Returns `{winning_side: "YES"\|"NO"\|"DRAW", yes_price, no_price}`. A side wins if its final price is > 0.9. |
| `simulate_strategy(markets, buy_price, min_prob, trade_size, min_volume)` | Simulates the bot's strategy on each resolved market. Determines what side the bot would have bought (the dominant side), checks if it met the probability threshold, calculates P&L based on whether that side won. |
| `calculate_stats(trades, initial_balance)` | Computes: win rate, net P&L, ROI, max drawdown, profit factor, average win/loss, best/worst streaks, total capital deployed. |
| `print_report(stats, trades, params)` | Formats and prints the full backtest report. With `--verbose`, lists every individual trade. |
| `parse_args()` | argparse CLI interface with defaults from `config.py`. |
| `main()` | Orchestrates fetch -> simulate -> calculate -> report. |

**P&L Calculation:**
```python
shares = trade_size / buy_price   # e.g., 124 / 0.99 = 125.25

if won:
    pnl = shares * (1.0 - buy_price)  # +$1.25
else:
    pnl = -trade_size                  # -$124.00
```

---

### `config.py` - Configuration

Loads environment variables via `python-dotenv` and defines all strategy constants. See the [Configuration](#configuration) section for the full parameter table.

---

## How the Strategy Works

### The Opportunity

Polymarket binary outcome shares resolve to exactly $1.00 (winner) or $0.00 (loser). When a Bitcoin price market is hours from resolution and the outcome is already near-certain (e.g., BTC is well above the threshold with 3 hours left), the winning side trades at $0.95-$0.99 while the market waits for official UMA oracle resolution.

### The Edge

By buying at $0.99, the bot captures $0.01 per share on resolution. This works because:

- **High certainty:** Only targeting markets where one side is already 95%+ likely
- **Near resolution:** Only markets resolving within 24 hours (less time for reversal)
- **Binary outcome:** Shares settle at exactly $1.00 or $0.00, no partial fills
- **Low spread:** The $0.01 spread per share is small enough that most traders ignore it

### The Math

| Metric | Value |
|--------|-------|
| Buy price | $0.99 per share |
| Trade size | $124.00 USDC |
| Shares per trade | 125.25 |
| Profit per win | $1.25 |
| Loss per loss | $124.00 |
| Break-even win rate | 99.0% |

The strategy requires an extremely high win rate to be profitable. A single loss wipes out ~99 winning trades. The bot achieves this by only entering positions where the outcome is near-certain.

### Scoring

Opportunities are ranked by a composite score:

```
score = probability * (1.0 / hours_to_resolution)
```

Higher probability and sooner resolution both increase the score. The bot trades the highest-scored opportunities first.

## Risk Management

The bot implements several risk controls:

| Control | Mechanism |
|---------|-----------|
| **Position limits** | Maximum 50 concurrent open orders |
| **Exposure cap** | Maximum $10,000 total capital at risk |
| **Time filter** | Minimum 30 minutes to resolution (avoids last-second volatility) |
| **Probability floor** | Only trades when one side is 95%+ |
| **Duplicate prevention** | Will not open a second position in the same token |
| **Liquidity check** | Verifies asks exist at/below buy price before trading (live mode) |
| **Rate limiting** | 0.5s minimum between order submissions |
| **Graceful shutdown** | Cancels all open orders on SIGINT/SIGTERM |
| **State persistence** | Saves positions to disk after every cycle |

### Known Risks

- **Oracle failure:** UMA oracle could resolve incorrectly (rare but catastrophic)
- **Market manipulation:** Sudden price movements could move the dominant side below 95%
- **Liquidity risk:** Orders may not fill if the orderbook is thin at $0.99
- **Smart contract risk:** Polymarket exchange contracts could have bugs
- **Network risk:** Polygon network congestion could delay order placement
- **API risk:** Gamma or CLOB API downtime could prevent scanning/trading

## API Reference

### Gamma API (`gamma-api.polymarket.com`)

Used for market discovery. Public, no authentication required.

**`GET /markets`**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tag_id` | int | Market tag filter (21 = crypto) |
| `active` | string | `"true"` for open markets |
| `closed` | string | `"true"` for resolved markets |
| `limit` | int | Page size (max 100) |
| `offset` | int | Pagination offset |

Returns an array of market objects with fields including `question`, `slug`, `outcomePrices`, `endDate`, `clobTokenIds`, `conditionId`, `negRisk`, `volume`, `umaResolutionStatus`, and more.

### CLOB API (`clob.polymarket.com`)

Used for order placement and management. Requires wallet-signed API credentials.

**`GET /markets/{conditionId}`** - Market details including tick size

**`POST /order`** - Place a signed order (handled by `py-clob-client`)

**`GET /orders`** - List open orders

**`DELETE /order/{orderId}`** - Cancel an order

## Troubleshooting

### "PRIVATE_KEY not set and DRY_RUN is false"

Set your private key in `.env` or enable dry run mode:
```bash
echo 'DRY_RUN=true' >> .env
```

### "Gamma API request failed"

The Gamma API may be rate-limiting or temporarily unavailable. The bot will retry on the next scan cycle (48 seconds). If persistent, check your network connectivity.

### "No opportunities found this cycle"

Normal when no Bitcoin markets meet the filtering criteria (95%+ probability, 0.5-24h to resolution). The bot will keep scanning.

### "No liquidity at 0.99"

The orderbook has no asks at or below $0.99. The bot skips this market and moves on.

### "Failed to initialize trading client"

Check that your `PRIVATE_KEY` is valid, your wallet has USDC.e on Polygon, and that the CLOB API is accessible.

### Backtest cache is stale

Delete the cache and re-fetch:
```bash
rm backtest_cache.json
python3 backtest.py --no-cache
```

## Disclaimer

This software is provided for educational and research purposes only. Trading on prediction markets involves significant financial risk.

- **No guarantees:** Past backtest performance does not guarantee future results
- **Real money at risk:** Live trading mode places real orders with real funds
- **Software bugs:** This software may contain bugs that result in financial losses
- **Regulatory risk:** Prediction market trading may be restricted in your jurisdiction
- **Not financial advice:** This project and its documentation do not constitute financial, legal, or investment advice

Use at your own risk. The authors are not responsible for any financial losses incurred through the use of this software.
