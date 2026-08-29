"""
risk_manager.py -- 风控执行层
从"看盘工具"升级为"量化系统"的核心模块之四。

三大功能：
  1. 凯利公式仓位管理 (Kelly Criterion)
  2. ATR 动态止损 (Average True Range Stop)
  3. 组合风控 (Portfolio Risk Control)

集成方式：
  from risk_manager import RiskManager
  rm = RiskManager()
  # 计算建议仓位
  size = rm.kelly_position(code, win_rate, win_loss_ratio, capital)
  # 计算止损价
  stop = rm.atr_stop(code, entry_price, side='long')
  # 检查组合风险
  risk = rm.portfolio_risk(positions)
"""
from __future__ import annotations

import json
import os
import math
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

# 风控参数
MAX_POSITION_PCT = 0.25       # 单只股票最大仓位 25%
MAX_SECTOR_PCT = 0.50         # 单板块最大暴露 50%
MAX_TOTAL_PCT = 0.80          # 最大总仓位 80%
KELLY_FRACTION = 0.5          # 半凯利（保守，避免全凯利过度集中）
ATR_STOP_MULT = 2.0           # ATR 止损倍数（2倍ATR）
ATR_PROFIT_MULT = 3.0         # ATR 止盈倍数（3倍ATR，盈亏比1.5:1）


def _load_klines(code: str) -> list | None:
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        stock = data.get("stocks", {}).get(code)
        if stock and stock.get("kline"):
            return stock["kline"]
    except Exception:
        pass
    return None


def _atr(klines: list, period: int = 14) -> float | None:
    """ATR (Average True Range)."""
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i][3])
        low = float(klines[i][4])
        prev_close = float(klines[i - 1][2])  # 修正：prev_close 用收盘价 [2]（此前误用开盘价 [1]）
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else None


