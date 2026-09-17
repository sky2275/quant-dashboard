#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_pattern_t1.py — 全市场「形态 → 次日上涨」扫描引擎
=========================================================
目标：回答「哪种形态走势的个股，买进后次日能上涨」

方法论（避免过拟合的三个关键设计）：
  1. 基准对比：先算全市场随机买入的基准胜率/收益，形态只统计「超额」部分
     —— 否则牛市里所有形态胜率都 >55%，全是假信号
  2. 显著性检验：t 统计量 = mean/(std/sqrt(N))，t<2 视为噪声
  3. 样本外检验：把时间轴切前后两半，两半都跑赢基准才算真有效

收益口径：
  ret_cc = T日收盘买入 → T+1收盘卖出   （隔夜+次日，主口径）
  ret_oc = T+1开盘买入 → T+1收盘卖出   （次日日内，次口径）
  gap    = T+1开盘 / T日收盘 - 1       （跳空，>9% 视为一字板买不进）

用法：
  python3 scripts/scan_pattern_t1.py
输出：
  cache/pattern_t1_stats.json   （每种形态的统计）
  cache/pattern_t1_samples.json （有效形态的真实案例，供报告引用）
"""
import os
import sys
import json
import math

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "cache")
DAILY = os.path.join(CACHE, "allmarket_daily.parquet")
BASIC = os.path.join(CACHE, "allmarket_basic.parquet")
OUT_STATS = os.path.join(CACHE, "pattern_t1_stats.json")
OUT_CASES = os.path.join(CACHE, "pattern_t1_cases.json")

MIN_BARS = 60          # 形态识别所需的最少历史K线
GAP_BLOCK = 0.09       # 次日高开 >9% 视为一字板/秒板，实际买不进
MAX_SAMPLE_PER_PAT = 400_000


# ── 工具函数 ────────────────────────────────────────────
def shift(arr, k):
    """shift(c,1)[i] = c[i-1]；shift(c,-1)[i] = c[i+1]；不足处为 nan"""
    out = np.full(arr.shape, np.nan, dtype=float)
    if k > 0:
        out[k:] = arr[:-k]
    elif k < 0:
        out[:k] = arr[-k:]
    else:
        out[:] = arr
    return out


def sma(arr, n):
    return pd.Series(arr).rolling(n, min_periods=n).mean().values


def _ema_np(arr, n):
    """指数移动平均，前 n-1 个为 nan"""
    out = np.full(arr.shape, np.nan, dtype=float)
    if len(arr) < n:
        return out
    alpha = 2.0 / (n + 1)
    out[n - 1] = arr[:n].mean()
    for i in range(n, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def roll_max_prev(arr, n):
    """不含当日、过去 n 日最高"""
    return pd.Series(arr).shift(1).rolling(n, min_periods=n).max().values


def roll_min_prev(arr, n):
    return pd.Series(arr).shift(1).rolling(n, min_periods=n).min().values


def roll_max_incl(arr, n):
    return pd.Series(arr).rolling(n, min_periods=n).max().values


def roll_min_incl(arr, n):
    return pd.Series(arr).rolling(n, min_periods=n).min().values


def limit_pct(ts_code: str) -> float:
    """涨跌幅限制：创业板/科创板 20%，北交所 30%，其余 10%"""
    c = ts_code[:6]
    if c.startswith(("300", "301", "688", "689")):
        return 19.8
    if c.startswith(("8", "4", "920")):
        return 29.8
    return 9.8


# ── 形态识别：全部返回 boolean array（长度 = n） ──────────
def build_patterns(o, h, l, c, v, pct, lim):
    """输入单只股票的 numpy 数组，返回 {形态名: bool mask}"""
    n = len(c)
    P = {}

    co, oo, ho, lo, vo, pcto = (shift(x, 1) for x in (c, o, h, l, v, pct))
    c2, o2 = shift(c, 2), shift(o, 2)
    c3 = shift(c, 3)

    ma5, ma10, ma20 = sma(c, 5), sma(c, 10), sma(c, 20)
    ema20 = _ema_np(c, 20)
    ema20_5 = shift(ema20, 5)
    vma5, vma20 = sma(v, 5), sma(v, 20)

    body = np.abs(c - o)
    rng = (h - l)
    rng_safe = np.where(rng <= 0, np.nan, rng)
    lower_sh = np.minimum(o, c) - l
    upper_sh = h - np.maximum(o, c)

    hi20_prev = roll_max_prev(h, 20)
    lo20_prev = roll_min_prev(l, 20)
    hi20_incl = roll_max_incl(h, 20)
    lo60_incl = roll_min_incl(l, 60)

    is_up = c > o
    is_dn = c < o

    # 基础有效位（有足够历史 + 当日非停牌）
    ok = ~np.isnan(ma20) & ~np.isnan(vma20) & (v > 0) & (rng > 0)
    ok &= ~np.isnan(hi20_prev) & ~np.isnan(lo60_incl)

    # ---- A. K线形态 ----
    # 1 阳包阴
    dn1 = shift(c, 1) < shift(o, 1)          # 昨日阴线
    P["阳包阴"] = ok & is_up & dn1 & (c >= oo) & (o <= co) & (pct > 1.0)

    # 2 早晨之星（大阴 + 小星 + 收复大阳）
    big_dn2 = (o2 - c2) / np.where(c2 > 0, c2, np.nan) > 0.02
    small_star = (np.abs(co - oo) / np.where(co > 0, co, np.nan)) < 0.015
    big_up = (c - o) / np.where(o > 0, o, np.nan) > 0.02
    P["早晨之星"] = ok & big_dn2 & small_star & big_up & (c > (o2 + c2) / 2)

    # 3 长下影（探底回升）
    P["长下影线"] = ok & (lower_sh / rng_safe > 0.55) & (lower_sh > body * 1.2)

    # 4 光头阳（收盘即最高，强势收尾）
    P["光头阳线"] = ok & (c >= h * 0.999) & (pct > 2.0)

    # 5 低位十字星
    P["低位十字星"] = ok & (body / rng_safe < 0.15) & (c < ma20)

    # 6 锤子线（底部反转）
    P["锤子线"] = ok & (lower_sh > body * 2) & (upper_sh < body * 0.6) & \
        (body / rng_safe < 0.35) & (c < ma20)

    # ---- B. 量能 ----
    # 7 缩量回踩（上涨趋势中的缩量回调）
    P["缩量回踩"] = ok & (ma5 > ma20) & (c > ma20) & (pct < 0) & (v < vma5 * 0.75)

    # 8 放量突破（创20日新高 + 放量）
    P["放量突破"] = ok & (c > hi20_prev) & (v > vma5 * 1.5) & (pct > 0)

    # 9 地量见地价
    P["地量地价"] = ok & (v < vma20 * 0.5) & (c < lo60_incl * 1.10)

    # 10 温和放量小阳（吸筹）
    P["温和放量小阳"] = ok & (v > vma5 * 1.2) & (v < vma5 * 2.0) & \
        (pct > 0) & (pct < 3.0)

    # ---- C. 趋势 / 位置 ----
    # 11 EMA20 回踩不破
    ema_up = ema20 > ema20_5
    P["EMA20回踩不破"] = ok & ema_up & (c > ema20) & (l <= ema20 * 1.01) & \
        (l >= ema20 * 0.96) & (pct < 2.0)

    # 12 重回 EMA20 上方
    below_y = shift(c, 1) < shift(ema20, 1)
    P["重回EMA20上方"] = ok & (c > ema20) & below_y

    # 13 连阳后首阴（3连阳后洗盘）
    P["连阳后首阴"] = ok & (pct < 0) & (pcto > 0) & (shift(pct, 2) > 0) & \
        (shift(pct, 3) > 0) & (c > ma20)

    # 14 平台突破（20日横盘后向上）
    plat_hi = roll_max_prev(h, 20)
    plat_lo = roll_min_prev(l, 20)
    flat = (plat_hi - plat_lo) / np.where(plat_lo > 0, plat_lo, np.nan) < 0.12
    P["平台突破"] = ok & flat & (c > plat_hi * 1.01) & (v > shift(vma5, 1) * 1.3)

    # 15 超跌反弹（20日跌超15%后收阳）
    c20 = shift(c, 20)
    dd20 = c / np.where(c20 > 0, c20, np.nan) - 1
    P["超跌反弹"] = ok & (~np.isnan(dd20)) & (dd20 < -0.15) & (pct > 0)

    # 16 多头排列
    P["多头排列"] = ok & (ma5 > ma10) & (ma10 > ma20) & is_up & (pct > 0)

    # ---- D. 涨停相关 ----
    # 17 涨停次日缩量整理
    y_limit = pcto >= lim * 0.98
    P["涨停后缩量"] = ok & y_limit & (v < vo * 0.8) & (np.abs(pct) < 3.0)

    # 18 首板放量（20日内首次涨停）
    was_limit = np.zeros(n, dtype=bool)
    for k in range(1, 21):
        was_limit |= (shift(pct, k) >= lim * 0.98)
    P["首板放量"] = ok & (pct >= lim * 0.98) & (~was_limit) & (v > vma5 * 1.5)

    # 19 二连板
    P["二连板"] = ok & (pct >= lim * 0.98) & y_limit

    return P


# ── 主流程 ──────────────────────────────────────────────
def main():
    if not os.path.exists(DAILY):
        print(f"[ERR] 缺 {DAILY}，先跑 fetch_allmarket_daily.py")
        return 1

    print("[1/4] 读数据 ...")
    df = pd.read_parquet(DAILY)
    name_map = {}
    if os.path.exists(BASIC):
        b = pd.read_parquet(BASIC)
        name_map = dict(zip(b["ts_code"], b["name"]))
    print(f"      {len(df):,} 条 / {df['ts_code'].nunique()} 只 / "
          f"{df['trade_date'].nunique()} 天")

    # 过滤 ST / 退市
    df["_nm"] = df["ts_code"].map(name_map)
    before = df["ts_code"].nunique()
    df = df[~df["_nm"].fillna("").str.contains("ST|退", regex=True)]
    print(f"      剔除 ST/退市后：{df['ts_code'].nunique()} 只（原 {before}）")

    # 收集样本：{形态: [(ret_cc, ret_oc, gap, date, code)]}
    print("[2/4] 扫描形态与次日收益 ...")
    samples = {}
    base_cc, base_oc = [], []

    codes = df["ts_code"].unique()
    done = 0
    for code, g in df.groupby("ts_code", sort=False):
        done += 1
        g = g.sort_values("trade_date")
        if len(g) < MIN_BARS + 2:
            continue
        o = g["open"].values.astype(float)
        h = g["high"].values.astype(float)
        l = g["low"].values.astype(float)
        c = g["close"].values.astype(float)
        v = g["vol"].values.astype(float)
        pct = g["pct_chg"].values.astype(float)
        dates = g["trade_date"].values
        n = len(c)
        if np.isnan(c).any() or np.isnan(o).any():
            continue

        lim = limit_pct(code)

        # 次日收益（最后一根无次日，置 nan）
        ret_cc = np.full(n, np.nan)
        ret_cc[:-1] = c[1:] / c[:-1] - 1
        ret_oc = np.full(n, np.nan)
        ret_oc[:-1] = c[1:] / np.where(o[1:] > 0, o[1:], np.nan) - 1
        gap = np.full(n, np.nan)
        gap[:-1] = o[1:] / c[:-1] - 1

        try:
            P = build_patterns(o, h, l, c, v, pct, lim)
        except Exception:
            continue

        # 有效位：有次日收益 + 次日不是一字板买不进
        tradable = ~np.isnan(ret_cc) & (gap < GAP_BLOCK) & (gap > -0.11)

        # 基准样本（抽样，避免内存爆炸）
        idx_base = np.where(tradable[MIN_BARS:])[0] + MIN_BARS
        if len(idx_base) > 60:
            step = max(1, len(idx_base) // 60)
            sel = idx_base[::step]
            base_cc.extend(ret_cc[sel].tolist())
            base_oc.extend(ret_oc[sel].tolist())

        for pname, mask in P.items():
            idx = np.where(mask & tradable)[0]
            if len(idx) == 0:
                continue
            arr = samples.setdefault(pname, [])
            if len(arr) > MAX_SAMPLE_PER_PAT:
                continue
            step = max(1, len(idx) // 3000)   # 每形态每股最多留 3000 个
            for i in idx[::step]:
                if np.isnan(ret_cc[i]) or np.isnan(ret_oc[i]):
                    continue
                arr.append((float(ret_cc[i]), float(ret_oc[i]),
                            float(gap[i]), str(dates[i]), str(code)))
        if done % 1000 == 0:
            print(f"      {done}/{len(codes)} ...")

    # ── 基准 ────────────────────────────────────────────
    bcc = np.array(base_cc, dtype=float)
    boc = np.array(base_oc, dtype=float)
    base = {
        "n": int(len(bcc)),
        "win_rate_cc": float((bcc > 0).mean() * 100),
        "mean_cc": float(bcc.mean() * 100),
        "median_cc": float(np.median(bcc) * 100),
        "win_rate_oc": float((boc > 0).mean() * 100),
        "mean_oc": float(boc.mean() * 100),
    }
    print(f"\n[3/4] 基准（全市场随机买入）：N={base['n']:,} "
          f"胜率={base['win_rate_cc']:.2f}% 平均={base['mean_cc']:+.3f}%")

    # ── 各形态统计 ───────────────────────────────────────
    print("[4/4] 统计各形态 ...")
    stats = []
    for pname, arr in samples.items():
        a = np.array([x[0] for x in arr], dtype=float)   # ret_cc
        aoc = np.array([x[1] for x in arr], dtype=float)  # ret_oc
        N = len(a)
        if N < 300:
            continue
        mean = a.mean()
        std = a.std(ddof=1)
        t = mean / (std / math.sqrt(N)) if std > 0 else 0.0
        wins = a[a > 0]
        loss = a[a <= 0]
        pl = (wins.mean() / abs(loss.mean())) if len(wins) and len(loss) and loss.mean() != 0 else None

        # 样本外检验：按日期切前后半
        ds = sorted(set(x[3] for x in arr))
        mid = ds[len(ds) // 2]
        a1 = np.array([x[0] for x in arr if x[3] < mid], dtype=float)
        a2 = np.array([x[0] for x in arr if x[3] >= mid], dtype=float)
        w1 = float((a1 > 0).mean() * 100) if len(a1) else None
        w2 = float((a2 > 0).mean() * 100) if len(a2) else None
        m1 = float(a1.mean() * 100) if len(a1) else None
        m2 = float(a2.mean() * 100) if len(a2) else None

        stats.append({
            "pattern": pname,
            "n": N,
            "win_rate": float((a > 0).mean() * 100),
            "excess_win": float((a > 0).mean() * 100 - base["win_rate_cc"]),
            "mean_ret": float(mean * 100),
            "excess_ret": float(mean * 100 - base["mean_cc"]),
            "median_ret": float(np.median(a) * 100),
            "t_stat": float(t),
            "profit_loss": float(pl) if pl else None,
            "win_rate_oc": float((aoc > 0).mean() * 100),
            "mean_oc": float(aoc.mean() * 100),
            "oos_split_date": mid,
            "oos_win_1": w1, "oos_win_2": w2,
            "oos_mean_1": m1, "oos_mean_2": m2,
            "stable": bool(w1 and w2 and w1 > base["win_rate_cc"] and w2 > base["win_rate_cc"]),
        })

    stats.sort(key=lambda x: -x["excess_ret"])

    out = {
        "asof": str(df["trade_date"].max()),
        "universe": int(df["ts_code"].nunique()),
        "days": int(df["trade_date"].nunique()),
        "baseline": base,
        "patterns": stats,
    }
    with open(OUT_STATS, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # 案例：给稳定有效形态各留若干真实样本
    good = [s for s in stats if s["stable"] and s["excess_ret"] > 0 and s["t_stat"] > 2]
    cases = {}
    for s in good:
        arr = samples[s["pattern"]]
        # 取收益最高的若干真实案例（同时保留亏损案例以呈现真实分布）
        arr_sorted = sorted(arr, key=lambda x: -x[0])
        top = arr_sorted[:12]
        cases[s["pattern"]] = [
            {"date": x[3], "code": x[4][:6], "name": name_map.get(x[4], x[4]),
             "ret_cc": round(x[0] * 100, 2), "ret_oc": round(x[1] * 100, 2),
             "gap": round(x[2] * 100, 2)} for x in top
        ]
    with open(OUT_CASES, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=1)

    print(f"\n{'形态':<14}{'样本':>8}{'胜率':>8}{'超额胜率':>9}"
          f"{'均收益':>9}{'超额收益':>9}{'t值':>7}{'稳定':>6}")
    print("-" * 72)
    for s in stats:
        print(f"{s['pattern']:<14}{s['n']:>8}{s['win_rate']:>7.1f}%"
              f"{s['excess_win']:>+8.1f}%{s['mean_ret']:>+8.2f}%"
              f"{s['excess_ret']:>+8.2f}%{s['t_stat']:>7.2f}"
              f"{'✓' if s['stable'] else '✗':>6}")
    print(f"\n[OK] → {OUT_STATS}")
    print(f"[OK] → {OUT_CASES}（{len(cases)} 个有效形态的案例）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
