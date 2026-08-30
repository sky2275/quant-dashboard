"""
signal_generator.py -- 信号生成器
从"看盘工具"升级为"量化系统"的核心模块之三。

汇总三类信号源，生成统一的买卖建议：
  1. 技术信号：MA交叉、RSI极值、MACD金叉死叉
  2. 因子信号：多因子评分触发阈值
  3. 量价信号：放量突破、缩量回调

输出：每只股票的当日信号 + 综合建议（买入/持有/卖出/观望）
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_factor as mf  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")

# 信号权重
SIGNAL_WEIGHTS = {
    "technical": 0.35,
    "factor": 0.40,
    "vol_price": 0.25,
}

# 建议阈值
THRESHOLDS = {
    "strong_buy": 75,
    "buy": 60,
    "hold": 40,
    "sell": 25,
}


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


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """计算MACD线、信号线、柱状图。"""
    if len(closes) < slow:
        return None, None, None
    ema_fast = [closes[0]] * len(closes)
    ema_slow = [closes[0]] * len(closes)
    af = 2 / (fast + 1)
    as_ = 2 / (slow + 1)
    for i in range(1, len(closes)):
        ema_fast[i] = closes[i] * af + ema_fast[i - 1] * (1 - af)
        ema_slow[i] = closes[i] * as_ + ema_slow[i - 1] * (1 - as_)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = [dif[0]] * len(dif)
    sa = 2 / (signal + 1)
    for i in range(1, len(dif)):
        dea[i] = dif[i] * sa + dea[i - 1] * (1 - sa)
    hist = [d - e for d, e in zip(dif, dea)]
    return dif[-1], dea[-1], hist[-1]


def generate_technical_signals(klines: list) -> dict:
    """技术指标信号。"""
    if not klines or len(klines) < 30:
        return {"score": 50, "signals": []}

    closes = [float(k[1]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    last_close = closes[-1]
    signals = []
    score = 50

    # MA 交叉
    if len(closes) >= 21:
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        ma5_prev = sum(closes[-6:-1]) / 5
        ma20_prev = sum(closes[-21:-1]) / 20
        if ma5 > ma20 and ma5_prev <= ma20_prev:
            score += 20
            signals.append("MA5上穿MA20，金叉")
        elif ma5 < ma20 and ma5_prev >= ma20_prev:
            score -= 20
            signals.append("MA5下穿MA20，死叉")
        elif ma5 > ma20:
            score += 5
        else:
            score -= 5

    # RSI
    rsi = mf._rsi(closes, 14)
    if rsi is not None:
        if rsi < 30:
            score += 15
            signals.append(f"RSI={rsi:.0f}，超卖")
        elif rsi > 70:
            score -= 15
            signals.append(f"RSI={rsi:.0f}，超买")
        elif 45 <= rsi <= 55:
            score += 5

    # MACD
    dif, dea, hist = _macd(closes)
    if dif is not None and dea is not None:
        if dif > dea and hist > 0:
            score += 10
            signals.append("MACD多头")
        elif dif < dea and hist < 0:
            score -= 10
            signals.append("MACD空头")

    # 趋势
    if len(closes) >= 61:
        ma60 = sum(closes[-60:]) / 60
        if last_close > ma60:
            score += 5
        else:
            score -= 5

    return {"score": max(0, min(100, score)), "rsi": rsi, "signals": signals}


def generate_vol_price_signals(klines: list) -> dict:
    """量价信号。"""
    if not klines or len(klines) < 25:
        return {"score": 50, "signals": []}

    closes = [float(k[1]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    last_close = closes[-1]
    signals = []
    score = 50

    # 量比
    recent_vol = sum(volumes[-5:]) / 5
    base_vol = sum(volumes[-25:-5]) / 20
    vol_ratio = recent_vol / base_vol if base_vol > 0 else 1.0

    # 价格变化
    price_change = (last_close / closes[-2] - 1) * 100 if len(closes) >= 2 else 0

    # 放量上涨
    if vol_ratio > 1.5 and price_change > 1:
        score += 25
        signals.append(f"放量上涨(+{price_change:.1f}%, 量比{vol_ratio:.1f})")
    # 放量下跌
    elif vol_ratio > 1.5 and price_change < -1:
        score -= 25
        signals.append(f"放量下跌({price_change:.1f}%, 量比{vol_ratio:.1f})")
    # 缩量回调
    elif vol_ratio < 0.7 and price_change < 0:
        score += 10
        signals.append(f"缩量回调({price_change:.1f}%, 量比{vol_ratio:.1f})")
    # 缩量上涨
    elif vol_ratio < 0.7 and price_change > 0:
        score += 5
        signals.append(f"缩量上涨(+{price_change:.1f}%, 量比{vol_ratio:.1f})")

    # 突破20日高点
    if len(closes) >= 21:
        high_20 = max(closes[-21:-1])
        if last_close > high_20:
            score += 15
            signals.append("突破20日新高")

    return {"score": max(0, min(100, score)), "vol_ratio": round(vol_ratio, 2), "signals": signals}


def generate_signal(code: str, klines: list | None = None) -> dict:
    """
    生成单只股票的综合信号。
    返回: {
        code, name, action: "strong_buy"/"buy"/"hold"/"sell"/"watch",
        confidence: 0-100,
        technical: {...}, factor: {...}, vol_price: {...},
        all_signals: [...],
        price, ma20, ma60, rsi
    }
    """
    if klines is None:
        klines = _load_klines(code)
    if not klines:
        return {"code": code, "error": "无K线数据"}

    # 加载股票名称
    name = code
    path = os.path.join(CACHE_DIR, "backtest_klines.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("stocks", {}).get(code, {}).get("name", code)
        except Exception:
            pass

    closes = [float(k[1]) for k in klines]
    last_price = closes[-1]

    # 1. 技术信号
    tech = generate_technical_signals(klines)

    # 2. 因子信号（传 code 让资金流因子按日期取数生效）
    factor_result = mf.score_stock(klines, code=code)
    factor = {
        "score": factor_result["total_score"],
        "factor_scores": factor_result["factor_scores"],
        "signals": factor_result["signals"],
    }

    # 3. 量价信号
    vp = generate_vol_price_signals(klines)

    # 加权综合信号
    composite = (
        tech["score"] * SIGNAL_WEIGHTS["technical"] +
        factor["score"] * SIGNAL_WEIGHTS["factor"] +
        vp["score"] * SIGNAL_WEIGHTS["vol_price"]
    )
    composite = round(composite, 1)

    # 生成建议
    if composite >= THRESHOLDS["strong_buy"]:
        action = "strong_buy"
    elif composite >= THRESHOLDS["buy"]:
        action = "buy"
    elif composite >= THRESHOLDS["hold"]:
        action = "hold"
    elif composite >= THRESHOLDS["sell"]:
        action = "watch"
    else:
        action = "sell"

    # 汇总所有信号
    all_signals = tech["signals"] + factor["signals"] + vp["signals"]

    return {
        "code": code,
        "name": name,
        "price": last_price,
        "action": action,
        "confidence": composite,
        "technical_score": tech["score"],
        "factor_score": factor["score"],
        "vol_price_score": vp["score"],
        "rsi": tech.get("rsi"),
        "vol_ratio": vp.get("vol_ratio"),
        "ma20": factor_result.get("ma20"),
        "ma60": factor_result.get("ma60"),
        "all_signals": all_signals,
        "factor_scores": factor["factor_scores"],
    }


def generate_all_signals(codes: list[str] | None = None) -> list[dict]:
    """对所有股票生成信号，按信心度排序。"""
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
        klines = stocks.get(code, {}).get("kline", [])
        if klines:
            results.append(generate_signal(code, klines))

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results


if __name__ == "__main__":
    signals = generate_all_signals()
    print(f"\n=== 信号生成器 (共 {len(signals)} 只) ===")
    print(f"{'代码':<8} {'名称':<8} {'建议':<10} {'信心':<6} {'技术':<6} {'因子':<6} {'量价':<6} 信号")
    for s in signals:
        action_map = {"strong_buy": "强烈买入", "buy": "买入", "hold": "持有",
                       "watch": "观望", "sell": "卖出"}
        sig = "; ".join(s["all_signals"][:2]) if s["all_signals"] else ""
        print(f"{s['code']:<8} {s['name']:<8} {action_map.get(s['action'], s['action']):<10} "
              f"{s['confidence']:<6} {s['technical_score']:<6} {s['factor_score']:<6} "
              f"{s['vol_price_score']:<6} {sig}")
