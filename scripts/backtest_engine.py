"""
backtest_engine.py -- 向量化回测引擎
从"看盘工具"升级为"量化系统"的核心模块之二。

支持策略：
  1. ma_cross  : 均线交叉（MA5上穿MA20买入，下穿卖出）
  2. momentum  : 动量突破（20日新高买入，跌破MA10卖出）
  3. mean_rev  : 均值回归（RSI<30买入，RSI>70卖出）
  4. multi_factor : 多因子信号（综合评分>70买入，<50卖出）

输出指标：
  - 总收益率、年化收益率
  - 最大回撤
  - Sharpe比率
  - 胜率、交易次数
  - 每笔交易明细

性能：500根K线向量化计算 < 100ms
"""
from __future__ import annotations

import json
import os
import math
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

# 交易成本
COMMISSION_RATE = 0.0003   # 万三佣金
SLIPPAGE = 0.001           # 0.1% 滑点
STAMP_TAX = 0.0005         # 卖出印花税万五


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


def _sma_series(closes: list[float], period: int) -> list[float | None]:
    """计算移动平均线序列，前 period-1 个为 None。"""
    result = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1: i + 1]) / period
    return result


def _rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """计算 RSI 序列。"""
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 100 - 100 / (1 + (avg_gain / avg_loss if avg_loss > 0 else 999))
    for i in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            result[i] = 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def _max_drawdown(equity: list[float]) -> float:
    """计算最大回撤百分比。"""
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _sharpe(returns: list[float], annual_factor: int = 252) -> float:
    """年化 Sharpe 比率（无风险利率=0）。"""
    if not returns or len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std_r = math.sqrt(var_r)
    if std_r == 0:
        return 0.0
    return round(mean_r / std_r * math.sqrt(annual_factor), 2)


def _apply_cost(price: float, is_buy: bool) -> float:
    """应用交易成本，返回实际成交价。"""
    if is_buy:
        return price * (1 + SLIPPAGE + COMMISSION_RATE)
    else:
        return price * (1 - SLIPPAGE - COMMISSION_RATE - STAMP_TAX)


