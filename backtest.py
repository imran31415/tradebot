#!/usr/bin/env python3
"""Backtest the sniper strategy against historical resolved BTC markets."""

import argparse
import json
import logging
import os
import sys
import time

import requests

import config

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_cache.json")
BTC_KEYWORDS = ("btc", "bitcoin")


def fetch_resolved_btc_markets(use_cache=True):
    """Fetch resolved Bitcoin markets from the Gamma API.

    Paginates through all closed crypto markets, filters for BTC keywords
    and resolved status. Results are cached to avoid repeated API calls.
    """
    if use_cache and os.path.exists(CACHE_FILE):
        logger.info("Loading markets from cache: %s", CACHE_FILE)
        with open(CACHE_FILE, "r") as f:
            markets = json.load(f)
        logger.info("Loaded %d cached markets", len(markets))
        return markets

    logger.info("Fetching resolved BTC markets from Gamma API...")
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    markets = []
    offset = 0
    limit = 100
    max_offset = 20000  # Cap pagination — covers 20k API pages

    while offset <= max_offset:
        params = {
            "tag_id": config.CRYPTO_TAG_ID,
            "closed": "true",
            "limit": limit,
            "offset": offset,
        }
        try:
            resp = session.get(f"{config.GAMMA_API_URL}/markets", params=params, timeout=15)
            resp.raise_for_status()
            batch = resp.json()
        except requests.RequestException as e:
            logger.error("Gamma API request failed at offset %d: %s", offset, e)
            break

        if not batch:
            break

        for market in batch:
            q = market.get("question", "").lower()
            slug = market.get("slug", "").lower()
            if not any(kw in q or kw in slug for kw in BTC_KEYWORDS):
                continue
            resolution = market.get("umaResolutionStatus", "")
            if resolution != "resolved":
                continue
            markets.append(market)

        logger.info("  fetched offset %d, batch=%d, BTC resolved so far=%d", offset, len(batch), len(markets))

        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.2)

    logger.info("Total resolved BTC markets: %d", len(markets))

    # Cache results
    with open(CACHE_FILE, "w") as f:
        json.dump(markets, f)
    logger.info("Cached to %s", CACHE_FILE)

    return markets


def determine_resolution(market):
    """Parse a resolved market's final outcomePrices to determine the winner.

    Returns dict with winning_side ("YES", "NO", or "DRAW").
    """
    prices_raw = market.get("outcomePrices", "")
    if not prices_raw:
        return None

    try:
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        if len(prices) < 2:
            return None
        yes_price = float(prices[0])
        no_price = float(prices[1])
    except (ValueError, json.JSONDecodeError):
        return None

    if yes_price > 0.9:
        return {"winning_side": "YES", "yes_price": yes_price, "no_price": no_price}
    elif no_price > 0.9:
        return {"winning_side": "NO", "yes_price": yes_price, "no_price": no_price}
    else:
        return {"winning_side": "DRAW", "yes_price": yes_price, "no_price": no_price}


def simulate_strategy(markets, buy_price, min_prob, trade_size, min_volume):
    """Simulate the sniper strategy on resolved markets.

    For each market: determine the dominant side (highest outcome price before
    resolution), check if it met the min_prob threshold, then see if it won.
    """
    trades = []

    for market in markets:
        resolution = determine_resolution(market)
        if resolution is None or resolution["winning_side"] == "DRAW":
            continue

        # Volume filter
        volume = float(market.get("volume", 0) or 0)
        if volume < min_volume:
            continue

        yes_price = resolution["yes_price"]
        no_price = resolution["no_price"]
        winning_side = resolution["winning_side"]

        # Determine what the bot would have done: buy the dominant side
        if yes_price >= no_price:
            bot_side = "YES"
            bot_prob = yes_price
        else:
            bot_side = "NO"
            bot_prob = no_price

        # Only trade if probability met threshold
        if bot_prob < min_prob:
            continue

        # Calculate shares bought
        shares = trade_size / buy_price

        # Did the bot's side win?
        won = bot_side == winning_side
        if won:
            pnl = shares * (1.0 - buy_price)  # shares resolve at $1
        else:
            pnl = -trade_size  # total loss

        trades.append({
            "question": market.get("question", ""),
            "slug": market.get("slug", ""),
            "volume": volume,
            "bot_side": bot_side,
            "bot_prob": bot_prob,
            "winning_side": winning_side,
            "won": won,
            "pnl": round(pnl, 4),
            "trade_size": trade_size,
            "buy_price": buy_price,
        })

    return trades