class RiskManager:
    """风控管理器。"""

    def __init__(self, capital: float = 100000.0):
        self.capital = capital

    # ------------------------------------------------------------------ 凯利仓位
    def kelly_position(self, code: str, win_rate: float,
                       win_loss_ratio: float, capital: float | None = None,
                       price: float | None = None) -> dict:
        """
        凯利公式计算最优仓位。

        Kelly = (p * b - (1-p)) / b * fraction
        其中 p=胜率, b=盈亏比, fraction=半凯利系数

        参数:
          code: 股票代码
          win_rate: 胜率 (0-1)
          win_loss_ratio: 盈亏比 (如 1.5 表示盈利是亏损的1.5倍)
          capital: 可用资金（默认用 self.capital）
          price: 当前股价（用于计算股数）

        返回: {kelly_pct, suggested_pct, shares, amount, stop_price, target_price}
        """
        cap = capital or self.capital
        if win_rate <= 0 or win_rate >= 1 or win_loss_ratio <= 0:
            return {"kelly_pct": 0, "suggested_pct": 0, "shares": 0, "amount": 0,
                    "reason": "参数无效"}

        # 凯利公式
        kelly = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly = max(0, min(kelly, 1))  # 限制在 0-1

        # 半凯利（更保守）
        suggested_pct = kelly * KELLY_FRACTION

        # 限制单只最大仓位
        suggested_pct = min(suggested_pct, MAX_POSITION_PCT)

        # 限制总仓位
        suggested_pct = min(suggested_pct, MAX_TOTAL_PCT)

        amount = cap * suggested_pct

        result = {
            "kelly_pct": round(kelly * 100, 1),
            "suggested_pct": round(suggested_pct * 100, 1),
            "amount": round(amount, 2),
            "win_rate": round(win_rate * 100, 1),
            "win_loss_ratio": round(win_loss_ratio, 2),
        }

        if price and price > 0:
            shares = int(amount / price / 100) * 100  # 整手
            result["shares"] = shares
            result["actual_amount"] = round(shares * price, 2)

            # 计算止损止盈
            klines = _load_klines(code)
            atr_val = _atr(klines) if klines else None
            if atr_val:
                result["atr"] = round(atr_val, 3)
                result["atr_pct"] = round(atr_val / price * 100, 2)
                result["stop_price"] = round(price - ATR_STOP_MULT * atr_val, 2)
                result["target_price"] = round(price + ATR_PROFIT_MULT * atr_val, 2)
                result["risk_reward_ratio"] = round(ATR_PROFIT_MULT / ATR_STOP_MULT, 2)
                result["max_loss"] = round(shares * ATR_STOP_MULT * atr_val, 2)
                result["max_profit"] = round(shares * ATR_PROFIT_MULT * atr_val, 2)

        return result

    # ------------------------------------------------------------------ ATR 止损
    def atr_stop(self, code: str, entry_price: float,
                 side: str = "long", mult: float | None = None) -> dict:
        """
        计算 ATR 动态止损价。

        参数:
          code: 股票代码
          entry_price: 入场价
          side: 'long' 或 'short'
          mult: ATR 倍数（默认 ATR_STOP_MULT）

        返回: {stop_price, target_price, atr, atr_pct, risk_per_share, reward_per_share}
        """
        m = mult or ATR_STOP_MULT
        klines = _load_klines(code)
        atr_val = _atr(klines) if klines else None

        if not atr_val or entry_price <= 0:
            return {"error": "无法计算ATR或价格无效"}

        if side == "long":
            stop_price = entry_price - m * atr_val
            target_price = entry_price + ATR_PROFIT_MULT * atr_val
        else:
            stop_price = entry_price + m * atr_val
            target_price = entry_price - ATR_PROFIT_MULT * atr_val

        return {
            "stop_price": round(stop_price, 2),
            "target_price": round(target_price, 2),
            "atr": round(atr_val, 3),
            "atr_pct": round(atr_val / entry_price * 100, 2),
            "risk_per_share": round(m * atr_val, 2),
            "reward_per_share": round(ATR_PROFIT_MULT * atr_val, 2),
            "risk_reward_ratio": round(ATR_PROFIT_MULT / m, 2),
            "side": side,
        }

    def trailing_stop(self, code: str, current_price: float,
                      highest_since_entry: float, side: str = "long") -> dict:
        """
        ATR 移动止损（跟踪止损）。
        随着股价上涨，止损价也跟着上移，锁定利润。

        参数:
          highest_since_entry: 入场以来的最高价
        """
        m = ATR_STOP_MULT
        klines = _load_klines(code)
        atr_val = _atr(klines) if klines else None

        if not atr_val or current_price <= 0:
            return {"error": "无法计算ATR或价格无效"}

        if side == "long":
            # 止损价 = 最高价 - N倍ATR
            stop_price = highest_since_entry - m * atr_val
            # 止损价不能高于当前价
            stop_price = min(stop_price, current_price)
            # 移动止损只上移不下移
        else:
            stop_price = highest_since_entry + m * atr_val
            stop_price = max(stop_price, current_price)

        return {
            "stop_price": round(stop_price, 2),
            "atr": round(atr_val, 3),
            "highest": round(highest_since_entry, 2),
            "current": round(current_price, 2),
            "distance_pct": round(abs(current_price - stop_price) / current_price * 100, 2),
            "side": side,
        }

    # ------------------------------------------------------------------ 组合 VaR
    def _portfolio_var(self, positions: list[dict], total_capital: float) -> dict | None:
        """
        组合级 VaR(95%)：基于持仓近 60 日收益率按市值加权，正态近似。
        VaR(95%) = 1.645 × σ(组合日收益率) × 组合市值。
        当 VaR 超过总资产 2%（对齐 strategy.yaml 的 single_day_drawdown: 2）触发降仓。
        """
        rets: dict[str, list] = {}
        weights: dict[str, float] = {}
        for p in positions:
            code = p.get("code")
            mv = p.get("market_value", 0)
            if not code or mv <= 0:
                continue
            klines = _load_klines(code)
            if not klines or len(klines) < 60:
                continue
            closes = [float(k[2]) for k in klines]
            r = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
            rets[code] = r[-60:]  # 近 60 个交易日
            weights[code] = mv
        if not rets:
            return None
        min_len = min(len(r) for r in rets.values())
        total_mv = sum(weights.values())
        if total_mv <= 0 or min_len < 2:
            return None
        # 市值加权组合日收益率序列
        port_rets = []
        for i in range(min_len):
            pr = sum(rets[c][i] * weights[c] / total_mv for c in rets)
            port_rets.append(pr)
        n = len(port_rets)
        mean = sum(port_rets) / n
        var_ = sum((r - mean) ** 2 for r in port_rets) / (n - 1)
        sigma = var_ ** 0.5
        var_95 = 1.645 * sigma * total_mv
        var_pct = var_95 / total_capital if total_capital > 0 else 0.0
        return {
            "sigma_daily": round(sigma, 5),
            "var_95_amount": round(var_95, 2),
            "var_95_pct": round(var_pct * 100, 2),
            "daily_drawdown_limit_pct": 2.0,
            "trigger_deleverage": var_pct > 0.02,
            "n_days": n,
        }

    # ------------------------------------------------------------------ 组合风控
    def portfolio_risk(self, positions: list[dict]) -> dict:
        """
        组合层面的风控检查。

        positions: [{code, name, sector, market_value, cost, shares, price}, ...]
        返回: {total_exposure, max_position, max_sector, positions_check, warnings}
        """
        total_capital = self.capital
        total_mv = sum(p.get("market_value", 0) for p in positions)
        exposure_pct = total_mv / total_capital if total_capital > 0 else 0

        # 单只仓位检查
        position_checks = []
        warnings = []
        for p in positions:
            pct = p.get("market_value", 0) / total_capital if total_capital > 0 else 0
            check = {
                "code": p.get("code"),
                "name": p.get("name"),
                "market_value": p.get("market_value", 0),
                "pct": round(pct * 100, 1),
                "status": "OK" if pct <= MAX_POSITION_PCT else "OVERWEIGHT",
            }
            if pct > MAX_POSITION_PCT:
                check["max_allowed"] = round(MAX_POSITION_PCT * 100, 1)
                warnings.append(f"{p.get('name', p.get('code'))} 仓位 {pct*100:.1f}% 超过上限 {MAX_POSITION_PCT*100:.0f}%")
            position_checks.append(check)

        # 板块集中度检查
        sector_mv = {}
        for p in positions:
            sector = p.get("sector", "未知")
            sector_mv[sector] = sector_mv.get(sector, 0) + p.get("market_value", 0)

        sector_checks = []
        for sector, mv in sector_mv.items():
            pct = mv / total_capital if total_capital > 0 else 0
            check = {"sector": sector, "market_value": round(mv, 2), "pct": round(pct * 100, 1)}
            if pct > MAX_SECTOR_PCT:
                check["status"] = "OVERWEIGHT"
                warnings.append(f"板块 {sector} 暴露 {pct*100:.1f}% 超过上限 {MAX_SECTOR_PCT*100:.0f}%")
            else:
                check["status"] = "OK"
            sector_checks.append(check)

        # 总仓位检查
        if exposure_pct > MAX_TOTAL_PCT:
            warnings.append(f"总仓位 {exposure_pct*100:.1f}% 超过上限 {MAX_TOTAL_PCT*100:.0f}%")

        # 组合级 VaR 风险预算（95% 单日，超过总资产 2% 触发降仓）
        var_result = self._portfolio_var(positions, total_capital)
        if var_result and var_result["trigger_deleverage"]:
            warnings.append(
                f"组合单日 VaR(95%) {var_result['var_95_pct']}% 超过 {var_result['daily_drawdown_limit_pct']}% 上限，建议降仓"
            )

        return {
            "total_capital": round(total_capital, 2),
            "total_market_value": round(total_mv, 2),
            "total_exposure_pct": round(exposure_pct * 100, 1),
            "max_position_pct": MAX_POSITION_PCT * 100,
            "max_sector_pct": MAX_SECTOR_PCT * 100,
            "max_total_pct": MAX_TOTAL_PCT * 100,
            "position_checks": position_checks,
            "sector_checks": sector_checks,
            "var_95": var_result,
            "warnings": warnings,
            "risk_level": "HIGH" if len(warnings) >= 3 else ("MEDIUM" if warnings else "LOW"),
        }

    # ------------------------------------------------------------------ 综合建议
    def trade_plan(self, code: str, signal: dict, capital: float | None = None) -> dict:
        """
        基于信号生成完整交易计划。

        signal: 信号生成器的输出 (signal_generator.generate_signal)
        返回: {action, shares, entry_price, stop_price, target_price, position_pct, risk_reward, reasoning}
        """
        cap = capital or self.capital
        price = signal.get("price", 0)
        action = signal.get("action", "hold")
        confidence = signal.get("confidence", 50)

        if action in ("sell",):
            return {"action": "sell", "reasoning": "信号建议卖出"}

        if action == "hold":
            return {"action": "hold", "reasoning": "信号中性，维持观望"}

        # 买入建议
        # 根据信号信心度调整胜率假设
        if action == "strong_buy":
            win_rate = 0.55 + (confidence - 75) / 100 * 0.15  # 55%-70%
        else:  # buy
            win_rate = 0.48 + (confidence - 60) / 100 * 0.12  # 48%-60%

        win_loss_ratio = 1.5  # 默认盈亏比 1.5:1

        kelly = self.kelly_position(code, win_rate, win_loss_ratio, cap, price)
        stop = self.atr_stop(code, price)

        reasoning = []
        reasoning.append(f"信号: {action} (信心度 {confidence})")
        reasoning.append(f"胜率假设: {win_rate*100:.0f}%")
        reasoning.append(f"凯利仓位: {kelly.get('suggested_pct', 0)}%")

        if "stop_price" in stop and "stop_price" not in kelly:
            kelly["stop_price"] = stop["stop_price"]
            kelly["target_price"] = stop["target_price"]
            kelly["risk_reward_ratio"] = stop.get("risk_reward_ratio", 1.5)
            reasoning.append(f"止损: {stop['stop_price']} ({stop.get('atr_pct', 0)}% ATR)")
            reasoning.append(f"止盈: {stop['target_price']}")

        kelly["action"] = action
        kelly["reasoning"] = "; ".join(reasoning)
        return kelly


