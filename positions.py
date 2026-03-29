import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PositionTracker:
    """Tracks orders, fills, and P&L in memory with JSON persistence."""

    def __init__(self):
        self.orders = {}  # order_id -> order details

    def add_order(self, order_id, details):
        """Record a new order."""
        self.orders[order_id] = {
            "order_id": order_id,
            "token_id": details.get("token_id", ""),
            "side": details.get("side", "BUY"),
            "price": details.get("price", 0),
            "size": details.get("size", 0),
            "size_usdc": details.get("size_usdc", 0),
            "status": "open",
            "placed_at": datetime.now(timezone.utc).isoformat(),
            "filled_at": None,
            "question": details.get("question", ""),
            "dry_run": details.get("dry_run", False),
        }
        logger.info("Tracked order %s: %s", order_id, details.get("question", "")[:60])

    def update_order(self, order_id, status):
        """Update order status (open, filled, cancelled, resolved)."""
        if order_id in self.orders:
            self.orders[order_id]["status"] = status
            if status == "filled":
                self.orders[order_id]["filled_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Updated order %s -> %s", order_id, status)

    def get_total_exposure(self):
        """Sum of all open + filled position values in USDC."""
        return sum(
            o["size_usdc"]
            for o in self.orders.values()
            if o["status"] in ("open", "filled")
        )

    def get_open_count(self):
        """Number of unfilled orders."""
        return sum(1 for o in self.orders.values() if o["status"] == "open")

    def get_filled_positions(self):
        """List filled positions awaiting resolution."""
        return [o for o in self.orders.values() if o["status"] == "filled"]

    def get_stats(self):
        """Summary statistics."""
        total = len(self.orders)
        open_count = sum(1 for o in self.orders.values() if o["status"] == "open")
        filled = sum(1 for o in self.orders.values() if o["status"] == "filled")
        cancelled = sum(1 for o in self.orders.values() if o["status"] == "cancelled")
        resolved = sum(1 for o in self.orders.values() if o["status"] == "resolved")

        total_exposure = self.get_total_exposure()
        # At 0.99 buy price, each share yields ~$0.01 profit on resolution
        expected_profit = sum(
            o["size"] * (1.0 - o["price"])
            for o in self.orders.values()
            if o["status"] in ("filled", "resolved")
        )
        fill_rate = filled / max(total, 1)

        return {
            "total_orders": total,
            "open": open_count,
            "filled": filled,
            "cancelled": cancelled,
            "resolved": resolved,
            "fill_rate": round(fill_rate, 3),
            "total_exposure_usdc": round(total_exposure, 2),
            "expected_profit_usdc": round(expected_profit, 2),
        }

    def save(self, filepath="positions.json"):
        """Persist positions to JSON file."""
        try:
            with open(filepath, "w") as f:
                json.dump(self.orders, f, indent=2)
            logger.debug("Saved %d positions to %s", len(self.orders), filepath)
        except IOError as e:
            logger.error("Failed to save positions: %s", e)

    def load(self, filepath="positions.json"):
        """Load positions from JSON file."""
        try:
            with open(filepath) as f:
                self.orders = json.load(f)
            logger.info("Loaded %d positions from %s", len(self.orders), filepath)
        except FileNotFoundError:
            logger.info("No existing positions file found, starting fresh")
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load positions: %s", e)
