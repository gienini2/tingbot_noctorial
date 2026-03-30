import json
import os
from datetime import datetime, timezone

TRADE_LOG_FILE = "trades_log.jsonl"
CAPITAL_FILE   = "capital_state.json"

STOP_LOSS_PCT = 0.003
TP_PCT        = [0.008, 0.015]

WARNING_DD   = 0.03
EMERGENCY_DD = 0.05

# Trailing adaptativo
TRAIL_ACTIVATION_ATR = 1.0
TRAIL_GAP_ATR        = 1.5
TRAIL_MIN_PCT        = 0.004
TRAIL_MAX_PCT        = 0.025
MIN_TARGET_PCT       = 0.01   # target mínimo 1% antes de activar trailing


def load_capital_state(initial_capital: float):
    if not os.path.exists(CAPITAL_FILE):
        state = {
            "initial_capital":   initial_capital,
            "current_capital":   initial_capital,
            "max_capital":       initial_capital,
            "trades":            0,
            "wins":              0,
            "losses":            0,
            "max_drawdown_pct":  0.0,
            "last_update":       None,
        }
        with open(CAPITAL_FILE, "w") as f:
            json.dump(state, f, indent=2)
        return state

    with open(CAPITAL_FILE) as f:
        return json.load(f)


def save_capital_state(state):
    with open(CAPITAL_FILE, "w") as f:
        json.dump(state, f, indent=2)