if __name__ == "__main__":
    rm = RiskManager(capital=100000)

    # 模拟测试
    print("=" * 60)
    print("  风控模块测试")
    print("=" * 60)

    # 1. 凯利仓位
    print("\n--- 凯利仓位计算 ---")
    result = rm.kelly_position("300285", win_rate=0.58, win_loss_ratio=1.5, price=35.0)
    for k, v in result.items():
        print(f"  {k}: {v}")

    # 2. ATR 止损
    print("\n--- ATR 止损 ---")
    stop = rm.atr_stop("300285", entry_price=35.0)
    for k, v in stop.items():
        print(f"  {k}: {v}")

    # 3. 移动止损
    print("\n--- 移动止损 ---")
    trail = rm.trailing_stop("300285", current_price=36.5, highest_since_entry=37.2)
    for k, v in trail.items():
        print(f"  {k}: {v}")

    # 4. 组合风控
    print("\n--- 组合风控 ---")
    positions = [
        {"code": "300285", "name": "国瓷材料", "sector": "半导体", "market_value": 28000},
        {"code": "000636", "name": "风华高科", "sector": "半导体", "market_value": 22000},
        {"code": "003033", "name": "征和工业", "sector": "机械", "market_value": 15000},
        {"code": "300223", "name": "北京君正", "sector": "半导体", "market_value": 35000},
    ]
    risk = rm.portfolio_risk(positions)
    print(f"  总仓位: {risk['total_exposure_pct']}%")
    print(f"  风险等级: {risk['risk_level']}")
    for w in risk["warnings"]:
        print(f"  ⚠ {w}")
    for s in risk["sector_checks"]:
        print(f"  板块 {s['sector']}: {s['pct']}% ({s['status']})")
