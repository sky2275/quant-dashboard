"""
multi_factor.py -- 多因子选股模型（v2 · 接入 factor_lib 因子库）

================================================================================
v2 改造（2026-08-30）
================================================================================
1. 因子定义迁出到 factor_lib.py，本文件不再硬编码任何因子逻辑。
   补因子 → 只改 factor_lib.FACTORS，本文件零改动。

2. 评分方式从「分档 if/else」改为「raw 值线性映射到 0-100」。
   旧版 5 因子的分档打分（如"站上MA20 +20分"）是台阶状的，同一档内
   差异被抹平，且与 factor_ic 算 IC 用的原始值定义不一致——
   导致"IC 说这个因子有效，评分却把它压在低档"。
   现在评分与 IC 同源，单调映射保证排序一致。

3. 支持因子翻转：IC 显著为负的因子（如 mom_20d）自动按 100-score 使用。
   旧版只是把反向因子降权，等于承认方向错还留半仓继续做错。

4. 因子数 5 → 20，按大类分配权重（抑制共线性）。

================================================================================
下游调用方（保持返回结构不变）
================================================================================
  signal_generator.py : total_score / factor_scores / signals / ma20 / ma60 / rsi
  backtest_engine.py  : score_stock(klines)["total_score"]
  screener.py         : factor_score
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import factor_lib as flib  # noqa: E402

# 因子权重（基础权重由 factor_lib 按大类生成；被 factor_ic.json 的动态权重覆盖）
FACTOR_WEIGHTS: dict = flib.base_weights()

_IC_CACHE: dict | None = None
_IC_LOADED_AT: float | None = None

# 旧因子名 → 新因子名（历史 IC 记录/旧缓存的平滑迁移）
LEGACY_MAP: dict[str, str] = flib.LEGACY_MAP


def load_ic_state(force_reload: bool = False) -> dict:
    """
    读取 factor_ic.json 的动态权重 + 翻转标记。
    返回 {"weights": {...}, "flips": {...}, "source": "ic"|"base", "updated_at": ...}

    容错策略（重要）：
      旧版要求 IC 文件的因子集合与硬编码集合**完全一致**才采纳，
      一旦新增/删除因子就整体回退到硬编码权重 —— 新因子永远用不上动态权重。
      新版改为「逐因子合并」：IC 文件里有该因子就用它的权重，
      没有的新因子用基础权重，缺失的旧因子直接丢弃，最后统一归一化。
    """
    global _IC_CACHE, _IC_LOADED_AT
    now = time.time()
    if (not force_reload and _IC_CACHE is not None
            and _IC_LOADED_AT and now - _IC_LOADED_AT < 30):
        return _IC_CACHE

    base = flib.base_weights()
    state = {"weights": dict(base), "flips": {}, "source": "base",
             "updated_at": None}

    path = os.path.join(CACHE_DIR, "factor_ic.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            ic_w = data.get("weights")
            if isinstance(ic_w, dict) and ic_w:
                merged = {}
                for name in base:
                    v = ic_w.get(name)
                    # 只接受合法正数权重，且不覆盖基础权重为 0 的因子
                    if isinstance(v, (int, float)) and v > 0:
                        merged[name] = float(v)
                    else:
                        merged[name] = base[name]
                total = sum(merged.values())
                if total > 0:
                    state["weights"] = {k: round(v / total, 4)
                                        for k, v in merged.items()}
                    state["flips"] = {
                        k: True for k, v in (data.get("flips") or {}).items()
                        if v and k in base
                    }
                    state["source"] = "ic"
                    state["updated_at"] = data.get("updated_at")
        except Exception:
            pass  # IC 文件损坏 → 静默回退基础权重

    _IC_CACHE = state
    _IC_LOADED_AT = now
    return state


def get_weights(force_reload: bool = False) -> dict:
    """当前生效的因子权重（动态权重优先，回退基础权重）。"""
    return load_ic_state(force_reload)["weights"]


def get_flips(force_reload: bool = False) -> dict:
    """需要翻转使用的因子（IC 显著为负）。"""
    return load_ic_state(force_reload)["flips"]


# ---------------------------------------------------------------- 兼容辅助
# ⚠️ 以下三个函数被 signal_generator.py 等下游以 mf._rsi / mf._atr / mf._sma
#    的形式直接调用。重构时曾误删导致整条流水线崩溃，不要再次移除。
#    新代码请优先直接用 factor_lib 里的同名函数。
def _sma(values: list[float], period: int) -> float | None:
    return flib._sma(values, period)


def _rsi(closes: list[float], period: int = 14) -> float | None:
    return flib._rsi(closes, period)


def _atr(klines: list, period: int = 14) -> float | None:
    """兼容旧签名：接收 K 线列表（旧→新），内部转为 KLineView。"""
    v = flib.KLineView(klines)
    v._build()
    return flib._atr(v, period)


# 展示阈值：权重低于此值的因子已被双重检验判定为无效/有害，
# 不能出现在"强项/弱项"里——否则等于展示层否定权重层的判断，误导决策。
SIGNAL_MIN_WEIGHT = 0.04


def _build_signals(scores: dict[str, float], flips: dict[str, bool],
                   extras: dict, weights: dict | None = None) -> list[str]:
    """从因子得分生成可读信号：列出最强 3 项与最弱 3 项。
    只展示在当前权重体系下真正"说话算数"的因子。
    翻转因子在括号内标注「(反向)」，避免读者误读方向。"""
    if not scores:
        return ["数据不足"]

    if weights:
        pool = {k: v for k, v in scores.items()
                if weights.get(k, 0) >= SIGNAL_MIN_WEIGHT}
    else:
        pool = dict(scores)
    if not pool:
        return ["因子信号不足"]

    ranked = sorted(pool.items(), key=lambda kv: kv[1], reverse=True)
    out: list[str] = []
    for name, s in ranked[:3]:
        if s >= 60:
            tag = "（反向）" if flips.get(name) else ""
            out.append(f"强项·{flib.FACTORS[name]['label']}{tag} {s:.0f}分")
    for name, s in ranked[-3:]:
        if s <= 40:
            tag = "（反向）" if flips.get(name) else ""
            out.append(f"弱项·{flib.FACTORS[name]['label']}{tag} {s:.0f}分")

    # 关键指标补充（下游 signal_generator 会展示这些字段）
    if extras.get("rsi") is not None:
        r = extras["rsi"]
        if r >= 70:
            out.append(f"RSI={r:.0f}，超买风险")
        elif r <= 30:
            out.append(f"RSI={r:.0f}，超卖区间")
    if extras.get("ma20") and extras.get("close"):
        if extras["close"] > extras["ma20"]:
            out.append("股价在MA20上方")
        else:
            out.append("股价跌破MA20")
    return out


def score_stock(klines: list, ctx: dict | None = None,
                code: str | None = None) -> dict:
    """
    对单只股票计算全部因子评分。
    klines: [[date, open, close, high, low, volume], ...] 旧->新

    返回结构与 v1 完全一致（下游无需改动）：
      {total_score, factor_scores, signals, rsi, ma20, ma60, atr_pct, coverage}
    """
    if not klines or len(klines) < 20:
        return {"total_score": 0, "factor_scores": {}, "signals": ["数据不足"],
                "rsi": None, "ma20": None, "ma60": None, "atr_pct": None,
                "coverage": 0.0}

    weights = get_weights()
    flips = get_flips()

    raws = flib.compute_raw(klines, ctx, code=code)
    res = flib.score_stock_raw(raws, weights, flips)

    # 关键指标（下游展示用，独立于因子体系）
    closes = [float(k[2]) for k in klines]
    last_close = closes[-1]
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)
    v = flib.KLineView(klines[-flib.MAX_LOOKBACK:])
    v._build()
    rsi_val = flib._rsi(v.closes, 14)
    atr_val = flib._atr(v, 14)

    extras = {"rsi": rsi_val, "ma20": ma20, "close": last_close}
    return {
        "total_score": res["total_score"],
        "factor_scores": res["factor_scores"],
        "signals": _build_signals(res["factor_scores"], flips, extras, weights),
        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "atr_pct": round(atr_val / last_close * 100, 2) if atr_val and last_close else None,
        "coverage": res["coverage"],
        "raw": {k: (round(x, 4) if isinstance(x, float) else x)
                for k, x in raws.items() if x is not None},
    }


def rank_stocks(codes: list[str] | None = None, top_n: int = 20) -> list[dict]:
    """
    对多只股票评分并排名。
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

    # 市场基准只需构造一次（beta / 特异波动因子依赖它）
    all_kl = {c: s.get("kline", []) for c, s in stocks.items() if s.get("kline")}
    mkt_ctx = flib.build_market_ctx(all_kl) if all_kl else {}

    results = []
    for code in codes:
        stock = stocks.get(code)
        if not stock:
            continue
        klines = stock.get("kline", [])
        if len(klines) < 20:
            continue
        dates = [str(k[0]) for k in klines[-flib.MAX_LOOKBACK:]]
        ctx = flib.slice_market_ctx(mkt_ctx, dates)
        result = score_stock(klines, ctx, code=code)
        result["code"] = code
        result["name"] = stock.get("name", code)
        results.append(result)

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    st = load_ic_state()
    print(f"\n权重来源: {st['source']}"
          + (f"  (IC 更新于 {st['updated_at']})" if st["updated_at"] else ""))
    if st["flips"]:
        print("翻转因子:", ", ".join(st["flips"]))

    ranking = rank_stocks()
    names = [n for n in flib.FACTOR_NAMES if any(
        n in r["factor_scores"] for r in ranking)][:6]
    header = f"{'排名':<4}{'代码':<10}{'名称':<10}{'总分':>6}" + "".join(
        f"{n[:9]:>10}" for n in names)
    print(f"\n=== 多因子选股排名 Top {len(ranking)}（{len(flib.FACTORS)} 因子）===")
    print(header)
    for i, r in enumerate(ranking, 1):
        fs = r["factor_scores"]
        row = f"{i:<4}{r['code']:<10}{r['name']:<10}{r['total_score']:>6}"
        row += "".join(f"{fs.get(n, 0):>10.0f}" for n in names)
        print(row)
    print("\n说明：分数为因子 raw 值映射后的 0-100，已对 IC 显著为负的因子翻转。")
