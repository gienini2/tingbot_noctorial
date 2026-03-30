"""
runner_mt5_noctorial.py — TingBot para Noctorial MT5
=====================================================
Instrumentos: XAUUSD, XAGUSD, TSLA, NVDA, AAPL (configurable)
Horario:      17:00 → 22:00 hora España (Europe/Madrid)
Cierre auto:  21:55 — cierra toda posición abierta antes de parar

Reglas Noctorial Fase 1 (10K):
  - Pérdida diaria máxima:  3%  → €300
  - Pérdida total máxima:   40% → €4.000 (KO €6.000)
  - Objetivo ganancia:      5%  → €500
  - Regla mejor día:        ningún día > 50% del profit total acumulado

Kill-switch:
  - Flotante negativo diario ≥ €280 → para el día (margen de seguridad)
  - Equity total ≤ €6.000          → para el challenge
  - Profit diario ≥ 50% del acumulado → para el día (regla mejor día)
  - Objetivo €500 alcanzado         → para el challenge

Lotaje:
  - Calculado automáticamente por instrumento
  - Riesgo por trade ≤ 1.5% del capital actual
  - Para plata/oro: nunca más de 0.15 lotes
  - Para tecnológicas: nunca más de 5 acciones (lote 0.05)

Uso:
  set MT5_PASSWORD=tu_contraseña
  set TG_BOT_TOKEN=tu_token
  set TG_CHAT_ID=tu_chat_id
  python runner_mt5_noctorial.py
"""

import os
import time
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests

from husmeador_v2 import husmeador, HUSMEADOR_PARAMS
from termometro_v2 import termometro
from vigilante import vigilante
from Hombre_del_tiempo import hombre_del_tiempo
from decisor_35 import decisor_35
import json

# =====================================================================
# CONFIG
# =====================================================================

MT5_LOGIN    = 57366
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER   = "Noctorial-Trade"

TG_TOKEN   = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

TZ_SPAIN = ZoneInfo("Europe/Madrid")

# Horario de operación (hora España)
HORA_INICIO = 17   # 17:00
HORA_FIN    = 22   # 22:00
HORA_CIERRE = 21   # 21:55 — cierre forzado de posiciones

# Reglas Noctorial
INITIAL_CAPITAL     = 10_000.0
PROFIT_TARGET       =    500.0   # €500 = 5%
DAILY_LOSS_LIMIT    =    280.0   # €280 — margen de seguridad bajo el 3% (€300)
TOTAL_EQUITY_FLOOR  =  6_000.0   # KO total
BEST_DAY_RATIO      =     0.50   # ningún día > 50% del profit acumulado

# Riesgo por trade
RISK_PER_TRADE_PCT  = 0.015      # 1.5% del capital actual

# Instrumentos habilitados
INSTRUMENTS = {
    "XAUUSD": {
        "pip_value":  1.0,        # ~$1 por pip por lote (0.01 lotes = 0.01$)
        "pip_size":   0.01,       # mínimo movimiento
        "max_lots":   0.15,       # límite duro anti-infracción
        "min_lots":   0.01,
        "sl_pips":    150,        # SL en pips (1.50$ de movimiento)
        "description": "Oro"
    },
    "XAGUSD": {
        "pip_value":  50.0,       # $50 por pip por lote estándar
        "pip_size":   0.001,
        "max_lots":   0.10,       # MUY conservador — plata muy volátil
        "min_lots":   0.01,
        "sl_pips":    200,        # 0.20$ de movimiento
        "description": "Plata"
    },
    "TSLA": {
        "pip_value":  1.0,
        "pip_size":   0.01,
        "max_lots":   0.05,       # ~5 acciones
        "min_lots":   0.01,
        "sl_pips":    60,         # 0.60$ de movimiento
        "description": "Tesla"
    },
    "NVDA": {
        "pip_value":  1.0,
        "pip_size":   0.01,
        "max_lots":   0.05,
        "min_lots":   0.01,
        "sl_pips":    80,
        "description": "Nvidia"
    },
    "AAPL": {
        "pip_value":  1.0,
        "pip_size":   0.01,
        "max_lots":   0.05,
        "min_lots":   0.01,
        "sl_pips":    50,
        "description": "Apple"
    },
}

