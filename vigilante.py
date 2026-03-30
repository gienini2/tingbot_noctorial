"""
VIGILANTE — Agente de salida por indicadores

Complementa al trailing stop y al stop loss.
Sale cuando el impulso se agota, antes de que el precio retroceda.

Lógica:
  - Si volumen cae significativamente → agotamiento
  - Si RSI + Estocástico altos y empiezan a bajar → techo
  - Si los dos coinciden → salida inmediata
  - Si solo uno → warning (no sale solo)
"""


def vigilante(df, position_open: bool, entry_price: float = None):
    """
    df: DataFrame con columnas -> close, volume, rsi, stoch_k, stoch_d, avg_volume
    position_open: bool
    entry_price: float — precio de entrada de la posición actual

    Retorna:
        {
            "exit_signal": bool,
            "reason": str,
            "strength": "strong" | "weak" | "none"
        }
    """

    if not position_open or len(df) < 5:
        return {"exit_signal": False, "reason": "no_position", "strength": "none"}

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    prev2 = df.iloc[-3]

    signals = []

    # =============================
    # 1. VOLUMEN CAYENDO
    # Comparamos las últimas 3 velas con la media
    # =============================
    avg_vol     = df["volume"].iloc[-20:].mean()
    vol_now     = last["volume"]
    vol_prev    = prev["volume"]

    # Vela actual en rojo (bajista)
    vela_roja = last["close"] < last["open"]

    # Volumen actual por debajo del 70% de la media
    vol_bajo = vol_now < avg_vol * 0.7

    # Volumen cayendo 2 velas seguidas
    vol_cayendo = vol_now < vol_prev < df["volume"].iloc[-3]

    if vela_roja and vol_bajo:
        signals.append("volumen_bajo_vela_roja")

    if vol_cayendo and vela_roja:
        signals.append("volumen_decreciente")

    # =============================
    # 2. RSI ALTO Y GIRANDO
    # =============================
    rsi_now  = last.get("rsi", 50)
    rsi_prev = prev.get("rsi", 50)

    rsi_alto   = rsi_now > 72
    rsi_girando = rsi_now < rsi_prev and rsi_prev > 70  # bajó desde zona alta

    if rsi_alto and rsi_girando:
        signals.append("rsi_giro_bajista")
    elif rsi_now > 80:
        signals.append("rsi_extremo")

    # =============================
    # 3. ESTOCÁSTICO ALTO Y GIRANDO
    # =============================
    stoch_k_now  = last.get("stoch_k", 50)
    stoch_d_now  = last.get("stoch_d", 50)
    stoch_k_prev = prev.get("stoch_k", 50)

    stoch_alto   = stoch_k_now > 75
    stoch_girando = stoch_k_now < stoch_k_prev and stoch_k_prev > 75
    stoch_cruce  = stoch_k_now < stoch_d_now and stoch_k_prev >= prev.get("stoch_d", 50)

    if stoch_alto and stoch_girando:
        signals.append("stoch_giro_bajista")
    if stoch_cruce and stoch_k_now > 70:
        signals.append("stoch_cruce_bajista_alto")

    # =============================
    # 4. EVALUACIÓN COMBINADA
    # =============================

    # Señal fuerte: volumen + indicador de momentum
    vol_signals   = [s for s in signals if "volumen" in s]
    mom_signals   = [s for s in signals if s not in vol_signals]

    if vol_signals and mom_signals:
        return {
            "exit_signal": True,
            "reason": f"IMPULSO_AGOTADO ({', '.join(signals)})",
            "strength": "strong"
        }

    # Señal media: dos señales de cualquier tipo
    if len(signals) >= 2:
        return {
            "exit_signal": True,
            "reason": f"SEÑALES_MULTIPLES ({', '.join(signals)})",
            "strength": "strong"
        }

    # Señal débil: una sola señal — no sale, solo avisa
    if len(signals) == 1:
        return {
            "exit_signal": False,
            "reason": f"WARNING ({signals[0]})",
            "strength": "weak"
        }

    # Sin señales — mantener posición
    return {
        "exit_signal": False,
        "reason": "impulso_activo",
        "strength": "none"
    }
