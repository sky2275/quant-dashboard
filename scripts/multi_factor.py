"""
multi_factor.py -- 多因子选股模型
从"看盘工具"升级为"量化系统"的核心模块之一。

因子体系（5 大因子）：
  1. 动量因子 (momentum)   : 20日涨幅，越高越好
  2. 量价因子 (vol_price)  : 量比+换手率组合，适度放量最佳
  3. 趋势因子 (trend)      : MA20上方加分，MA60斜率为正加分
  4. 波动因子 (volatility) : ATR/Price 比率，低波动更优
  5. RSI因子 (rsi)         : 40-60中性区最佳，避免超买超卖

输出：每只股票的综合评分 (0-100)，按评分排序选股。
"""
from __future__ import annotations

import json
import os
import math
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

# 因子权重（可调）
FACTOR_WEIGHTS = {
    "momentum": 0.25,
    "vol_price": 0.15,
    "trend": 0.25,
    "volatility": 0.15,
    "rsi": 0.20,
}


def _load_klines(code: str) -> list | None:
    """从 backtest_klines.json 加载某只股票的K线。"""
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


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _atr(klines: list, period: int = 14) -> float | None:
    """Average True Range."""
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i][3])
        low = float(klines[i][4])
        prev_close = float(klines[i - 1][1])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else None


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def score_stock(klines: list) -> dict:
    """
    对单只股票计算 5 大因子评分。
    klines: [[date, open, close, high, low, volume], ...] 旧->新
    返回: {factor_scores: {...}, total_score: float, signals: [...]}
    """
    if not klines or len(klines) < 60:
        return {"total_score": 0, "factor_scores": {}, "signals": ["数据不足"]}

    closes = [float(k[1]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    last_close = closes[-1]
    scores = {}
    signals = []

    # 1. 动量因子：20日涨幅
    if len(closes) >= 21:
        ret_20d = (closes[-1] / closes[-21] - 1) * 100
        # 评分映射：+10%→100, 0%→50, -10%→0
        scores["momentum"] = max(0, min(100, 50 + ret_20d * 5))
        if ret_20d > 5:
            signals.append(f"20日涨幅+{ret_20d:.1f}%，动量强劲")
        elif ret_20d < -5:
            signals.append(f"20日跌幅{ret_20d:.1f}%，动量疲弱")
    else:
        scores["momentum"] = 50

    # 2. 量价因子：量比（最近5日均量/前20日均量）
    if len(volumes) >= 25:
        recent_vol = sum(volumes[-5:]) / 5
        base_vol = sum(volumes[-25:-5]) / 20
        vol_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
        # 量比 1.5-2.5 最佳
        if 1.5 <= vol_ratio <= 2.5:
            scores["vol_price"] = 90
            signals.append(f"量比{vol_ratio:.2f}，适度放量")
        elif vol_ratio > 3:
            scores["vol_price"] = 40
            signals.append(f"量比{vol_ratio:.2f}，放量过大需警惕")
        elif vol_ratio < 0.7:
            scores["vol_price"] = 30
            signals.append(f"量比{vol_ratio:.2f}，缩量明显")
        else:
            scores["vol_price"] = 60
    else:
        scores["vol_price"] = 50

    # 3. 趋势因子：MA20/MA60 位置 + MA60斜率
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    if ma20 and ma60:
        trend_score = 50
        if last_close > ma20:
            trend_score += 20
            signals.append("股价在MA20上方")
        if ma20 > ma60:
            trend_score += 20
            signals.append("MA20 > MA60，多头排列")
        # MA60 斜率（5日前vs现在）
        if len(closes) >= 65:
            ma60_5d_ago = sum(closes[-65:-5]) / 60
            if ma60 > ma60_5d_ago:
                trend_score += 10
        scores["trend"] = min(100, trend_score)
    else:
        scores["trend"] = 50

    # 4. 波动因子：ATR/Price
    atr_val = _atr(klines, 14)
    if atr_val and last_close > 0:
        atr_pct = atr_val / last_close * 100
        # ATR% < 2%→高分, 2-4%→中, >5%→低分
        if atr_pct < 2:
            scores["volatility"] = 85
        elif atr_pct < 4:
            scores["volatility"] = 65
        else:
            scores["volatility"] = 35
            signals.append(f"ATR占比{atr_pct:.1f}%，波动较大")
    else:
        scores["volatility"] = 50

    # 5. RSI因子
    rsi_val = _rsi(closes, 14)
    if rsi_val is not None:
        if 40 <= rsi_val <= 60:
            scores["rsi"] = 85
            signals.append(f"RSI={rsi_val:.0f}，中性区")
        elif 30 <= rsi_val < 40:
            scores["rsi"] = 75
            signals.append(f"RSI={rsi_val:.0f}，接近超卖")
        elif 60 < rsi_val <= 70:
            scores["rsi"] = 60
            signals.append(f"RSI={rsi_val:.0f}，偏强")
        elif rsi_val < 30:
            scores["rsi"] = 50
            signals.append(f"RSI={rsi_val:.0f}，超卖反弹机会")
        else:
            scores["rsi"] = 30
            signals.append(f"RSI={rsi_val:.0f}，超买风险")
    else:
        scores["rsi"] = 50

    # 加权总分
    total = sum(scores.get(k, 50) * w for k, w in FACTOR_WEIGHTS.items())

    return {
        "total_score": round(total, 1),
        "factor_scores": {k: round(v, 1) for k, v in scores.items()},
        "rsi": rsi_val,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "atr_pct": round(atr_val / last_close * 100, 2) if atr_val and last_close else None,
        "signals": signals,
    }


def rank_stocks(codes: list[str] | None = None, top_n: int = 20) -> list[dict]:
    """
    对多只股票评分并排名。
    codes: 股票代码列表，None则用 backtest_klines.json 中全部
    返回: [{code, name, total_score, factor_scores, signals}, ...] 按分数降序
    """
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    stocks = data.get("stocks", {})
    if codes is None:
        codes = list(stocks.keys())

    results = []
    for code in codes:
        stock = stocks.get(code)
        if not stock:
            continue
        klines = stock.get("kline", [])
        result = score_stock(klines)
        result["code"] = code
        result["name"] = stock.get("name", code)
        results.append(result)

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    ranking = rank_stocks()
    print(f"\n=== 多因子选股排名 (Top {len(ranking)}) ===")
    print(f"{'排名':<4} {'代码':<8} {'名称':<8} {'总分':<6} {'动量':<6} {'量价':<6} {'趋势':<6} {'波动':<6} {'RSI':<6} 信号")
    for i, r in enumerate(ranking, 1):
        fs = r["factor_scores"]
        sig = "; ".join(r["signals"][:2]) if r["signals"] else ""
        print(f"{i:<4} {r['code']:<8} {r['name']:<8} {r['total_score']:<6} "
              f"{fs.get('momentum', 0):<6} {fs.get('vol_price', 0):<6} "
              f"{fs.get('trend', 0):<6} {fs.get('volatility', 0):<6} "
              f"{fs.get('rsi', 0):<6} {sig}")