def backtest(klines: list, strategy: str = "ma_cross", params: dict | None = None) -> dict:
    """
    执行回测。
    klines: [[date, open, close, high, low, volume], ...] 旧->新
    strategy: 策略名
    params: 策略参数
    返回: {strategy, total_return, annual_return, max_drawdown, sharpe,
           win_rate, trade_count, trades: [...], equity_curve: [...]}
    """
    if not klines or len(klines) < 30:
        return {"error": "K线数据不足"}

    params = params or {}
    closes = [float(k[1]) for k in klines]
    dates = [k[0] for k in klines]
    n = len(closes)

    # ---- 生成买卖信号 ----
    signals = [0] * n  # 1=买, -1=卖, 0=持有
    short_ma = params.get("short_ma", 5)
    long_ma = params.get("long_ma", 20)

    if strategy == "ma_cross":
        ma_s = _sma_series(closes, short_ma)
        ma_l = _sma_series(closes, long_ma)
        for i in range(long_ma + 1, n):
            if ma_s[i] and ma_l[i] and ma_s[i - 1] and ma_l[i - 1]:
                if ma_s[i] > ma_l[i] and ma_s[i - 1] <= ma_l[i - 1]:
                    signals[i] = 1
                elif ma_s[i] < ma_l[i] and ma_s[i - 1] >= ma_l[i - 1]:
                    signals[i] = -1

    elif strategy == "momentum":
        lookback = params.get("lookback", 20)
        stop_ma = params.get("stop_ma", 10)
        ma_stop = _sma_series(closes, stop_ma)
        for i in range(lookback, n):
            high_n = max(closes[i - lookback: i])
            if closes[i] > high_n and closes[i - 1] <= high_n:
                signals[i] = 1
            elif ma_stop[i] and closes[i] < ma_stop[i]:
                signals[i] = -1

    elif strategy == "mean_rev":
        rsi_period = params.get("rsi_period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)
        rsi = _rsi_series(closes, rsi_period)
        for i in range(rsi_period + 1, n):
            if rsi[i] is not None:
                if rsi[i] < oversold and rsi[i - 1] >= oversold:
                    signals[i] = 1
                elif rsi[i] > overbought and rsi[i - 1] <= overbought:
                    signals[i] = -1

    elif strategy == "multi_factor":
        # 使用多因子评分，每天检查
        try:
            from multi_factor import score_stock
        except ImportError:
            import sys; sys.path.insert(0, os.path.dirname(__file__))
            from multi_factor import score_stock
        buy_threshold = params.get("buy_threshold", 70)
        sell_threshold = params.get("sell_threshold", 50)
        window = params.get("window", 60)
        for i in range(window, n):
            sub = klines[:i + 1]
            result = score_stock(sub)
            score = result["total_score"]
            if score >= buy_threshold:
                signals[i] = 1
            elif score <= sell_threshold:
                signals[i] = -1
    else:
        return {"error": f"未知策略: {strategy}"}

    # ---- 执行回测 ----
    position = 0          # 持仓数量
    cash = 100000.0       # 初始资金 10 万
    initial_capital = cash
    entry_price = 0.0
    trades = []
    equity_curve = []
    winning_trades = 0

    for i in range(n):
        price = closes[i]
        date = dates[i]

        # 执行买入
        if signals[i] == 1 and position == 0:
            buy_price = _apply_cost(price, is_buy=True)
            position = int(cash / buy_price / 100) * 100  # 整手买入
            if position > 0:
                cost = position * buy_price
                cash -= cost
                entry_price = buy_price

        # 执行卖出
        elif signals[i] == -1 and position > 0:
            sell_price = _apply_cost(price, is_buy=False)
            proceeds = position * sell_price
            cash += proceeds
            pnl = proceeds - position * entry_price
            pnl_pct = (sell_price / entry_price - 1) * 100
            trades.append({
                "buy_date": dates[i - 1] if i > 0 else date,
                "buy_price": round(entry_price, 2),
                "sell_date": date,
                "sell_price": round(sell_price, 2),
                "shares": position,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "win": pnl > 0,
            })
            if pnl > 0:
                winning_trades += 1
            position = 0
            entry_price = 0.0

        # 记录每日净值
        total_value = cash + position * price
        equity_curve.append(round(total_value, 2))

    # 如果末尾还有持仓，按最后收盘价平仓计算
    if position > 0:
        last_price = closes[-1]
        total_value = cash + position * last_price
        equity_curve[-1] = round(total_value, 2)
        pnl = total_value - initial_capital
        trades.append({
            "buy_date": dates[-1],
            "buy_price": round(entry_price, 2),
            "sell_date": "持仓中",
            "sell_price": round(last_price, 2),
            "shares": position,
            "pnl": round(pnl, 2),
            "pnl_pct": round((last_price / entry_price - 1) * 100, 2),
            "win": pnl > 0,
        })
        if pnl > 0:
            winning_trades += 1

    # ---- 计算统计指标 ----
    final_value = equity_curve[-1]
    total_return = (final_value / initial_capital - 1) * 100

    # 年化收益
    trading_days = n
    annual_return = ((final_value / initial_capital) ** (252 / trading_days) - 1) * 100 \
        if trading_days > 0 else 0

    # 日收益率序列
    daily_returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0:
            daily_returns.append(equity_curve[i] / equity_curve[i - 1] - 1)

    max_dd = _max_drawdown(equity_curve)
    sharpe = _sharpe(daily_returns)
    trade_count = len(trades)
    win_rate = round(winning_trades / trade_count * 100, 1) if trade_count > 0 else 0

    # 买入持有基准
    bh_return = (closes[-1] / closes[0] - 1) * 100

    return {
        "strategy": strategy,
        "params": params,
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return": round(total_return, 2),
        "annual_return": round(annual_return, 2),
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "trade_count": trade_count,
        "buy_hold_return": round(bh_return, 2),
        "excess_return": round(total_return - bh_return, 2),
        "trades": trades,
        "equity_curve_sample": equity_curve[::max(1, len(equity_curve) // 50)],  # 降采样
    }


def run_all_strategies(code: str, klines: list | None = None) -> dict:
    """对单只股票跑所有策略，返回对比结果。"""
    if klines is None:
        klines = _load_klines(code)
    if not klines:
        return {"error": f"无法加载 {code} 的K线数据"}

    strategies = {
        "ma_cross": {"short_ma": 5, "long_ma": 20},
        "momentum": {"lookback": 20, "stop_ma": 10},
        "mean_rev": {"rsi_period": 14, "oversold": 30, "overbought": 70},
    }

    results = {}
    for name, params in strategies.items():
        results[name] = backtest(klines, strategy=name, params=params)

    return results


if __name__ == "__main__":
    # 对所有持仓股跑回测
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for code, stock in data.get("stocks", {}).items():
            name = stock.get("name", code)
            klines = stock.get("kline", [])
            print(f"\n{'='*60}")
            print(f"  {code} {name}  ({len(klines)} 根K线)")
            print(f"{'='*60}")
            all_results = run_all_strategies(code, klines)
            for strat, r in all_results.items():
                if "error" in r:
                    print(f"  {strat}: {r['error']}")
                    continue
                print(f"  {strat:12s} | 收益:{r['total_return']:>7.1f}% | "
                      f"年化:{r['annual_return']:>7.1f}% | 回撤:{r['max_drawdown']:>5.1f}% | "
                      f"Sharpe:{r['sharpe']:>5.1f} | 胜率:{r['win_rate']:>5.1f}% | "
                      f"交易:{r['trade_count']:>3}次 | 超额:{r['excess_return']:>+7.1f}%")
