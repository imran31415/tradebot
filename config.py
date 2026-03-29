import os
from dotenv import load_dotenv

load_dotenv()

# --- Credentials ---
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
CHAIN_ID = 137  # Polygon mainnet
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "0"))
FUNDER_ADDRESS = os.getenv("FUNDER_ADDRESS", "")

# --- Strategy Parameters ---
BUY_PRICE = 0.99
MIN_PROBABILITY = 0.95
TRADE_SIZE_USDC = 124.0
MAX_HOURS_TO_RESOLUTION = 24
MIN_HOURS_TO_RESOLUTION = 0.5
SCAN_INTERVAL_SECONDS = 48
MAX_OPEN_ORDERS = 50
MAX_TOTAL_EXPOSURE_USDC = 10000.0
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# --- API URLs ---
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"

# --- Polymarket Constants ---
CRYPTO_TAG_ID = 21
NEG_RISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
CTF_EXCHANGE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
