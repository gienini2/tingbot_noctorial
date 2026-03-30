"""
Hombre_del_tiempo.py — Agente 3 — Contexto de mercado
=======================================================
v2: Niveles S/R precisos + escenarios alcista/bajista
    Inspirado en análisis tipo Tradeando:
      - Zonas tocadas múltiples veces (no teóricas)
      - Escenario principal + escenario alternativo
      - Distancia al nivel más próximo en %
      - Calidad del nivel (nº de toques)
"""

import pandas as pd
import numpy as np


# =====================================================================
# 1. EMA
# =====================================================================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


# =====================================================================
# 2. SWING HIGHS / LOWS con conteo de calidad
# =====================================================================
def detect_swings(df: pd.DataFrame, lookback: int = 4):
    """
    Devuelve lista de (índice, precio, n_toques)
    n_toques: cuántas velas posteriores han retestado esa zona (+/- 0.3%)
    """
    highs = df["high"].values
    lows  = df["low"].values
    closes = df["close"].values

    swing_highs = []
    swing_lows  = []

    tolerance = 0.003  # 0.3% — zona de retesteo

    for i in range(lookback, len(df) - lookback):
        # Swing high
        if highs[i] == max(highs[i - lookback:i + lookback + 1]):
            # Contar cuántas velas posteriores han llegado a esa zona
            zona = highs[i]
            toques = sum(
                1 for j in range(i + 1, len(df))
                if abs(highs[j] - zona) / zona < tolerance
                or abs(lows[j] - zona) / zona < tolerance
            )
            swing_highs.append((i, round(highs[i], 4), toques))

        # Swing low
        if lows[i] == min(lows[i - lookback:i + lookback + 1]):
            zona = lows[i]
            toques = sum(
                1 for j in range(i + 1, len(df))
                if abs(highs[j] - zona) / zona < tolerance
                or abs(lows[j] - zona) / zona < tolerance
            )
            swing_lows.append((i, round(lows[i], 4), toques))

    return swing_highs, swing_lows


# =====================================================================
# 3. CLUSTERIZAR NIVELES CERCANOS
# =====================================================================
def cluster_levels(niveles, tolerance_pct=0.003):
    """
    Agrupa niveles dentro del tolerance_pct en uno solo.
    Devuelve lista de (precio_medio, toques_totales)
    """
    if not niveles:
        return []

    # Ordenar por precio
    niveles_sorted = sorted(niveles, key=lambda x: x[0])
    clusters = [[niveles_sorted[0]]]

    for precio, toques in niveles_sorted[1:]:
        ref = clusters[-1][-1][0]
        if abs(precio - ref) / ref < tolerance_pct:
            clusters[-1].append((precio, toques))
        else:
            clusters.append([(precio, toques)])

    resultado = []
    for cluster in clusters:
        precio_medio = round(np.mean([c[0] for c in cluster]), 4)
        toques_total = sum(c[1] for c in cluster)
        resultado.append((precio_medio, toques_total))

    return resultado


# =====================================================================
# 4. ESTADO DE MERCADO
# =====================================================================
def evaluate_market_state(df: pd.DataFrame):
    df = df.copy()
    df["ema50"]  = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)

    price    = df["close"].iloc[-1]
    ema50    = df["ema50"].iloc[-1]
    ema200   = df["ema200"].iloc[-1]
    slope50  = df["ema50"].iloc[-1]  - df["ema50"].iloc[-5]
    slope200 = df["ema200"].iloc[-1] - df["ema200"].iloc[-10]

    swing_highs, swing_lows = detect_swings(df)

    market_state = "ranging"
    bias = "neutral"

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        last_highs = [(h[1], h[2]) for h in swing_highs[-2:]]
        last_lows  = [(l[1], l[2]) for l in swing_lows[-2:]]

        higher_lows  = last_lows[1][0]  > last_lows[0][0]
        lower_highs  = last_highs[1][0] < last_highs[0][0]
        higher_highs = last_highs[1][0] > last_highs[0][0]

        if price > ema50 > ema200 and higher_lows and higher_highs and slope50 > 0:
            market_state = "trending"
            bias = "bullish"
        elif price < ema50 < ema200 and lower_highs and not higher_lows and slope50 < 0:
            market_state = "trending"
            bias = "bearish"
        elif price > ema50 and slope50 > 0:
            market_state = "transitional"
            bias = "bullish"
        elif price < ema50 and slope50 < 0:
            market_state = "transitional"
            bias = "bearish"
        else:
            market_state = "ranging"

    return market_state, bias


