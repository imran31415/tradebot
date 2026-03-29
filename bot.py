#!/usr/bin/env python3
"""Polymarket Bitcoin Sniper Bot — Main Orchestrator.

Scans for near-certain Bitcoin market outcomes on Polymarket,
places limit buy orders at 99c, and tracks positions until resolution.
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

import config
from positions import PositionTracker
from scanner import GammaClient, filter_opportunities, get_tick_size
from trader import DryRunClient, TradingClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")

# Globals for signal handler access
trader = None
tracker = None
running = True


def shutdown_handler(signum, frame):
    """Graceful shutdown: cancel open orders and save state."""
    global running
    logger.info("Shutdown signal received (sig=%s), cleaning up...", signum)
    running = False

    if trader and not config.DRY_RUN:
        logger.info("Cancelling all open orders...")
        trader.cancel_all()

    if tracker:
        tracker.save()
        logger.info("Positions saved.")

    logger.info("Shutdown complete.")
    sys.exit(0)


def print_config():
    """Log current configuration."""
    logger.info("=" * 60)
    logger.info("Polymarket Bitcoin Sniper Bot")
    logger.info("=" * 60)
    logger.info("Mode:            %s", "DRY RUN" if config.DRY_RUN else "LIVE TRADING")
    logger.info("Buy price:       $%.2f", config.BUY_PRICE)
    logger.info("Min probability: %.0f%%", config.MIN_PROBABILITY * 100)
    logger.info("Trade size:      $%.0f", config.TRADE_SIZE_USDC)
    logger.info("Resolution window: %.1f - %d hours", config.MIN_HOURS_TO_RESOLUTION, config.MAX_HOURS_TO_RESOLUTION)
    logger.info("Scan interval:   %ds", config.SCAN_INTERVAL_SECONDS)
    logger.info("Max open orders: %d", config.MAX_OPEN_ORDERS)
    logger.info("Max exposure:    $%.0f", config.MAX_TOTAL_EXPOSURE_USDC)
    logger.info("=" * 60)


def update_existing_orders(trader_client, tracker_obj):
    """Check and update status of existing open orders."""
    open_orders = [
        o for o in tracker_obj.orders.values()
        if o["status"] == "open" and not o.get("dry_run")
    ]
    if not open_orders:
        return

    try:
        live_orders = trader_client.get_open_orders()
        live_ids = set()
        for lo in live_orders:
            oid = lo.get("id", lo.get("orderID", ""))
            if oid:
                live_ids.add(oid)

        for order in open_orders:
            oid = order["order_id"]
            if oid not in live_ids:
                # Order no longer open — assume filled or cancelled
                tracker_obj.update_order(oid, "filled")
                logger.info("Order %s appears filled/completed", oid)
    except Exception as e:
        logger.warning("Could not update order statuses: %s", e)


def run_scan_cycle(gamma, trader_client, tracker_obj):
    """Execute one scan-and-trade cycle."""
    # 1. Scan
    logger.info("--- Scan cycle starting ---")
    markets = gamma.find_bitcoin_markets()
    opportunities = filter_opportunities(markets)

    if not opportunities:
        logger.info("No opportunities found this cycle")
        return

    # 2. Check limits
    exposure = tracker_obj.get_total_exposure()
    open_count = tracker_obj.get_open_count()

    if open_count >= config.MAX_OPEN_ORDERS:
        logger.info("At max open orders (%d), skipping trades", open_count)
        return

    if exposure >= config.MAX_TOTAL_EXPOSURE_USDC:
        logger.info("At max exposure ($%.0f), skipping trades", exposure)
        return

    remaining_capacity = config.MAX_OPEN_ORDERS - open_count
    remaining_exposure = config.MAX_TOTAL_EXPOSURE_USDC - exposure

    # 3-5. Validate, Trade, Track
    trades_placed = 0
    for opp in opportunities:
        if trades_placed >= remaining_capacity:
            break
        if remaining_exposure < config.TRADE_SIZE_USDC:
            logger.info("Remaining exposure budget too low ($%.0f)", remaining_exposure)
            break

        token_id = opp["token_id"]

        # Already have an order for this token?
        existing = any(
            o["token_id"] == token_id and o["status"] in ("open", "filled")
            for o in tracker_obj.orders.values()
        )
        if existing:
            logger.debug("Already have position in %s, skipping", opp["question"][:50])
            continue

        # Check orderbook liquidity (skip in dry run to avoid auth issues)
        if not config.DRY_RUN:
            book = trader_client.check_orderbook(token_id, config.BUY_PRICE)
            if not book["has_liquidity"]:
                logger.info("No liquidity at %.2f for %s", config.BUY_PRICE, opp["question"][:50])
                continue

        # Get tick size
        tick_size = get_tick_size(opp.get("condition_id", ""))

        # Place order
        logger.info(
            "Trading: %s | %s @ %.2f | resolves in %.1fh | score=%.3f",
            opp["question"][:50],
            opp["side"],
            opp["current_price"],
            opp["hours_to_resolution"],
            opp["score"],
        )

        result = trader_client.place_limit_buy(
            token_id=token_id,
            price=config.BUY_PRICE,
            size_usdc=config.TRADE_SIZE_USDC,
            neg_risk=opp.get("neg_risk", False),
            tick_size=tick_size,
        )

        if result:
            result["question"] = opp["question"]
            result["side"] = opp["side"]
            tracker_obj.add_order(result["order_id"], result)
            trades_placed += 1
            remaining_exposure -= config.TRADE_SIZE_USDC

    # 6. Monitor existing orders
    if not config.DRY_RUN:
        update_existing_orders(trader_client, tracker_obj)

    # 7. Log summary
    stats = tracker_obj.get_stats()
    logger.info(
        "Cycle done: %d new trades | Total: %d orders, %d open, %d filled | "
        "Exposure: $%.0f | Expected profit: $%.2f",
        trades_placed,
        stats["total_orders"],
        stats["open"],
        stats["filled"],
        stats["total_exposure_usdc"],
        stats["expected_profit_usdc"],
    )

    # 8. Persist
    tracker_obj.save()


def main():
    global trader, tracker

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print_config()

    if not config.PRIVATE_KEY and not config.DRY_RUN:
        logger.error("PRIVATE_KEY not set and DRY_RUN is false — aborting")
        sys.exit(1)

    # Initialize components
    gamma = GammaClient()
    tracker = PositionTracker()
    tracker.load()

    if config.PRIVATE_KEY and not config.DRY_RUN:
        try:
            trader = TradingClient()
            bal = trader.get_balance()
            if bal:
                logger.info("Wallet balance: %s", bal)
        except Exception as e:
            logger.error("Failed to initialize trading client: %s", e)
            sys.exit(1)
    else:
        if not config.PRIVATE_KEY:
            logger.info("No private key — running in scan-only mode")
        trader = DryRunClient()

    # Main loop
    logger.info("Starting main loop (interval=%ds)", config.SCAN_INTERVAL_SECONDS)
    while running:
        try:
            run_scan_cycle(gamma, trader, tracker)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Cycle error: %s", e, exc_info=True)

        if running:
            logger.info("Sleeping %ds until next scan...", config.SCAN_INTERVAL_SECONDS)
            time.sleep(config.SCAN_INTERVAL_SECONDS)

    # Final save
    if tracker:
        tracker.save()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
