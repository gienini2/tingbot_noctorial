"""
Runner Live — Bucle principal del bot de trading.

Fixes aplicados:
  #1 — Doble inicialización: position_open/btc_qty/exit_manager se declaran
       ANTES del bloque de recuperación de posición, no después.
  #2 — hmac: query string construida con sorted() para consistencia con Binance.
  #3 — space calculado dinámicamente desde distance_to_resistance.
  #4 — except granular: errores transitorios reintentan, fatales rompen.
  #6 — ftmo_kill_check llamada dentro del bucle en cada iteración.
  #7 — adjust_quantity_to_lot_size eliminada (era huérfana y tenía bug).
  #8 — Filtro de vela extendida movido DESPUÉS de la gestión de salida.
  #9 — Bug polvo: añadido continue para evitar NameError en order.get().
  #10 — FTMO: current_day comparado como date vs date (no datetime vs date).
  #11 — ATR calculado y pasado al exit_manager para trailing adaptativo.
  #12 — Vigilante integrado: salida por indicadores combinada con trailing.
  #13 — Sincronización capital real Binance tras cada SELL.
"""

import os
import time
import hmac
import hashlib
import requests
import signal
import sys
import pandas as pd
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

from capital_manager import Agent4ExitManager, save_capital_state
from husmeador_v2 import husmeador, HUSMEADOR_PARAMS
from termometro_v2 import termometro
from Hombre_del_tiempo import hombre_del_tiempo
from decisor_35 import decisor_35
from vigilante import vigilante

from urllib.parse import urlencode


# =========================
# CONFIG
# =========================
SYMBOL   = "BTCUSDC"
INTERVAL = "5m"
BASE     = "https://api.binance.com"

API_KEY    = os.environ["BINANCE_API_KEY"]
API_SECRET = os.environ["BINANCE_API_SECRET"]
HEADERS    = {"X-MBX-APIKEY": API_KEY}

TRANSIENT_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ReadTimeout,
)


# =========================
# BINANCE API
# =========================

def get_symbol_filters(symbol):
    r = requests.get(f"{BASE}/api/v3/exchangeInfo", timeout=10)
    data = r.json()
    for s in data["symbols"]:
        if s["symbol"] == symbol:
            filters = {f["filterType"]: f for f in s["filters"]}
            return filters
    raise RuntimeError("Symbol not found")

SYMBOL_FILTERS = get_symbol_filters(SYMBOL)


def quantize_qty(qty, step_size):
    q    = Decimal(str(qty))
    step = Decimal(step_size)
    return (q // step) * step


def signed_request(method, path, params=None):
    if params is None:
        params = {}

    params["timestamp"] = int(time.time() * 1000)
    query = urlencode(sorted(params.items()))
    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    url = f"{BASE}{path}?{query}&signature={signature}"

    if method == "GET":
        r = requests.get(url, headers=HEADERS)
    else:
        r = requests.post(url, headers=HEADERS)

    if r.status_code != 200:
        telegram_send(f"BINANCE ERROR: {r.text}")
        r.raise_for_status()

    return r.json()


def get_usdc_balance():
    data = signed_request("GET", "/api/v3/account")
    usdc = next((b for b in data["balances"] if b["asset"] == "USDC"), None)
    return float(usdc["free"]) if usdc else 0.0


def get_btc_balance():
    data = signed_request("GET", "/api/v3/account")
    btc = next((b for b in data["balances"] if b["asset"] == "BTC"), None)
    return float(btc["free"]) if btc else 0.0


def get_last_price():
    r = requests.get(
        f"{BASE}/api/v3/ticker/price",
        params={"symbol": SYMBOL},
        timeout=10,
    )
    return float(r.json()["price"])


def market_buy_btc_with_usdc(usdc_amount):
    price    = Decimal(str(get_last_price()))
    filters  = SYMBOL_FILTERS
    lot      = filters["LOT_SIZE"]
    step_size   = lot["stepSize"]
    min_qty     = Decimal(lot["minQty"])

    if "NOTIONAL" in filters:
        min_notional = Decimal(filters["NOTIONAL"]["minNotional"])
    else:
        min_notional = Decimal(filters["MIN_NOTIONAL"]["minNotional"])

    raw_qty = Decimal(str(usdc_amount)) / price
    qty     = quantize_qty(raw_qty, step_size)

    if qty < min_qty:
        raise RuntimeError("MIN_QTY not met")
    if qty * price < min_notional:
        raise RuntimeError("MIN_NOTIONAL not met")

    return signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol":   SYMBOL,
            "side":     "BUY",
            "type":     "MARKET",
            "quantity": format(qty, "f"),
        },
    )


