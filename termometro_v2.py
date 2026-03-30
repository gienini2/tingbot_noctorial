"""
termometro_v2.py — Scoring de calidad de señal v2
===================================================
Cambios respecto a v1:
  - Añadido bonus/penalización por pendiente de EMAs
    · EMAs ascendentes → +10 puntos (momentum real)
    · EMAs planas      →   0 puntos (neutral)
    · EMAs bajistas    →  -8 puntos (penaliza pero NO bloquea)
  - Score mínimo efectivo rebajado por el decisor_35 (de 40 a 35)
  - Añadido parámetro ema_short_prev y ema_mid_prev para calcular pendiente
"""


def clamp(value, min_v=0, max_v=100):
    return max(min_v, min(value, max_v))


def termometro(
    candle,
    ema_short,
    ema_mid,
    rsi,
    stoch_k,
    stoch_d,
    avg_volume,
    ema_short_prev=None,   # NUEVO — valor de EMA corta 5 velas antes
    ema_mid_prev=None,     # NUEVO — valor de EMA media 5 velas antes
):
    """
    candle:         dict con keys -> open, high, low, close, volume
    ema_short:      float — EMA 20 actual
    ema_mid:        float — EMA 50 actual
    rsi:            float
    stoch_k:        float
    stoch_d:        float
    avg_volume:     float
    ema_short_prev: float — EMA 20 hace 5 velas (para calcular pendiente)
    ema_mid_prev:   float — EMA 50 hace 5 velas (para calcular pendiente)
    """

    score = 50
    reasons = []

    price  = candle["close"]
    volume = candle["volume"]

    body        = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]
    body_ratio  = body / candle_range if candle_range > 0 else 0

    # ---------------------------------
    # 1. ESTRUCTURA — EMAs (peso alto)
    # ---------------------------------
    if price > ema_short and ema_short > ema_mid:
        score += 10
        reasons.append("Precio sostenido sobre EMAs")
    else:
        score -= 10
        reasons.append("Estructura EMA desordenada")

    # Precio demasiado estirado
    if abs(price - ema_short) / ema_short > 0.003:
        score -= 5
        reasons.append("Precio estirado respecto a EMA")

    # ---------------------------------
    # 2. PENDIENTE DE EMAs — NUEVO
    # Bonus si ambas EMAs son ascendentes
    # Penalización si son bajistas (no bloquea)
    # ---------------------------------
    if ema_short_prev is not None and ema_mid_prev is not None:
        short_ascendente = ema_short > ema_short_prev
        mid_ascendente   = ema_mid   > ema_mid_prev

        if short_ascendente and mid_ascendente:
            score += 10
            reasons.append("EMAs ascendentes — momentum alcista")
        elif not short_ascendente and not mid_ascendente:
            score -= 8
            reasons.append("EMAs bajistas — penalización (no bloqueo)")
        else:
            # Una sube y otra no — mercado indeciso
            reasons.append("EMAs mixtas — contexto indeciso")
    else:
        # Sin datos previos — no puntúa ni penaliza
        reasons.append("Pendiente EMA no disponible")

    # ---------------------------------
    # 3. TIMING — RSI
    # ---------------------------------
    if rsi < 30:
        score += 10
        reasons.append("RSI en sobreventa — zona óptima de entrada")
    elif rsi < 45:
        score += 5
        reasons.append("RSI rebote saludable")
    elif rsi > 70:
        reasons.append("RSI elevado — contexto de sobrecompra")

    if rsi < 15:
        score -= 5
        reasons.append("RSI demasiado débil — posible colapso")

    # ---------------------------------
    # 4. CONFIRMACIÓN — ESTOCÁSTICO
    # ---------------------------------
    if stoch_k < 20 and stoch_k > stoch_d:
        score += 5
        reasons.append("Estocástico bajo con cruce alcista")
    elif stoch_k > 80 and abs(stoch_k - stoch_d) < 3:
        score -= 5
        reasons.append("Estocástico en zona extrema alta")

    # ---------------------------------
    # 5. VOLUMEN — CALIDAD
    # ---------------------------------
    if volume > avg_volume * 1.3 and body_ratio > 0.6:
        score += 10
        reasons.append("Volumen alto con vela limpia")
    elif volume > avg_volume * 1.2 and body_ratio > 0.6:
        score += 5
        reasons.append("Volumen acompaña con cierre limpio")

    if volume > avg_volume * 2 and body_ratio < 0.3:
        score -= 5
        reasons.append("Volumen alto sin desplazamiento real")

    # ---------------------------------
    # NORMALIZACIÓN FINAL
    # ---------------------------------
    score   = int(clamp(score))
    reasons = reasons[:5]

    return {
        "score": score,
        "score_reasons": reasons
    }
