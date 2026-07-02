#!/usr/bin/env python3
"""Python MT5 Connector.

Fetches closed bar data from MetaTrader 5 terminal and pushes it to Tradebot.
Requires `pip install MetaTrader5 requests` on a Windows host with MT5 installed.
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone
import requests

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("mt5_connector")

# Import MetaTrader5 (only available on Windows)
try:
    import MetaTrader5 as mt5
except ImportError:
    logger.warning("MetaTrader5 library is not installed or this OS is not Windows. MT5 terminal features will be unavailable.")
    mt5 = None

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1/bridge")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "CHANGE_ME_webhook_token")
BODY_SECRET = os.getenv("BODY_SECRET", "CHANGE_ME_body_secret")
BROKER_NAME = os.getenv("BROKER_NAME", "MetaQuotes")
ACCOUNT_ID = os.getenv("ACCOUNT_ID", "123456")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "60"))

# Timeframe mapping from string to MT5 constants
TIMEFRAME_MAP = {
    "M5": 5,  # mt5.TIMEFRAME_M5
    "M15": 15,  # mt5.TIMEFRAME_M15
    "H1": 16385,  # mt5.TIMEFRAME_H1
    "H4": 16388,  # mt5.TIMEFRAME_H4
}

# Configured feeds to monitor
MONITORED_FEEDS = [
    {"symbol": "XAUUSD", "timeframe": "M15"},
    {"symbol": "XAUUSD", "timeframe": "H1"},
    {"symbol": "EURUSD", "timeframe": "M15"},
    {"symbol": "EURUSD", "timeframe": "H1"},
]


def send_heartbeat(status: str, msg: str) -> None:
    """Send heartbeat to the backend API."""
    url = f"{BACKEND_URL}/heartbeat/{WEBHOOK_TOKEN}"
    payload = {
        "secret": BODY_SECRET,
        "status": status,
        "details": {
            "message": msg,
            "broker": BROKER_NAME,
            "account_id": ACCOUNT_ID,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        logger.info(f"Heartbeat sent. Status: {status}. Server response: {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to send heartbeat: {e}")


def send_candle(symbol: str, timeframe: str, dt_utc: datetime, o: float, h: float, low: float, c: float, v: float) -> bool:
    """Send a closed candle to the backend API."""
    url = f"{BACKEND_URL}/mt5/candles/{WEBHOOK_TOKEN}"
    payload = {
        "secret": BODY_SECRET,
        "symbol": symbol,
        "timeframe": timeframe,
        "time": dt_utc.isoformat().replace("+00:00", "Z"),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": v,
        "broker": BROKER_NAME,
        "account_id": ACCOUNT_ID
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.info(f"Candle sent successfully: {symbol} {timeframe} at {dt_utc.isoformat()} (Close: {c})")
            return True
        else:
            logger.error(f"Failed to send candle: {symbol} {timeframe}. Response ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send candle request: {e}")
        return False


def poll_and_execute_orders() -> None:
    """Poll the backend for pending orders and execute them in the MT5 terminal (Phase F)."""
    if mt5 is None:
        return

    url = f"{BACKEND_URL}/orders/pending/{WEBHOOK_TOKEN}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return
        orders = resp.json().get("orders", [])
        for order in orders:
            signal_id = order["signal_id"]
            symbol = order["symbol"]
            action = order["action"]
            vol = order["volume"]
            sl = order["sl"]
            tp_list = order.get("tp", [])
            tp = tp_list[0] if tp_list else 0.0
            magic = order.get("magic_number", 9999)

            logger.info(f"Processing pending order: Signal ID {signal_id}, {action} {vol} lot on {symbol}")

            # Get current quote price
            symbol_info = mt5.symbol_info_tick(symbol)
            if symbol_info is None:
                logger.error(f"Failed to get tick info for {symbol}")
                report_fill(signal_id, "REJECTED", error_msg=f"Symbol {symbol} not found in MT5")
                continue

            order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
            price = symbol_info.ask if action == "BUY" else symbol_info.bid

            # Build MT5 order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(vol),
                "type": order_type,
                "price": float(price),
                "sl": float(sl),
                "tp": float(tp),
                "deviation": 20,
                "magic": int(magic),
                "comment": "Tradebot auto-execution",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            # Send order to MT5
            result = mt5.order_send(request)
            if result is None:
                logger.error("MT5 order_send returned None")
                report_fill(signal_id, "REJECTED", error_msg="MT5 terminal order_send returned None")
                continue

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"Order executed successfully in MT5: Ticket {result.order}, Fill Price {result.price}")
                report_fill(signal_id, "FILLED", fill_price=result.price, ticket_no=result.order)
            else:
                err_msg = f"Retcode {result.retcode}: {result.comment}"
                logger.error(f"MT5 execution failed: {err_msg}")
                report_fill(signal_id, "REJECTED", error_msg=err_msg)

    except Exception as e:
        logger.error(f"Error during order polling/execution: {e}")


def report_fill(signal_id: int, status: str, fill_price: float = None, ticket_no: int = None, error_msg: str = None) -> None:
    """Report execution outcome back to backend."""
    url = f"{BACKEND_URL}/orders/{signal_id}/fill/{WEBHOOK_TOKEN}"
    payload = {
        "status": status,
        "fill_price": fill_price,
        "ticket_no": ticket_no,
        "error_message": error_msg
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        logger.info(f"Reported fill status for Signal {signal_id}: {status}. Response code: {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to report fill status for Signal {signal_id}: {e}")


def main():
    if mt5 is None:
        logger.error("MetaTrader5 library is required to run this connector script on Windows.")
        sys.exit(1)

    # Initialize connection to MT5 terminal
    if not mt5.initialize():
        logger.error(f"Failed to initialize MetaTrader5. Error: {mt5.last_error()}")
        send_heartbeat("DOWN", f"MetaTrader5 initialization failed: {mt5.last_error()}")
        sys.exit(1)

    logger.info("MetaTrader5 connection established successfully.")
    send_heartbeat("OK", "MT5 Connector started successfully")

    # Track last bar times to prevent double ingestion
    last_bar_times = {}
    last_heartbeat_time = time.time()

    try:
        while True:
            # Poll each feed for new closed bar
            for feed in MONITORED_FEEDS:
                sym = feed["symbol"]
                tf_name = feed["timeframe"]
                tf_constant = TIMEFRAME_MAP.get(tf_name)

                if tf_constant is None:
                    continue

                # Fetch the last 2 bars (index 0 is current forming bar, index 1 is previous closed bar)
                rates = mt5.copy_rates_from_pos(sym, tf_constant, 0, 2)
                if rates is None or len(rates) < 2:
                    logger.warning(f"No rates returned for {sym} {tf_name}. Check if symbol is visible in MarketWatch.")
                    continue

                closed_rate = rates[0]  # Previous bar
                bar_time_raw = int(closed_rate["time"])
                dt_utc = datetime.fromtimestamp(bar_time_raw, tz=timezone.utc)

                feed_key = f"{sym}:{tf_name}"
                if feed_key not in last_bar_times:
                    # Initialize last bar time with current closed bar to avoid back-filling on start
                    last_bar_times[feed_key] = bar_time_raw
                    logger.info(f"Initialized feed tracker for {sym} {tf_name} at {dt_utc.isoformat()}")
                    continue

                # If a new bar is detected
                if bar_time_raw > last_bar_times[feed_key]:
                    # Closed candle properties
                    o = float(closed_rate["open"])
                    h = float(closed_rate["high"])
                    low = float(closed_rate["low"])
                    c = float(closed_rate["close"])
                    v = float(closed_rate["real_volume"] if "real_volume" in closed_rate else closed_rate["tick_volume"])

                    success = send_candle(sym, tf_name, dt_utc, o, h, low, c, v)
                    if success:
                        last_bar_times[feed_key] = bar_time_raw

            # Poll and execute pending trade orders (Phase F)
            poll_and_execute_orders()

            # Send periodic heartbeats
            if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL_SECONDS:
                send_heartbeat("OK", "MT5 Terminal active and polling feeds")
                last_heartbeat_time = time.time()

            time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Connector stopping...")
        send_heartbeat("PAUSED", "Connector stopped by user")
    finally:
        mt5.shutdown()
        logger.info("MetaTrader5 connection closed.")


if __name__ == "__main__":
    main()
