import json
import logging
import time
from datetime import datetime, timezone

import requests

import config

logger = logging.getLogger(__name__)


class GammaClient:
    """Wraps the Gamma API for market discovery."""

    def __init__(self):
        self.base_url = config.GAMMA_API_URL
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, endpoint, params=None):
        url = f"{self.base_url}{endpoint}"
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def find_bitcoin_markets(self):
        """Find active Bitcoin-related markets on Polymarket."""
        markets = []
        offset = 0
        limit = 100

        while True:
            params = {
                "tag_id": config.CRYPTO_TAG_ID,
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset,
            }
            try:
                batch = self._get("/markets", params)
            except requests.RequestException as e:
                logger.error("Gamma API request failed: %s", e)
                break

            if not batch:
                break

            for market in batch:
                q = market.get("question", "").lower()
                slug = market.get("slug", "").lower()
                if any(kw in q or kw in slug for kw in ("btc", "bitcoin")):
                    markets.append(market)

            if len(batch) < limit:
                break
            offset += limit
            time.sleep(0.3)

        logger.info("Found %d Bitcoin markets", len(markets))
        return markets


def filter_opportunities(markets):
    """Filter markets to find near-certain outcomes close to resolution."""
    opportunities = []
    now = datetime.now(timezone.utc)

    for market in markets:
        try:
            # Must have order book enabled
            if not market.get("enableOrderBook"):
                continue
            if not market.get("active"):
                continue

            # Parse outcome prices
            prices_raw = market.get("outcomePrices", "")
            if not prices_raw:
                continue
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if len(prices) < 2:
                continue

            yes_price = float(prices[0])
            no_price = float(prices[1])

            # Determine dominant side
            if yes_price >= config.MIN_PROBABILITY:
                dominant_side = "YES"
                dominant_price = yes_price
            elif no_price >= config.MIN_PROBABILITY:
                dominant_side = "NO"
                dominant_price = no_price
            else:
                continue

            # Parse end date
            end_date_str = market.get("endDate", "")
            if not end_date_str:
                continue
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            hours_to_resolution = (end_date - now).total_seconds() / 3600.0

            if hours_to_resolution < config.MIN_HOURS_TO_RESOLUTION:
                continue
            if hours_to_resolution > config.MAX_HOURS_TO_RESOLUTION:
                continue

            # Extract token IDs
            token_ids_raw = market.get("clobTokenIds", "")
            if not token_ids_raw:
                continue
            token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
            if len(token_ids) < 2:
                continue

            token_id = token_ids[0] if dominant_side == "YES" else token_ids[1]

            # Score: higher probability + sooner resolution = better
            score = dominant_price * (1.0 / max(hours_to_resolution, 0.1))

            neg_risk = market.get("negRisk", False)

            opportunities.append({
                "question": market.get("question", ""),
                "token_id": token_id,
                "side": dominant_side,
                "current_price": dominant_price,
                "end_date": end_date.isoformat(),
                "hours_to_resolution": round(hours_to_resolution, 2),
                "condition_id": market.get("conditionId", ""),
                "neg_risk": neg_risk,
                "score": score,
                "market_slug": market.get("slug", ""),
            })

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.warning("Skipping market %s: %s", market.get("question", "?"), e)
            continue

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Filtered to %d opportunities", len(opportunities))
    return opportunities


def get_tick_size(condition_id):
    """Query CLOB API for the market's tick size using condition ID."""
    if not condition_id:
        return 0.01
    try:
        url = f"{config.CLOB_API_URL}/markets/{condition_id}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("minimum_tick_size", 0.01))
    except Exception as e:
        logger.debug("Could not fetch tick size for %s: %s — defaulting to 0.01", condition_id[:20], e)
        return 0.01
