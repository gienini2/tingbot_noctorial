def decisor_35(
    evento_detectado: bool,
    score: int,
    score_reasons: list[str],
    context: dict,
    timeframe: str
) -> dict:
    """
    AGENTE 3.5 — DECISOR
    Implementación estricta según TABLA DE REGLAS NEGOCIADA.
    No heurísticas. No atajos. No categorías fuera de contrato.
    """

    decision_reason = []

    # =================================================
    # 0. HARD STOP — sin evento no hay trade
    # =================================================
    if not evento_detectado:
        return {
            "allow_trade": False,
            "decision_type": "veto",
            "trade_category": "low_quality_chop",
            "decision_reason": ["evento no detectado"]
        }

    decision_reason.append("evento confirmado")

    # =================================================
    # 1. Clasificación del score
    # =================================================
    if score < 40:
        score_level = "low"
        decision_reason.append("score bajo")
    elif score < 65:
        score_level = "medium"
        decision_reason.append("score medio")
    else:
        score_level = "high"
        decision_reason.append("score alto")

    # =================================================
    # 2. Lectura de contexto (Agente 3)
    # =================================================
    trend_bias = context.get("trend_bias")         # bullish | bearish | neutral
    market_state = context.get("market_state")     # trending | ranging | transitional
    trade_direction = context.get("trade_direction")  # long | short
    space = context.get("space")                   # much | sufficient | little

    # --- 2.1 Alineación direccional ---
    if trend_bias == "neutral":
        alignment = "neutral"
        decision_reason.append("contexto neutral")
    elif (trend_bias == "bullish" and trade_direction == "long") or \
         (trend_bias == "bearish" and trade_direction == "short"):
        alignment = "with"
        decision_reason.append("contexto a favor")
    else:
        alignment = "against"
        decision_reason.append("contexto en contra")

    # --- 2.2 Estado de mercado ---
    if market_state:
        decision_reason.append(f"mercado {market_state}")

    # =================================================
    # 3. Regla de espacio
    # =================================================
    if space == "little":
        space_state = "little"
        decision_reason.append("espacio limitado")
    elif space in ("much", "sufficient"):
        space_state = "enough"
        decision_reason.append("espacio suficiente")
    else:
        space_state = "unknown"

    # =================================================
    # 4. DECISIÓN COMBINADA — TABLA PURA
    # =================================================
    allow_trade = False
    decision_type = "veto"
    trade_category = "low_quality_chop"

    # -------------------------------
    # SCORE ALTO (65–100)
    # -------------------------------
    if score_level == "high":

        if alignment == "with":

            if space_state == "enough":
                allow_trade = True
                decision_type = "allow"
                trade_category = "continuation_clean"

            else:
                allow_trade = False
                decision_type = "veto"
                trade_category = "low_space_breakout"
        elif alignment == "neutral":
            if space_state == "enough":
                allow_trade = True
                decision_type = "allow"
                trade_category = "continuation_clean"
            else:
                allow_trade = True
                decision_type = "allow_with_conditions"
                trade_category = "continuation_near_sr"

        elif alignment == "against":
            if space_state == "enough":
                allow_trade = True
                decision_type = "allow_with_conditions"
                trade_category = "countertrend_high_quality"
            else:
                allow_trade = False
                decision_type = "veto"
                trade_category = "low_quality_chop"

    # -------------------------------
    # SCORE MEDIO (40–64)
    # -------------------------------
    elif score_level == "medium":

            if alignment == "with" and space_state == "enough":
                allow_trade = True
                decision_type = "allow_with_conditions"
                trade_category = "pullback_with_context"

            else:
                allow_trade = False
                decision_type = "veto"
                trade_category = "low_quality_chop"    

    # -------------------------------
    # SCORE BAJO (0–39)
    # -------------------------------
    elif score_level == "low":

        if alignment == "with" and space == "much":
            allow_trade = False
            decision_type = "veto"
            trade_category = "experimental_low_score"
            decision_reason.append("trade experimental declarado")
        else:
            allow_trade = False
            decision_type = "veto"
            trade_category = "low_quality_chop"

   # =================================================
    # 5. OUTPUT OBLIGATORIO
    # =================================================
    return {
            "allow_trade": allow_trade,
            "decision_type": decision_type,
            "trade_category": trade_category,
            "decision_reason": decision_reason
       }