class Agent4ExitManager:

    def __init__(self, initial_capital, telegram_sender=None):
        self.telegram       = telegram_sender
        self.state          = load_capital_state(initial_capital)
        self.position_open  = False
        self.entry_price    = None
        self.entry_time     = None
        self.trailing_price = None
        self.trail_gap_pct  = TRAIL_MIN_PCT
        self.atr            = None
        self.symbol         = "BTCUSDC"
        self.size           = None

    # --------------------------------
    # OPEN POSITION
    # --------------------------------

    def open_position(self, entry_price: float, atr: float = None,
                      allow_trailing=True, size=None):
        self.entry_price    = entry_price
        self.entry_time     = datetime.now(timezone.utc).isoformat()
        self.trailing_price = None
        self.position_open  = True
        self.size           = size
        self.atr            = atr

        # Calcular gap del trailing según ATR
        if atr and entry_price > 0:
            atr_pct = atr / entry_price
            self.trail_gap_pct = max(
                TRAIL_MIN_PCT,
                min(atr_pct * TRAIL_GAP_ATR, TRAIL_MAX_PCT)
            )
        else:
            self.trail_gap_pct = TRAIL_MIN_PCT

        self.sl_price  = entry_price * (1 - STOP_LOSS_PCT)
        self.tp_prices = [entry_price * (1 + p) for p in TP_PCT]

        # FIX ENTRADA: registrar apertura en trades_log
        self._log_open()

    # --------------------------------
    # LOG APERTURA
    # --------------------------------

    def _log_open(self):
        """Registra la apertura del trade en el log para tener el ciclo completo."""
        entry_record = {
            "type":            "open",
            "timestamp_entry": self.entry_time,
            "symbol":          self.symbol,
            "entry_price":     self.entry_price,
            "size":            self.size,
            "sl_price":        self.sl_price,
            "trail_gap_pct":   self.trail_gap_pct,
            "equity_before":   self.state["current_capital"],
        }
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(entry_record) + "\n")

    # --------------------------------
    # PRICE UPDATE
    # --------------------------------

    def on_price_update(self, price: float):
        if not self.position_open:
            return None

        # Stop loss fijo
        if price <= self.sl_price:
            return self._close_trade(price, "STOP LOSS")

        # Take profit máximo — no cierra, activa trailing
        if price >= self.tp_prices[-1]:
            if self.trailing_price is None:
                self.trailing_price = price
            if price > self.trailing_price:
                self.trailing_price = price
            return None

        # Activar trailing cuando precio supera target mínimo 1%
        if self.trailing_price is None:
            if price >= self.entry_price * (1 + MIN_TARGET_PCT):
                self.trailing_price = price
            return None

        # Trailing activo — actualizar máximo
        if price > self.trailing_price:
            self.trailing_price = price
        elif price < self.trailing_price * (1 - self.trail_gap_pct):
            return self._close_trade(price, "TRAILING STOP")

        return None

    # --------------------------------
    # CLOSE TRADE
    # --------------------------------

    def _close_trade(self, exit_price: float, reason: str):
        pnl_pct = (exit_price - self.entry_price) / self.entry_price

        self._update_capital(pnl_pct)

        pnl_usdc = pnl_pct * self.state["current_capital"]

        trade = {
            "type":             "close",
            "timestamp_entry":  self.entry_time,
            "timestamp_exit":   datetime.now(timezone.utc).isoformat(),
            "symbol":           self.symbol,
            "entry_price":      self.entry_price,
            "exit_price":       exit_price,
            "size":             self.size,
            "pnl_pct":          pnl_pct,
            "pnl_usdc":         pnl_usdc,
            "reason":           reason,
            "trail_gap_pct":    self.trail_gap_pct,
            "equity_after":     self.state["current_capital"],
        }

        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(trade) + "\n")

        save_capital_state(self.state)

        self.position_open  = False
        self.entry_price    = None
        self.trailing_price = None
        self.entry_time     = None
        self.size           = None
        self.atr            = None

        self._send_report(pnl_pct, reason)

        return trade

    # --------------------------------
    # UPDATE CAPITAL
    # --------------------------------

    def _update_capital(self, pnl_pct):
        self.state["trades"] += 1

        if pnl_pct > 0:
            self.state["wins"] += 1
        else:
            self.state["losses"] += 1

        self.state["current_capital"] *= (1 + pnl_pct)
        self.state["max_capital"] = max(
            self.state["max_capital"],
            self.state["current_capital"],
        )

        dd = (
            self.state["max_capital"] - self.state["current_capital"]
        ) / self.state["max_capital"]

        self.state["max_drawdown_pct"] = max(
            self.state["max_drawdown_pct"], dd
        )
        self.state["last_update"] = datetime.now(timezone.utc).isoformat()

    # --------------------------------
    # TELEGRAM REPORT — VENTA COMPLETA
    # --------------------------------

    def _send_report(self, pnl_pct, reason):
        status = "🟢 OPERATIVO"
        if self.state["max_drawdown_pct"] >= EMERGENCY_DD:
            status = "🔴 STOP RECOMENDADO"
        elif self.state["max_drawdown_pct"] >= WARNING_DD:
            status = "⚠️ WARNING"

        # FIX VENTA: incluir saldo real actualizado en el mensaje
        msg = (
            f"📤 TRADE CERRADO\n\n"
            f"Motivo: {reason}\n"
            f"Resultado: {pnl_pct*100:.2f}%\n"
            f"Trail gap usado: {self.trail_gap_pct*100:.2f}%\n"
            f"Capital bot: {self.state['current_capital']:.2f}\n"
            f"Trades: {self.state['trades']} "
            f"(W:{self.state['wins']} / L:{self.state['losses']})\n"
            f"Max DD: -{self.state['max_drawdown_pct']*100:.2f}%\n\n"
            f"Estado: {status}"
        )

        if self.telegram:
            self.telegram(msg)

    # --------------------------------
    # TELEGRAM REPORT — COMPRA
    # --------------------------------

    def send_buy_report(self, real_balance: float, btc_qty: float,
                        entry_price: float, score: int, space: str,
                        atr: float, categoria: str, evento: str):
        """
        Llamado desde el runner tras confirmar el BUY FILLED.
        Muestra saldo real de Binance/Bybit en el momento de la compra.
        """
        msg = (
            f"🟢 BUY REAL\n\n"
            f"Par: {self.symbol}\n"
            f"BTC: {btc_qty:.8f}\n"
            f"Precio entrada: {entry_price:.2f}\n"
            f"Saldo antes: {real_balance:.2f} USDC\n"
            f"Score: {score}\n"
            f"Evento: {evento}\n"
            f"Space: {space}\n"
            f"ATR: {atr:.2f}\n"
            f"Trail gap: {self.trail_gap_pct*100:.2f}%\n"
            f"Categoría: {categoria}\n"
            f"SL en: {self.sl_price:.2f}"
        )

        if self.telegram:
            self.telegram(msg)

    # --------------------------------
    # TELEGRAM REPORT — VENTA DESDE VIGILANTE
    # --------------------------------

    def send_sell_report(self, real_balance_after: float, reason: str, pnl_pct: float):
        """
        Llamado desde el runner tras confirmar el SELL FILLED.
        Muestra saldo real actualizado de Binance/Bybit.
        """
        msg = (
            f"🔴 SELL REAL\n\n"
            f"Motivo: {reason}\n"
            f"Resultado estimado: {pnl_pct*100:.2f}%\n"
            f"Saldo real tras venta: {real_balance_after:.2f} USDC\n"
            f"Trades: {self.state['trades']} "
            f"(W:{self.state['wins']} / L:{self.state['losses']})\n"
            f"Max DD: -{self.state['max_drawdown_pct']*100:.2f}%"
        )

        if self.telegram:
            self.telegram(msg)