def market_sell_btc(qty):
    filters   = SYMBOL_FILTERS
    step_size = filters["LOT_SIZE"]["stepSize"]
    qty       = float(quantize_qty(qty, step_size))

    return signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol":   SYMBOL,
            "side":     "SELL",
            "type":     "MARKET",
            "quantity": format(qty, "f"),
        },
    )


def get_last_closed_kline():
    r = requests.get(
        f"{BASE}/api/v3/klines",
        params={"symbol": SYMBOL, "interval": INTERVAL, "limit": 2},
        timeout=10,
    )
    k = r.json()[-2]
    return {
        "timestamp": pd.to_datetime(k[0], unit="ms", utc=True),
        "open":      float(k[1]),
        "high":      float(k[2]),
        "low":       float(k[3]),
        "close":     float(k[4]),
        "volume":    float(k[5]),
    }


# =========================
# TELEGRAM
# =========================

def telegram_send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.environ['TG_BOT_TOKEN']}/sendMessage",
            json={"chat_id": os.environ["TG_CHAT_ID"], "text": msg},
            timeout=10,
        )
    except Exception:
        pass


# =========================
# FTMO KILL-SWITCH
# =========================

def ftmo_kill_check(equity_now, equity_start_day, equity_start_account, current_day):
    today = datetime.now(timezone.utc).date()

    if today != current_day:
        equity_start_day = equity_now
        current_day      = today

    if equity_now <= equity_start_day * 0.95:
        return False, "FTMO DAILY LOSS 5%", equity_start_day, current_day

    if equity_now <= equity_start_account * 0.90:
        return False, "FTMO MAX LOSS 10%", equity_start_day, current_day

    return True, "", equity_start_day, current_day


# =========================
# UTIL
# =========================

def sleep_to_next_candle():
    """Espera al inicio de la siguiente vela M5."""
    now = datetime.now(timezone.utc)
    seconds_in_5min = (now.minute % 5) * 60 + now.second + now.microsecond / 1e6
    time.sleep(300 - seconds_in_5min)


def handle_shutdown(signum, frame):
    telegram_send("⛔ BOT DETENIDO (SIGNAL)")
    sys.exit(0)


def compute_space(distance_to_resistance, price) -> str:
    if distance_to_resistance is None or price <= 0:
        return "sufficient"
    ratio = distance_to_resistance / price
    if ratio > 0.008:
        return "much"
    elif ratio > 0.003:
        return "sufficient"
    else:
        return "little"


def compute_atr(df, period=14) -> float:
    if len(df) < period + 1:
        return None
    high  = df["high"].iloc[-period:]
    low   = df["low"].iloc[-period:]
    close = df["close"].iloc[-period - 1:-1]
    tr = pd.concat([
        high - low,
        (high - close.values).abs(),
        (low  - close.values).abs(),
    ], axis=1).max(axis=1)
    return float(tr.mean())


def execute_sell(btc_qty, exit_manager, entry_price, reason):
    """Ejecuta la venta, sincroniza capital real y notifica con saldo actualizado."""
    order    = market_sell_btc(btc_qty)
    status   = order.get("status")
    executed = float(order.get("executedQty") or 0)

    if status == "FILLED" or executed > 0:
        # Sincronizar capital con saldo real Binance
        real_balance = get_usdc_balance()
        exit_manager.state["current_capital"] = real_balance
        save_capital_state(exit_manager.state)

        # Calcular PnL estimado para el reporte
        fills = order.get("fills", [])
        if fills:
            exit_price = sum(float(f["price"]) * float(f["qty"]) for f in fills) / \
                         sum(float(f["qty"]) for f in fills)
        else:
            exit_price = entry_price  # fallback

        pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0

        # Reporte Telegram completo con saldo real
        exit_manager.send_sell_report(real_balance, reason, pnl_pct)
        return True
    else:
        telegram_send(f"SELL NO FILLED: {order}")
        return False


