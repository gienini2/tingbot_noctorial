HUSMEADOR_PARAMS = {
    "1m": {
        "lookback": 20,
        "vol_ratio": 1.3,          # volumen mínimo para entrar (era 1.2, subimos exigencia)
        "range_expansion": 1.3,
        "breakout_buffer": 0.0008,
        "stoch_max": 35,           # estocástico máximo para considerar entrada (zona baja)
        "engulf_body_ratio": 0.6,  # cuerpo mínimo de la vela envolvente (60% del rango)
    }
}


def husmeador(df, params):

    if len(df) < params["lookback"]:
        return False, "not_enough_data"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    vol_ratio       = params["vol_ratio"]
    range_expansion = params["range_expansion"]
    breakout_buffer = params["breakout_buffer"]
    stoch_max       = params["stoch_max"]
    engulf_ratio    = params["engulf_body_ratio"]

    # =============================
    # 1. VOLUMEN ALTO — FILTRO DURO
    # =============================
    avg_vol = df["volume"].iloc[-20:].mean()

    if last["volume"] < avg_vol * vol_ratio:
        return False, "no_volume"

    # =============================
    # 2. ESTOCÁSTICO BAJO — FILTRO DURO
    # Queremos entrar en zona de sobreventa, no sobrecompra
    # =============================
    stoch_k = df["stoch_k"].iloc[-1] if "stoch_k" in df.columns else None

    if stoch_k is not None and stoch_k > stoch_max:
        return False, "stoch_too_high"

    # =============================
    # 3. VELA ENVOLVENTE ALCISTA
    # La vela actual cierra por encima de la apertura anterior
    # y tiene cuerpo sólido (no mecha dominante)
    # =============================
    last_body  = last["close"] - last["open"]
    last_range = last["high"] - last["low"]
    body_ratio = last_body / last_range if last_range > 0 else 0

    es_alcista   = last["close"] > last["open"]                  # vela verde
    es_envolvente = last["close"] > prev["open"] and \
                    last["open"]  < prev["close"]                 # engulle la anterior
    cuerpo_solido = body_ratio >= engulf_ratio                    # cuerpo limpio

    if es_alcista and es_envolvente and cuerpo_solido:
        return True, "engulfing_bullish"

    # =============================
    # 4. EXPANSIÓN DE VOLATILIDAD
    # =============================
    avg_range = (
        df["high"].iloc[-20:] -
        df["low"].iloc[-20:]
    ).mean()

    if last_range < avg_range * range_expansion:
        return False, "no_range_expansion"

    # =============================
    # 5. MICRO BREAKOUT
    # =============================
    prev_high = df["high"].iloc[-5:-1].max()

    if last["close"] > prev_high * (1 + breakout_buffer):
        return True, "momentum_breakout"

    # =============================
    # 6. PULLBACK EN TENDENCIA
    # =============================
    ema_short = df["ema_short"].iloc[-1]
    ema_mid   = df["ema_mid"].iloc[-1]

    if ema_short > ema_mid:
        if prev["low"] < ema_short and last["close"] > ema_short:
            distance = abs(last["close"] - ema_short) / ema_short
            if distance > 0.002:
                return False, "pullback_too_extended"
            return True, "ema_pullback"

    return False, "no_event_fallback"