INTERVAL        = mt5.TIMEFRAME_M5
COOLDOWN_SECS   = 300   # 5 minutos entre trades por instrumento


# =====================================================================
# TELEGRAM
# =====================================================================

def tg(msg: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        print(f"[TG] {msg}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception:
        pass


# =====================================================================
# LOGGING DE RECHAZOS
# =====================================================================

LOG_FILE = "tingbot_log.jsonl"

def log_rechazo(symbol: str, motivo: str, precio: float, rsi: float = 0,
                stoch: float = 0, score: int = 0, evento: str = ""):
    """Registra cada rechazo en archivo jsonl para análisis posterior."""
    entry = {
        "ts":     datetime.now(TZ_SPAIN).strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "motivo": motivo,
        "precio": round(precio, 4),
        "rsi":    round(rsi, 1),
        "stoch":  round(stoch, 1),
        "score":  score,
        "evento": evento,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    # También imprime en consola para ver en tiempo real
    print(f"[{entry['ts']}] ❌ {symbol:8s} | {motivo:35s} | RSI:{rsi:5.1f} Stoch:{stoch:5.1f} Score:{score}")

def log_trade(symbol: str, accion: str, precio: float, lotes: float,
              score: int = 0, evento: str = "", motivo: str = ""):
    """Registra entradas y salidas."""
    entry = {
        "ts":     datetime.now(TZ_SPAIN).strftime("%Y-%m-%d %H:%M:%S"),
        "tipo":   "TRADE",
        "symbol": symbol,
        "accion": accion,
        "precio": round(precio, 4),
        "lotes":  lotes,
        "score":  score,
        "evento": evento,
        "motivo": motivo,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[{entry['ts']}] ✅ {symbol:8s} | {accion:6s} @ {precio:.4f} | Lotes:{lotes} Score:{score}")

def resumen_diario():
    """Lee el log del día y manda resumen por Telegram."""
    try:
        hoy = datetime.now(TZ_SPAIN).strftime("%Y-%m-%d")
        rechazos = {}
        trades = 0
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if not entry["ts"].startswith(hoy):
                    continue
                if entry.get("tipo") == "TRADE":
                    trades += 1
                else:
                    sym = entry["symbol"]
                    motivo = entry["motivo"]
                    key = f"{sym}|{motivo}"
                    rechazos[key] = rechazos.get(key, 0) + 1

        if not rechazos and trades == 0:
            tg("📊 Resumen sesión: sin actividad registrada.")
            return

        lineas = [f"📊 RESUMEN SESIÓN {hoy}", f"Trades ejecutados: {trades}", ""]
        if rechazos:
            lineas.append("Rechazos por motivo:")
            for key, count in sorted(rechazos.items(), key=lambda x: -x[1])[:10]:
                sym, mot = key.split("|", 1)
                lineas.append(f"  {sym}: {mot} ({count}x)")

        tg("\n".join(lineas))
    except Exception as e:
        tg(f"⚠️ Error en resumen: {e}")


# =====================================================================
# MT5 — INICIALIZACIÓN
# =====================================================================

def mt5_init():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() falló: {mt5.last_error()}")

    if not MT5_PASSWORD:
        raise RuntimeError("MT5_PASSWORD no configurado. Ejecuta: set MT5_PASSWORD=xxx")

    ok = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    if not ok:
        raise RuntimeError(f"MT5 login() falló: {mt5.last_error()}")

    info = mt5.account_info()
    tg(
        f"✅ MT5 CONECTADO — Noctorial\n"
        f"Cuenta: #{info.login}\n"
        f"Balance: €{info.balance:.2f}\n"
        f"Equity:  €{info.equity:.2f}\n"
        f"Horario: {HORA_INICIO}:00 → {HORA_FIN}:00 (España)\n"
        f"Instrumentos: {', '.join(INSTRUMENTS.keys())}"
    )
    return info


# =====================================================================
# MT5 — DATOS
# =====================================================================

def get_equity() -> float:
    info = mt5.account_info()
    return float(info.equity) if info else 0.0

def get_balance() -> float:
    info = mt5.account_info()
    return float(info.balance) if info else 0.0

def get_open_position(symbol: str):
    positions = mt5.positions_get(symbol=symbol)
    return positions[0] if positions and len(positions) > 0 else None

def get_all_open_positions():
    return mt5.positions_get() or []

def get_klines(symbol: str, n: int = 200) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, INTERVAL, 0, n + 1)
    if rates is None or len(rates) < 10:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("timestamp")
    df = df.rename(columns={"tick_volume": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    return df.iloc[:-1]   # excluir vela actual abierta


# =====================================================================
# LOTAJE AUTOMÁTICO
# =====================================================================

def calcular_lotes(symbol: str, capital: float) -> float:
    """
    Calcula lotes seguros para no superar RISK_PER_TRADE_PCT del capital.
    Respeta siempre max_lots del instrumento.
    """
    cfg = INSTRUMENTS[symbol]
    riesgo_euros = capital * RISK_PER_TRADE_PCT

    # Riesgo = lotes × sl_pips × pip_value
    # lotes = riesgo / (sl_pips × pip_value)
    lotes = riesgo_euros / (cfg["sl_pips"] * cfg["pip_value"])
    lotes = max(cfg["min_lots"], min(lotes, cfg["max_lots"]))

    # Redondear al step del broker (0.01)
    lotes = round(round(lotes / 0.01) * 0.01, 2)
    return lotes


# =====================================================================
# MT5 — EJECUCIÓN
# =====================================================================

def market_buy(symbol: str, lots: float) -> dict | None:
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        tg(f"⛔ No tick para {symbol}")
        return None

    sl_cfg = INSTRUMENTS[symbol]
    sl_price = round(tick.ask - sl_cfg["sl_pips"] * sl_cfg["pip_size"], 5)

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lots,
        "type":         mt5.ORDER_TYPE_BUY,
        "price":        tick.ask,
        "sl":           sl_price,
        "deviation":    30,
        "magic":        20260319,
        "comment":      f"TingBot_{symbol}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        tg(f"⛔ BUY {symbol} FALLIDO: {result.retcode} — {result.comment}")
        return None

    return {
        "ticket": result.order,
        "price":  result.price,
        "volume": result.volume,
        "sl":     sl_price,
    }


def market_sell(symbol: str, reason: str = "") -> bool:
    position = get_open_position(symbol)
    if position is None:
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       position.volume,
        "type":         mt5.ORDER_TYPE_SELL,
        "position":     position.ticket,
        "price":        tick.bid,
        "deviation":    30,
        "magic":        20260319,
        "comment":      f"Close_{reason[:20]}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        tg(f"⛔ SELL {symbol} FALLIDO: {result.retcode} — {result.comment}")
        return False
    return True


def cerrar_todo(reason: str):
    """Cierra todas las posiciones abiertas."""
    positions = get_all_open_positions()
    if not positions:
        return
    tg(f"🔒 Cerrando todas las posiciones: {reason}")
    for p in positions:
        market_sell(p.symbol, reason)


# =====================================================================
# HORARIO
# =====================================================================

def dentro_de_horario() -> bool:
    now = datetime.now(TZ_SPAIN)
    return HORA_INICIO <= now.hour < HORA_FIN

def es_hora_de_cierre() -> bool:
    now = datetime.now(TZ_SPAIN)
    return now.hour == HORA_CIERRE and now.minute >= 55

def minutos_para_inicio() -> int:
    now = datetime.now(TZ_SPAIN)
    if now.hour < HORA_INICIO:
        return (HORA_INICIO - now.hour) * 60 - now.minute
    return 0


# =====================================================================
# KILL-SWITCH NOCTORIAL
# =====================================================================

def kill_check(
    equity_now: float,
    equity_start_day: float,
    equity_start_account: float,
    profit_acumulado: float,
    current_day,
) -> tuple[bool, str, float, object]:

    today = datetime.now(timezone.utc).date()

    # Reset diario
    if today != current_day:
        equity_start_day = equity_now
        current_day = today
        tg(f"📅 Nuevo día — equity reset: €{equity_now:.2f}")

    # KO diario — flotante negativo
    daily_loss = equity_start_day - equity_now
    if daily_loss >= DAILY_LOSS_LIMIT:
        return False, f"KO DIARIO: pérdida €{daily_loss:.2f} (límite €{DAILY_LOSS_LIMIT})", equity_start_day, current_day

    # KO total
    if equity_now <= TOTAL_EQUITY_FLOOR:
        return False, f"KO TOTAL: equity €{equity_now:.2f}", equity_start_day, current_day

    # Objetivo alcanzado
    profit = equity_now - equity_start_account
    if profit >= PROFIT_TARGET:
        return False, f"🏆 OBJETIVO ALCANZADO: +€{profit:.2f}", equity_start_day, current_day

    # Regla del mejor día — profit de hoy no puede ser > 50% del acumulado
    profit_hoy = equity_now - equity_start_day
    if profit_acumulado > 0 and profit_hoy >= profit_acumulado * BEST_DAY_RATIO:
        return False, f"MEJOR DÍA 50%: hoy +€{profit_hoy:.2f} vs acumulado €{profit_acumulado:.2f}", equity_start_day, current_day

    return True, "", equity_start_day, current_day


# =====================================================================
# INDICADORES
# =====================================================================

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
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
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> float | None:
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

def compute_space(distance_to_resistance, price) -> str:
    if distance_to_resistance is None or price <= 0:
        return "sufficient"
    ratio = distance_to_resistance / price
    if ratio > 0.008:
        return "much"
    elif ratio > 0.003:
        return "sufficient"
    return "little"


# =====================================================================
# ESTADO POR INSTRUMENTO
# =====================================================================

class InstrumentState:
    def __init__(self, symbol: str):
        self.symbol       = symbol
        self.position_open = False
        self.entry_price  = 0.0
        self.entry_time   = None
        self.last_exit    = None
        self.trailing_max = None
        self.sl_price     = 0.0
        self.lots         = 0.0

    def reset(self):
        self.position_open = False
        self.entry_price   = 0.0
        self.entry_time    = None
        self.trailing_max  = None
        self.sl_price      = 0.0
        self.last_exit     = time.time()

    def on_price(self, price: float) -> str | None:
        """Trailing stop adaptativo. Retorna razón de cierre o None."""
        if not self.position_open:
            return None

        # Stop loss fijo
        if price <= self.sl_price:
            return "STOP LOSS"

        # Activar trailing cuando supera 1% de ganancia
        min_target = self.entry_price * 1.010
        if self.trailing_max is None:
            if price >= min_target:
                self.trailing_max = price
            return None

        # Actualizar máximo
        if price > self.trailing_max:
            self.trailing_max = price

        # Trail gap: 0.5% por defecto
        trail_gap = 0.005
        if price < self.trailing_max * (1 - trail_gap):
            return "TRAILING STOP"

        return None


# =====================================================================
# LOOP POR INSTRUMENTO
# =====================================================================

def process_instrument(
    symbol: str,
    state: InstrumentState,
    capital: float,
    params: dict,
) -> None:
    """Ejecuta un ciclo de análisis/decisión para un instrumento."""

    cfg = INSTRUMENTS[symbol]

    # Datos
    df = get_klines(symbol, 200)
    if df.empty or len(df) < 60:
        return

    df = compute_indicators(df)
    last = df.iloc[-1]
    price = last["close"]

    # ── GESTIÓN DE SALIDA ──────────────────────────────────────────
    if state.position_open:

        # Verificar que la posición sigue abierta en MT5
        pos = get_open_position(symbol)
        if pos is None:
            tg(f"⚠️ {symbol}: posición cerrada externamente")
            state.reset()
            return

        # 1. Vigilante
        vig = vigilante(df, True, state.entry_price)
        if vig["exit_signal"]:
            sold = market_sell(symbol, vig["reason"])
            if sold:
                equity_after = get_equity()
                pnl = equity_after - capital
                tg(
                    f"🔴 SELL {symbol}\n"
                    f"Motivo: {vig['reason']}\n"
                    f"Entrada: {state.entry_price:.4f}\n"
                    f"Salida: {price:.4f}\n"
                    f"Equity: €{equity_after:.2f}"
                )
                state.reset()
            return

        # 2. Trailing stop / SL
        reason = state.on_price(price)
        if reason:
            sold = market_sell(symbol, reason)
            if sold:
                equity_after = get_equity()
                tg(
                    f"🔴 SELL {symbol}\n"
                    f"Motivo: {reason}\n"
                    f"Entrada: {state.entry_price:.4f}\n"
                    f"Salida: {price:.4f}\n"
                    f"Equity: €{equity_after:.2f}"
                )
                state.reset()
        return

    rsi_val   = float(last.get("rsi", 0))
    stoch_val = float(last.get("stoch_k", 0))

    # ── COOLDOWN ──────────────────────────────────────────────────
    if state.last_exit and time.time() - state.last_exit < COOLDOWN_SECS:
        log_rechazo(symbol, "cooldown_post_salida", price, rsi_val, stoch_val)
        return

    # ── HUSMEADOR ─────────────────────────────────────────────────
    resultado = husmeador(df, params)
    if resultado is None:
        log_rechazo(symbol, "husmeador_none", price, rsi_val, stoch_val)
        return
    evento, evento_tipo = resultado
    if not evento:
        log_rechazo(symbol, f"husmeador_{evento_tipo}", price, rsi_val, stoch_val)
        return

    # ── SCORING ───────────────────────────────────────────────────
    # Calcular pendientes de EMAs (5 velas antes)
    ema_short_prev = float(df["ema_short"].iloc[-6]) if len(df) >= 6 else None
    ema_mid_prev   = float(df["ema_mid"].iloc[-6])   if len(df) >= 6 else None

    score_data = termometro(
        candle=last.to_dict(),
        ema_short=last["ema_short"],
        ema_mid=last["ema_mid"],
        rsi=last["rsi"],
        stoch_k=last["stoch_k"],
        stoch_d=last["stoch_d"],
        avg_volume=last["avg_volume"],
        ema_short_prev=ema_short_prev,
        ema_mid_prev=ema_mid_prev,
    )

    # ── CONTEXTO ──────────────────────────────────────────────────
    context = hombre_del_tiempo(
        candle_data=df,
        timeframe="5m",
        score=score_data["score"],
        score_reasons=score_data["score_reasons"],
    )

    space = compute_space(context.get("distance_to_resistance"), price)

    # ── DECISOR ───────────────────────────────────────────────────
    decision = decisor_35(
        evento_detectado=evento,
        score=score_data["score"],
        score_reasons=score_data["score_reasons"],
        context={
            "trend_bias":      context["bias"],
            "market_state":    context["market_state"],
            "trade_direction": "long",
            "space":           space,
        },
        timeframe="5m",
    )

    if not decision["allow_trade"]:
        log_rechazo(
            symbol,
            f"decisor_{decision['trade_category']}",
            price, rsi_val, stoch_val,
            score_data["score"], evento_tipo
        )
        return

    # ── ENTRADA ───────────────────────────────────────────────────
    lots = calcular_lotes(symbol, capital)
    order = market_buy(symbol, lots)
    if order is None:
        return

    state.position_open = True
    state.entry_price   = order["price"]
    state.entry_time    = datetime.now(TZ_SPAIN)
    state.sl_price      = order["sl"]
    state.lots          = order["volume"]
    state.trailing_max  = None

    tg(
        f"🟢 BUY {symbol} ({cfg['description']})\n"
        f"Precio: {order['price']:.4f}\n"
        f"Lotes: {order['volume']}\n"
        f"SL en: {order['sl']:.4f}\n"
        f"Score: {score_data['score']}\n"
        f"Evento: {evento_tipo}\n"
        f"Categoría: {decision['trade_category']}"
    )
    log_trade(symbol, "BUY", order["price"], order["volume"],
              score_data["score"], evento_tipo, decision["trade_category"])


# =====================================================================
# MAIN
# =====================================================================

def main():
    mt5_init()

    equity             = get_equity()
    equity_start_acct  = equity
    equity_start_day   = equity
    profit_acumulado   = 0.0
    current_day        = datetime.now(timezone.utc).date()

    # Estado independiente por instrumento
    states = {sym: InstrumentState(sym) for sym in INSTRUMENTS}

    # Recuperar posiciones abiertas si las hay
    for pos in get_all_open_positions():
        if pos.symbol in states:
            s = states[pos.symbol]
            s.position_open = True
            s.entry_price   = pos.price_open
            s.sl_price      = pos.sl if pos.sl > 0 else pos.price_open * 0.995
            s.lots          = pos.volume
            tg(f"⚠️ Posición recuperada: {pos.symbol} @ {pos.price_open:.4f}")

    params = HUSMEADOR_PARAMS["5m"]   # M5 — parámetros relajados para tecnológicas

    tg(
        f"🤖 TINGBOT NOCTORIAL ARRANCADO\n"
        f"Horario: {HORA_INICIO}:00–{HORA_FIN}:00 España\n"
        f"Capital: €{equity:.2f}\n"
        f"Objetivo: +€{PROFIT_TARGET:.0f}\n"
        f"Límite diario: -€{DAILY_LOSS_LIMIT:.0f}"
    )

    esperando_notificado = False

    while True:
        try:
            now_spain = datetime.now(TZ_SPAIN)

            # ── FUERA DE HORARIO ──────────────────────────────────
            if not dentro_de_horario():
                if not esperando_notificado:
                    mins = minutos_para_inicio()
                    if mins > 0:
                        tg(f"⏰ Fuera de horario. Arranco en ~{mins} min (17:00 España)")
                    else:
                        tg(f"⏰ Sesión finalizada. Hasta mañana a las {HORA_INICIO}:00")
                    esperando_notificado = True
                time.sleep(60)
                continue

            esperando_notificado = False

            # ── CIERRE FORZADO 21:55 ──────────────────────────────
            if es_hora_de_cierre():
                cerrar_todo("CIERRE_HORARIO_21:55")
                for s in states.values():
                    if s.position_open:
                        s.reset()
                resumen_diario()
                tg("🌙 Sesión cerrada. Bot en espera hasta mañana 17:00.")
                time.sleep(300)
                continue

            # ── KILL-SWITCH ───────────────────────────────────────
            equity_now = get_equity()
            profit_acumulado = equity_now - equity_start_acct

            ok, motivo, equity_start_day, current_day = kill_check(
                equity_now, equity_start_day, equity_start_acct,
                profit_acumulado, current_day
            )
            if not ok:
                cerrar_todo(motivo)
                tg(f"🛑 KILL SWITCH: {motivo}")
                break

            # ── PROCESAR CADA INSTRUMENTO ─────────────────────────
            for symbol, state in states.items():
                try:
                    process_instrument(symbol, state, equity_now, params)
                except Exception as e:
                    tg(f"⚠️ Error en {symbol}: {e}")

            # Esperar ~30 segundos antes del siguiente ciclo
            # (M5 = vela cada 5 min, pero revisamos más frecuente para trailing)
            time.sleep(30)

        except KeyboardInterrupt:
            cerrar_todo("STOP_MANUAL")
            tg("⛔ Bot detenido manualmente (Ctrl+C)")
            break

        except Exception as e:
            tg(f"⛔ ERROR CRÍTICO: {e}")
            import traceback
            print(traceback.format_exc())
            time.sleep(60)
            continue

    mt5.shutdown()
    tg(f"🔴 MT5 desconectado. Equity final: €{get_equity():.2f}")


if __name__ == "__main__":
    main()