# =========================
# MAIN
# =========================

def main():
    signal.signal(signal.SIGINT,  handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    balance     = get_usdc_balance()
    btc_balance = get_btc_balance()
    price       = get_last_price()
    equity      = balance + btc_balance * price

    position_open = False
    btc_qty       = 0.0
    entry_price   = 0.0
    exit_manager  = Agent4ExitManager(equity, telegram_send)

    if btc_balance > 0.00001:
        position_open = True
        btc_qty       = btc_balance
        entry_price   = price
        exit_manager.open_position(entry_price, atr=None, allow_trailing=True)
        telegram_send(
            f"⚠️ POSICIÓN RECUPERADA\n"
            f"BTC: {btc_qty:.8f}\n"
            f"Precio actual: {entry_price:.2f}"
        )

    trade_usdc = get_usdc_balance() * 0.98
    telegram_send(
        f"💰 SALDO: {balance:.2f} USDC\n"
        f"📊 Trade size: {trade_usdc:.2f} USDC\n"
        f"🟢 BOT LIVE ARRANCADO"
    )

    equity_start_account = equity
    equity_start_day     = equity
    current_day          = datetime.now(timezone.utc).date()

    last_exit_time  = None
    COOLDOWN_SECONDS = 180

    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.index.name = "timestamp"

    params = HUSMEADOR_PARAMS["5m"]

    def get_total_equity():
        usdc  = get_usdc_balance()
        btc   = get_btc_balance()
        price = get_last_price()
        return usdc + btc * price

    while True:
        try:
            candle = get_last_closed_kline()
            ts     = candle.pop("timestamp")
            df.loc[ts] = candle

            if len(df) > 200:
                df = df.iloc[-200:]

            # Indicadores técnicos
            df["ema_short"]  = df["close"].ewm(span=20, adjust=False).mean()
            df["ema_mid"]    = df["close"].ewm(span=50, adjust=False).mean()
            df["avg_volume"] = df["volume"].rolling(20).mean()

            delta = df["close"].diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = -delta.clip(upper=0).rolling(14).mean()
            rs    = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))

            low_min  = df["low"].rolling(14).min()
            high_max = df["high"].rolling(14).max()
            range_   = (high_max - low_min).replace(0, 1e-9)
            df["stoch_k"] = 100 * (df["close"] - low_min) / range_
            df["stoch_d"] = df["stoch_k"].rolling(3).mean()

            last = df.iloc[-1]

            # =========================
            # FTMO KILL-SWITCH
            # =========================
            equity_now = get_total_equity()
            ok, motivo, equity_start_day, current_day = ftmo_kill_check(
                equity_now, equity_start_day, equity_start_account, current_day
            )
            if not ok:
                telegram_send(f"🛑 KILL SWITCH ACTIVADO: {motivo}")
                break

            # =========================
            # GESTIÓN DE SALIDA
            # Orden: Vigilante → Trailing/SL
            # =========================
            if position_open:

                # 1. VIGILANTE — salida por indicadores
                vig = vigilante(df, position_open, entry_price)
                if vig["exit_signal"]:
                    btc_qty = get_btc_balance()
                    if btc_qty < 0.00001:
                        telegram_send(f"⚠️ POLVO DETECTADO: {btc_qty:.8f} BTC")
                        position_open = False
                        sleep_to_next_candle()
                        continue

                    telegram_send(f"🔔 VIGILANTE: {vig['reason']}")
                    sold = execute_sell(btc_qty, exit_manager, entry_price, vig["reason"])
                    if sold:
                        position_open  = False
                        btc_qty        = 0.0
                        entry_price    = 0.0
                        last_exit_time = time.time()
                        sleep_to_next_candle()
                        continue

                # 2. TRAILING STOP / STOP LOSS — capital_manager
                result = exit_manager.on_price_update(last["close"])
                if result:
                    btc_qty = get_btc_balance()

                    if btc_qty < 0.00001:
                        telegram_send(f"⚠️ POLVO DETECTADO: {btc_qty:.8f} BTC")
                        position_open = False
                        sleep_to_next_candle()
                        continue

                    sold = execute_sell(btc_qty, exit_manager, entry_price, result["reason"])
                    if sold:
                        position_open  = False
                        btc_qty        = 0.0
                        entry_price    = 0.0
                        last_exit_time = time.time()

            # Filtro de vela extendida
            if abs(last["close"] - last["ema_short"]) / last["ema_short"] > 0.004:
                sleep_to_next_candle()
                continue

            if len(df) < max(params["lookback"], 50):
                sleep_to_next_candle()
                continue

            evento_result = husmeador(df, params)
            if evento_result is None:
                sleep_to_next_candle()
                continue

            evento, evento_tipo = evento_result

            if not evento or position_open:
                sleep_to_next_candle()
                continue

            if last_exit_time and time.time() - last_exit_time < COOLDOWN_SECONDS:
                sleep_to_next_candle()
                continue

            # =========================
            # SCORING Y CONTEXTO
            # =========================
            score_data = termometro(
                candle=last.to_dict(),
                ema_short=last["ema_short"],
                ema_mid=last["ema_mid"],
                rsi=last["rsi"],
                stoch_k=last["stoch_k"],
                stoch_d=last["stoch_d"],
                avg_volume=last["avg_volume"],
                ema_short_prev=float(df["ema_short"].iloc[-6]) if len(df) >= 6 else None,
                ema_mid_prev=float(df["ema_mid"].iloc[-6]) if len(df) >= 6 else None,
            )

            context = hombre_del_tiempo(
                candle_data=df,
                timeframe="1m",
                score=score_data["score"],
                score_reasons=score_data["score_reasons"],
            )

            space_real = compute_space(
                context.get("distance_to_resistance"),
                last["close"],
            )

            decision = decisor_35(
                evento_detectado=evento,
                score=score_data["score"],
                score_reasons=score_data["score_reasons"],
                context={
                    "trend_bias":      context["bias"],
                    "market_state":    context["market_state"],
                    "trade_direction": "long",
                    "space":           space_real,
                },
                timeframe="1m",
            )

            # =========================
            # ENTRADA
            # =========================
            if decision["allow_trade"]:
                trade_usdc = get_usdc_balance() * 0.98
                order      = market_buy_btc_with_usdc(trade_usdc)

                if order.get("status") != "FILLED":
                    telegram_send(f"BUY NO FILLED: {order}")
                    sleep_to_next_candle()
                    continue

                fills = order.get("fills", [])
                if fills:
                    btc_qty     = sum(float(f["qty"]) for f in fills)
                    entry_price = sum(
                        float(f["price"]) * float(f["qty"]) for f in fills
                    ) / btc_qty
                else:
                    btc_qty     = float(order.get("executedQty") or 0)
                    entry_price = float(last["close"])

                atr_now = compute_atr(df)
                position_open = True
                exit_manager.open_position(
                    entry_price,
                    atr=atr_now,
                    allow_trailing=True,
                )

                # Saldo real antes de la compra para el reporte
                saldo_antes = get_usdc_balance()
                exit_manager.send_buy_report(
                    real_balance=saldo_antes,
                    btc_qty=btc_qty,
                    entry_price=entry_price,
                    score=score_data["score"],
                    space=space_real,
                    atr=atr_now if atr_now else 0,
                    categoria=decision["trade_category"],
                    evento=evento_tipo,
                )

            sleep_to_next_candle()

        except TRANSIENT_ERRORS as e:
            telegram_send(f"⚠️ Error transitorio, reintentando: {e}")
            sleep_to_next_candle()
            continue

        except Exception as e:
            telegram_send(f"⛔ ERROR CRÍTICO: {e}")
            break


if __name__ == "__main__":
    main()