# =====================================================================
# 5. S/R PRECISOS CON CALIDAD
# =====================================================================
def find_support_resistance(df: pd.DataFrame, window: int = 150):
    """
    Devuelve los 3 soportes y 3 resistencias más relevantes
    con su número de toques (calidad del nivel).
    Formato: [(precio, toques), ...]
    """
    recent = df.tail(window)
    swing_highs, swing_lows = detect_swings(recent, lookback=4)

    # Extraer precios y toques
    res_raw = [(h[1], h[2]) for h in swing_highs]
    sup_raw = [(l[1], l[2]) for l in swing_lows]

    # Clusterizar
    resistencias = cluster_levels(res_raw, tolerance_pct=0.004)
    soportes     = cluster_levels(sup_raw, tolerance_pct=0.004)

    price = df["close"].iloc[-1]

    # Filtrar: soportes por debajo del precio, resistencias por encima
    soportes     = [(p, t) for p, t in soportes     if p < price]
    resistencias = [(p, t) for p, t in resistencias if p > price]

    # Ordenar: soportes desc (el más cercano primero), res asc
    soportes     = sorted(soportes,     key=lambda x: -x[0])[:3]
    resistencias = sorted(resistencias, key=lambda x:  x[0])[:3]

    return soportes, resistencias


# =====================================================================
# 6. ESCENARIOS ALCISTA / BAJISTA
# =====================================================================
def build_scenarios(price, soportes, resistencias, bias):
    """
    Construye escenarios estilo Tradeando:
      - Principal: coherente con el bias
      - Alternativo: escenario contrario con invalidación
    """
    s1 = soportes[0][0]     if soportes     else None
    r1 = resistencias[0][0] if resistencias else None

    distancia_r = round(((r1 - price) / price) * 100, 2) if r1 else None
    distancia_s = round(((price - s1) / price) * 100, 2) if s1 else None

    escenario_alcista = {}
    escenario_bajista = {}

    if bias in ("bullish", "neutral"):
        if s1 and r1:
            escenario_alcista = {
                "descripcion": f"Pullback a {s1} y rebote hacia {r1}",
                "entrada":     f"Rebote en {s1} con confirmación vela",
                "objetivo":    r1,
                "invalidacion": round(s1 * 0.997, 4),
                "distancia_objetivo_pct": distancia_r,
            }
        elif r1:
            escenario_alcista = {
                "descripcion":  f"Continuación alcista hacia {r1}",
                "entrada":      "En zona actual con momentum",
                "objetivo":     r1,
                "invalidacion": s1 if s1 else "—",
                "distancia_objetivo_pct": distancia_r,
            }

    if bias in ("bearish", "neutral"):
        if r1 and s1:
            escenario_bajista = {
                "descripcion":  f"Rechazo en {r1} hacia {s1}",
                "entrada":      f"Rechazo en {r1} con vela bajista",
                "objetivo":     s1,
                "invalidacion": round(r1 * 1.003, 4),
                "distancia_objetivo_pct": distancia_s,
            }

    return escenario_alcista, escenario_bajista


# =====================================================================
# 7. FUNCIÓN PRINCIPAL — API pública del agente
# =====================================================================
def hombre_del_tiempo(
    candle_data: pd.DataFrame,
    timeframe: str,
    score: int,
    score_reasons: list,
    memoria_contextual: dict | None = None
):
    df = candle_data.copy()

    market_state, bias = evaluate_market_state(df)
    soportes, resistencias = find_support_resistance(df)

    price = df["close"].iloc[-1]

    # Niveles más próximos
    nearest_support    = soportes[0][0]     if soportes     else None
    nearest_resistance = resistencias[0][0] if resistencias else None
    support_quality    = soportes[0][1]     if soportes     else 0
    resistance_quality = resistencias[0][1] if resistencias else 0

    dist_support    = round(abs(price - nearest_support)    / price * 100, 2) if nearest_support    else None
    dist_resistance = round(abs(nearest_resistance - price) / price * 100, 2) if nearest_resistance else None

    # Escenarios
    escenario_alcista, escenario_bajista = build_scenarios(
        price, soportes, resistencias, bias
    )

    # Notas de contexto
    context_notes = []
    if nearest_support:
        context_notes.append(
            f"soporte más cercano: {nearest_support} ({dist_support}% abajo, {support_quality} toques)"
        )
    if nearest_resistance:
        context_notes.append(
            f"resistencia más cercana: {nearest_resistance} ({dist_resistance}% arriba, {resistance_quality} toques)"
        )
    if memoria_contextual:
        context_notes.append("memoria contextual externa presente")

    return {
        # Estado
        "market_state":          market_state,
        "bias":                  bias,

        # S/R básicos (compatibilidad con runner actual)
        "nearest_support":       nearest_support,
        "nearest_resistance":    nearest_resistance,
        "distance_to_support":   abs(price - nearest_support)    if nearest_support    else None,
        "distance_to_resistance": abs(nearest_resistance - price) if nearest_resistance else None,

        # S/R completos con calidad
        "soportes":              soportes,       # [(precio, toques), ...]
        "resistencias":          resistencias,   # [(precio, toques), ...]
        "support_quality":       support_quality,
        "resistance_quality":    resistance_quality,

        # Escenarios
        "escenario_alcista":     escenario_alcista,
        "escenario_bajista":     escenario_bajista,

        # Notas
        "context_notes":         context_notes,
    }