def calculate_stats(trades, initial_balance=10000.0):
    """Calculate performance statistics from a list of trades."""
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "roi": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": 0.0,
            "best_streak": 0,
            "worst_streak": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "total_capital_deployed": 0.0,
        }

    wins = [t for t in trades if t["won"]]
    losses = [t for t in trades if not t["won"]]

    total_wins_pnl = sum(t["pnl"] for t in wins)
    total_losses_pnl = abs(sum(t["pnl"] for t in losses))
    net_pnl = sum(t["pnl"] for t in trades)
    total_capital = sum(t["trade_size"] for t in trades)

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t["pnl"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Streaks
    best_streak = 0
    worst_streak = 0
    current_streak = 0
    for t in trades:
        if t["won"]:
            current_streak = current_streak + 1 if current_streak > 0 else 1
        else:
            current_streak = current_streak - 1 if current_streak < 0 else -1
        best_streak = max(best_streak, current_streak)
        worst_streak = min(worst_streak, current_streak)

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "net_pnl": round(net_pnl, 2),
        "roi": round(net_pnl / total_capital * 100, 2) if total_capital else 0.0,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(total_wins_pnl / total_losses_pnl, 2) if total_losses_pnl else float("inf"),
        "best_streak": best_streak,
        "worst_streak": abs(worst_streak),
        "avg_win": round(total_wins_pnl / len(wins), 2) if wins else 0.0,
        "avg_loss": round(total_losses_pnl / len(losses), 2) if losses else 0.0,
        "total_capital_deployed": round(total_capital, 2),
    }


def print_report(stats, trades, params):
    """Print a formatted backtest report to the console."""
    print("\n" + "=" * 60)
    print("  BACKTEST REPORT — BTC Sniper Strategy")
    print("=" * 60)

    print("\n  Parameters:")
    print(f"    Buy Price:      ${params['buy_price']:.2f}")
    print(f"    Min Probability: {params['min_prob'] * 100:.0f}%")
    print(f"    Trade Size:     ${params['trade_size']:.2f}")
    print(f"    Min Volume:     ${params['min_volume']:.0f}")

    print(f"\n  Results ({stats['total_trades']} trades):")
    print(f"    Wins:           {stats['wins']}")
    print(f"    Losses:         {stats['losses']}")
    print(f"    Win Rate:       {stats['win_rate']:.1f}%")
    print(f"    Net P&L:        ${stats['net_pnl']:+.2f}")
    print(f"    ROI:            {stats['roi']:+.2f}%")
    print(f"    Capital Used:   ${stats['total_capital_deployed']:,.2f}")
    print(f"    Max Drawdown:   ${stats['max_drawdown']:.2f}")
    print(f"    Profit Factor:  {stats['profit_factor']:.2f}")
    print(f"    Avg Win:        ${stats['avg_win']:.2f}")
    print(f"    Avg Loss:       ${stats['avg_loss']:.2f}")
    print(f"    Best Streak:    {stats['best_streak']} wins")
    print(f"    Worst Streak:   {stats['worst_streak']} losses")

    if params.get("verbose") and trades:
        print("\n  Individual Trades:")
        print("  " + "-" * 56)
        for i, t in enumerate(trades, 1):
            result = "WIN " if t["won"] else "LOSS"
            print(f"    {i:3d}. [{result}] {t['pnl']:+8.2f}  {t['bot_side']:3s} @ {t['bot_prob']:.2f}  "
                  f"vol=${t['volume']:,.0f}")
            print(f"         {t['question'][:70]}")

    print("\n" + "=" * 60)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Backtest the BTC sniper strategy on resolved Polymarket markets.")
    parser.add_argument("--buy-price", type=float, default=config.BUY_PRICE,
                        help=f"Limit buy price (default: {config.BUY_PRICE})")
    parser.add_argument("--min-prob", type=float, default=config.MIN_PROBABILITY,
                        help=f"Minimum probability threshold (default: {config.MIN_PROBABILITY})")
    parser.add_argument("--trade-size", type=float, default=config.TRADE_SIZE_USDC,
                        help=f"Trade size in USDC (default: {config.TRADE_SIZE_USDC})")
    parser.add_argument("--min-volume", type=float, default=0.0,
                        help="Minimum market volume in USD (default: 0)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Force fresh API fetch (ignore cache)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show individual trades")
    return parser.parse_args()


def main():
    """Run the backtest."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args()

    # Fetch resolved markets
    markets = fetch_resolved_btc_markets(use_cache=not args.no_cache)
    if not markets:
        print("No resolved BTC markets found.")
        sys.exit(1)

    # Simulate
    trades = simulate_strategy(
        markets,
        buy_price=args.buy_price,
        min_prob=args.min_prob,
        trade_size=args.trade_size,
        min_volume=args.min_volume,
    )

    # Stats
    stats = calculate_stats(trades)

    # Report
    params = {
        "buy_price": args.buy_price,
        "min_prob": args.min_prob,
        "trade_size": args.trade_size,
        "min_volume": args.min_volume,
        "verbose": args.verbose,
    }
    print_report(stats, trades, params)


if __name__ == "__main__":
    main()
