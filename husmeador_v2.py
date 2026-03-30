"""
husmeador_v2.py — Detector de eventos v2
=========================================
v2.1: vol_ratio=0.0 (CFDs MT5), oversold_bounce, SIN función duplicada
"""

HUSMEADOR_PARAMS = {
    "1m": {
        "lookback":          20,
        "vol_ratio":         1.3,
        "range_expansion":   1.3,
        "breakout_buffer":   0.0008,
        "stoch_max":         35,
        "engulf_body_ratio": 0.6,
    },
    "5m": {
        "lookback":          20,
        "vol_ratio":         0.0,
        "range_expansion":   1.10,
        "breakout_buffer":   0.0005,
        "stoch_max":         55,
        "engulf_body_ratio": 0.50,
        "oversold_rsi":      25,
        "oversold_stoch":    15,
    }
}


def husmeador(df, params):

    if len(df) < params["lookback"]:
        return False, "not_enough_data"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    vol_ratio       = params.get("vol_ratio", 0.0)
    range_expansion = params["range_expansion"]
    breakout_buffer = params["breakout_buffer"]
    stoch_max       = params["stoch_max"]
    engulf_ratio    = params["engulf_body_ratio"]
    oversold_rsi    = params.get("oversold_rsi", 25)
    oversold_stoch  = params.get("oversold_stoch", 15)

    avg_vol = df["volume"].iloc[-20:].mean()

    # 0. SOBREVENTA EXTREMA
    rsi_val   = df["rsi"].iloc[-1]     if "rsi"     in df.columns else 50
    stoch_val = df["stoch_k"].iloc[-1] if "stoch_k" in df.columns else 50

    if rsi_val < oversold_rsi and stoch_val < oversold_stoch:
        if last["close"] > last["open"]:
            return True, "oversold_bounce"

    # 1. VOLUMEN — desactivado si vol_ratio=0.0
    if vol_ratio > 0.0:
        if last["volume"] < avg_vol * vol_ratio:
            return False, "no_volume"

    # 2. ESTOCÁSTICO
    stoch_k = df["stoch_k"].iloc[-1] if "stoch_k" in df.columns else None
    if stoch_k is not None and stoch_k > stoch_max:
        return False, "stoch_too_high"

    # 3. VELA ENVOLVENTE ALCISTA
    last_body  = last["close"] - last["open"]
    last_range = last["high"]  - last["low"]
    body_ratio = last_body / last_range if last_range > 0 else 0

    es_alcista    = last["close"] > last["open"]
    es_envolvente = last["close"] > prev["open"] and \
                    last["open"]  < prev["close"]
    cuerpo_solido = body_ratio >= engulf_ratio

    if es_alcista and es_envolvente and cuerpo_solido:
        return True, "engulfing_bullish"

    # 4. EXPANSIÓN DE VOLATILIDAD
    avg_range = (
        df["high"].iloc[-20:] -
        df["low"].iloc[-20:]
    ).mean()

    if last_range < avg_range * range_expansion:
        return False, "no_range_expansion"

    # 5. MICRO BREAKOUT
    prev_high = df["high"].iloc[-5:-1].max()
    if last["close"] > prev_high * (1 + breakout_buffer):
        return True, "momentum_breakout"

    # 6. PULLBACK EN TENDENCIA
    ema_short = df["ema_short"].iloc[-1]
    ema_mid   = df["ema_mid"].iloc[-1]

    if ema_short > ema_mid:
        if prev["low"] < ema_short and last["close"] > ema_short:
            distance = abs(last["close"] - ema_short) / ema_short
            if distance > 0.004:
                return False, "pullback_too_extended"
            return True, "ema_pullback"

    return False, "no_event_fallback"
