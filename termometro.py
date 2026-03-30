def clamp(value, min_v=0, max_v=100):
    return max(min_v, min(value, max_v))


def termometro(
    candle,
    ema_short,
    ema_mid,
    rsi,
    stoch_k,
    stoch_d,
    avg_volume
):
    """
    candle: dict con keys -> open, high, low, close, volume
    ema_short: float
    ema_mid: float
    rsi: float
    stoch_k: float
    stoch_d: float
    avg_volume: float
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
    # 2. TIMING — RSI
    # Lógica nueva: premiamos RSI bajo (zona de entrada)
    # NO penalizamos RSI alto (eso lo filtra el husmeador)
    # ---------------------------------

    # RSI zona óptima de entrada (rebote desde sobreventa)
    if rsi < 30:
        score += 10
        reasons.append("RSI en sobreventa — zona óptima de entrada")
    elif rsi < 45:
        score += 5
        reasons.append("RSI rebote saludable")
    elif rsi > 70:
        # Ya no penalizamos — el husmeador filtra estocástico alto
        # pero sí lo anotamos como contexto
        reasons.append("RSI elevado — contexto de sobrecompra")

    # RSI demasiado débil (colapso, no rebote)
    if rsi < 15:
        score -= 5
        reasons.append("RSI demasiado débil — posible colapso")

    # ---------------------------------
    # 3. CONFIRMACIÓN — ESTOCÁSTICO
    # Premiamos estocástico bajo (alineado con nueva lógica)
    # ---------------------------------
    if stoch_k < 20 and stoch_k > stoch_d:
        score += 5
        reasons.append("Estocástico bajo con cruce alcista")
    elif stoch_k > 80 and abs(stoch_k - stoch_d) < 3:
        score -= 5
        reasons.append("Estocástico en zona extrema alta")

    # ---------------------------------
    # 4. VOLUMEN — CALIDAD
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
