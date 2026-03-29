import logging
import math
import time
import uuid

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

import config

logger = logging.getLogger(__name__)


class TradingClient:
    """Wraps py-clob-client for order placement and management."""

    def __init__(self):
        self.client = ClobClient(
            config.CLOB_API_URL,
            key=config.PRIVATE_KEY,
            chain_id=config.CHAIN_ID,
            signature_type=config.SIGNATURE_TYPE,
            funder=config.FUNDER_ADDRESS or None,
        )
        # Derive and set API credentials
        self.client.set_api_creds(self.client.create_or_derive_api_creds())
        self._last_order_time = 0.0
        logger.info("TradingClient initialized")

    def _rate_limit(self):
        """Enforce minimum 0.5s between order submissions."""
        elapsed = time.time() - self._last_order_time
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        self._last_order_time = time.time()

    def place_limit_buy(self, token_id, price, size_usdc, neg_risk=False, tick_size=0.01):
        """Place a GTC limit buy order.

        Args:
            token_id: The CLOB token ID for the outcome.
            price: Limit price (e.g. 0.99).
            size_usdc: Dollar amount to spend.
            neg_risk: Whether the market uses neg-risk exchange.
            tick_size: Market tick size for price rounding.

        Returns:
            dict with order_id and details, or None on failure.
        """
        self._rate_limit()

        # Round price to tick size
        decimals = max(0, -int(math.floor(math.log10(tick_size))))
        price = round(round(price / tick_size) * tick_size, decimals)

        # Calculate shares from dollar amount
        size = round(size_usdc / price, 2)

        try:
            order_args = OrderArgs(
                price=price,
                size=size,
                side="BUY",
                token_id=token_id,
            )

            if config.DRY_RUN:
                logger.info(
                    "[DRY RUN] Would place BUY: token=%s price=%.4f size=%.2f ($%.2f)",
                    token_id[:16] + "...",
                    price,
                    size,
                    size_usdc,
                )
                return {
                    "order_id": f"dry-run-{uuid.uuid4().hex[:12]}",
                    "token_id": token_id,
                    "price": price,
                    "size": size,
                    "size_usdc": size_usdc,
                    "dry_run": True,
                }

            signed_order = self.client.create_and_post_order(
                order_args,
                OrderType.GTC,
                neg_risk=neg_risk,
            )

            order_id = signed_order.get("orderID", signed_order.get("id", "unknown"))
            logger.info(
                "Order placed: id=%s token=%s price=%.4f size=%.2f ($%.2f)",
                order_id,
                token_id[:16] + "...",
                price,
                size,
                size_usdc,
            )
            return {
                "order_id": order_id,
                "token_id": token_id,
                "price": price,
                "size": size,
                "size_usdc": size_usdc,
                "dry_run": False,
                "response": signed_order,
            }

        except Exception as e:
            logger.error("Failed to place order for token %s: %s", token_id[:16] + "...", e)
            return None

    def get_open_orders(self):
        """List all open orders."""
        try:
            return self.client.get_orders()
        except Exception as e:
            logger.error("Failed to get open orders: %s", e)
            return []

    def cancel_order(self, order_id):
        """Cancel a single order by ID."""
        try:
            if config.DRY_RUN:
                logger.info("[DRY RUN] Would cancel order %s", order_id)
                return True
            result = self.client.cancel(order_id)
            logger.info("Cancelled order %s: %s", order_id, result)
            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return False

    def cancel_all(self):
        """Emergency: cancel all open orders."""
        try:
            if config.DRY_RUN:
                logger.info("[DRY RUN] Would cancel all open orders")
                return True
            result = self.client.cancel_all()
            logger.info("Cancelled all orders: %s", result)
            return True
        except Exception as e:
            logger.error("Failed to cancel all orders: %s", e)
            return False

    def get_balance(self):
        """Check USDC.e balance and allowance."""
        try:
            bal = self.client.get_balance_allowance()
            logger.info("Balance: %s", bal)
            return bal
        except Exception as e:
            logger.error("Failed to get balance: %s", e)
            return None

    def check_orderbook(self, token_id, price=None):
        """Check orderbook for a token to verify liquidity."""
        price = price or config.BUY_PRICE
        try:
            book = self.client.get_order_book(token_id)
            asks = book.get("asks", [])

            # Check if there are asks at or below our target price
            relevant_asks = [a for a in asks if float(a.get("price", 1)) <= price + 0.005]
            total_size = sum(float(a.get("size", 0)) for a in relevant_asks)

            logger.debug(
                "Orderbook for %s: %d asks at/below %.2f, total size %.2f",
                token_id[:16] + "...",
                len(relevant_asks),
                price,
                total_size,
            )
            return {"has_liquidity": len(relevant_asks) > 0, "total_size": total_size, "asks": relevant_asks}
        except Exception as e:
            logger.warning("Failed to check orderbook for %s: %s", token_id[:16] + "...", e)
            return {"has_liquidity": False, "total_size": 0, "asks": []}


class DryRunClient:
    """Stub trading client used when no private key is available."""

    def __init__(self):
        self._last_order_time = 0.0
        logger.info("DryRunClient initialized (no real trading)")

    def place_limit_buy(self, token_id, price, size_usdc, neg_risk=False, tick_size=0.01):
        decimals = max(0, -int(math.floor(math.log10(tick_size))))
        price = round(round(price / tick_size) * tick_size, decimals)
        size = round(size_usdc / price, 2)
        logger.info(
            "[DRY RUN] Would place BUY: token=%s price=%.4f size=%.2f ($%.2f)",
            token_id[:16] + "...", price, size, size_usdc,
        )
        return {
            "order_id": f"dry-run-{uuid.uuid4().hex[:12]}",
            "token_id": token_id,
            "price": price,
            "size": size,
            "size_usdc": size_usdc,
            "dry_run": True,
        }

    def get_open_orders(self):
        return []

    def cancel_order(self, order_id):
        logger.info("[DRY RUN] Would cancel order %s", order_id)
        return True

    def cancel_all(self):
        logger.info("[DRY RUN] Would cancel all open orders")
        return True

    def get_balance(self):
        return None

    def check_orderbook(self, token_id, price=None):
        return {"has_liquidity": True, "total_size": 0, "asks": []}
