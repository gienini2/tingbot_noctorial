"""
briefing_noctorial.py — Briefing diario 10:00
=============================================
Ejecutar como tarea programada en Windows (Task Scheduler) a las 10:00.
Conecta a MT5, calcula S/R reales por instrumento y manda Telegram.

Uso:
  set MT5_PASSWORD=xxx
  set TG_BOT_TOKEN=xxx
  set TG_CHAT_ID=xxx
  python briefing_noctorial.py
"""

import os
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
MT5_LOGIN    = 57366
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER   = "Noctorial-Trade"
TG_TOKEN     = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID", "")

INSTRUMENTS = ["XAUUSD", "XAGUSD", "TSLA", "NVDA", "AAPL"]
TIMEFRAMES   = [mt5.TIMEFRAME_H1, mt5.TIMEFRAME_M15]   # H1 para S/R, M15 para sesgo


def tg(msg: str):
    if not TG_TOKEN:
        print(msg)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG ERROR] {e}")


def detect_swings(highs, lows, lookback=5):
    swing_highs, swing_lows = [], []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == max(highs[i - lookback:i + lookback + 1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i - lookback:i + lookback + 1]):
            swing_lows.append(lows[i])
    return swing_highs, swing_lows


def cluster_levels(levels, tolerance_pct=0.003):
    """Agrupa niveles cercanos en uno solo (media del cluster)."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters = [[levels[0]]]
    for v in levels[1:]:
        if abs(v - clusters[-1][-1]) / clusters[-1][-1] < tolerance_pct:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [round(np.mean(c), 4) for c in clusters]


def get_sr(symbol: str):
    """Calcula S/R sobre H1 últimas 100 velas."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 100)
    if rates is None or len(rates) < 20:
        return [], []
    df = pd.DataFrame(rates)
    sh, sl = detect_swings(df["high"].values, df["low"].values, lookback=5)
    resistencias = cluster_levels(sh[-8:], tolerance_pct=0.004)[-3:]
    soportes     = cluster_levels(sl[-8:], tolerance_pct=0.004)[-3:]
    return sorted(soportes), sorted(resistencias, reverse=True)


def get_bias(symbol: str):
    """Sesgo M15: precio vs EMA50."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 60)
    if rates is None or len(rates) < 50:
        return "neutral"
    df = pd.DataFrame(rates)
    ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    price = df["close"].iloc[-1]
    slope = df["close"].ewm(span=50, adjust=False).mean().iloc[-1] - \
            df["close"].ewm(span=50, adjust=False).mean().iloc[-5]
    if price > ema50 and slope > 0:
        return "alcista ▲"
    elif price < ema50 and slope < 0:
        return "bajista ▼"
    return "lateral ◆"


def get_price(symbol: str):
    tick = mt5.symbol_info_tick(symbol)
    return round((tick.bid + tick.ask) / 2, 4) if tick else 0.0


def briefing_instrumento(symbol: str):
    precio    = get_price(symbol)
    bias      = get_bias(symbol)
    sop, res  = get_sr(symbol)

    # Escenarios
    escenario_alcista = ""
    escenario_bajista = ""

    if sop:
        escenario_bajista = f"Pullback a {sop[0]} → buscar rebote largo"
    if res:
        escenario_alcista = f"Rotura de {res[0]} → continuación"

    # Zona operativa de la sesión
    soporte_sesion    = sop[0]  if sop else "—"
    resistencia_sesion = res[0] if res else "—"

    lineas = [
        f"<b>{symbol}</b>  ({precio})  {bias}",
        f"  S: {' / '.join(str(s) for s in sop) if sop else '—'}",
        f"  R: {' / '.join(str(r) for r in res) if res else '—'}",
        f"  📗 Alcista: {escenario_alcista or '—'}",
        f"  📕 Bajista: {escenario_bajista or '—'}",
        f"  🎯 Zona sesión: {soporte_sesion} → {resistencia_sesion}",
    ]
    return "\n".join(lineas)


def main():
    if not mt5.initialize():
        print("MT5 init falló")
        return
    if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print("MT5 login falló")
        mt5.shutdown()
        return

    info  = mt5.account_info()
    ahora = datetime.now(TZ).strftime("%d/%m/%Y %H:%M")

    header = (
        f"☀️ <b>BRIEFING NOCTORIAL — {ahora}</b>\n"
        f"Balance: €{info.balance:.2f}  |  Equity: €{info.equity:.2f}\n"
        f"Profit acumulado: €{info.balance - 9770:.2f}\n"
        f"─────────────────────────"
    )
    tg(header)

    for sym in INSTRUMENTS:
        bloque = briefing_instrumento(sym)
        tg(bloque)

    footer = (
        "─────────────────────────\n"
        "🕔 Sesión activa: 17:00 → 22:00\n"
        "⚠️ Kill-switch diario: -€280\n"
        "✅ Objetivo sesión: +€50 mínimo"
    )
    tg(footer)
    mt5.shutdown()


if __name__ == "__main__":
    main()
